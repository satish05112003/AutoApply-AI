"""
Sheets Service — Orchestration layer for Google OAuth spreadsheet operations.

Responsibilities:
  - CRUD on GoogleIntegration records
  - Token lifecycle (delegates to GoogleOAuthService)
  - Spreadsheet provisioning (delegates to GoogleSheetsAPIClient)
  - EventQueue processing — maps application events to sheet rows
  - Writing records to WrittenRecord for idempotent upsert behavior

This service is always called from either:
  a) API router (async, awaitable) — for status reads
  b) Celery tasks (async, via asyncio.run) — for writes

PostgreSQL is always the source of truth. Sheets is a display layer.
"""
import os
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.sheets import GoogleIntegration, UserSpreadsheet, EventQueue, WrittenRecord
from app.models.applications import Application, ApplicationEvent
from app.models.jobs import JobPosting
from app.models.profile import Resume, CandidateProfile, Preferences
from app.integrations.google_sheets_client import (
    GoogleSheetsAPIClient,
    GoogleSheetsAPIError,
    SPREADSHEET_TABS,
    classify_application_tab,
)
from app.services.google_oauth_service import GoogleOAuthService, GoogleOAuthTokenError

logger = logging.getLogger("autoapply_ai.services.sheets")

# Centralized dedicated Google Sheets Synchronization Logger
sync_log_dir = "logs"
os.makedirs(sync_log_dir, exist_ok=True)
sync_log_file = os.path.join(sync_log_dir, "google_sheets_sync.log")

sync_log_handler = logging.FileHandler(sync_log_file, encoding="utf-8")
sync_log_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s"
))
sync_log_handler.setLevel(logging.INFO)

sheets_sync_logger = logging.getLogger("google_sheets_sync")
sheets_sync_logger.addHandler(sync_log_handler)
sheets_sync_logger.setLevel(logging.INFO)
sheets_sync_logger.propagate = False


class SheetsService:
    """
    Async service class for all Google Sheets integration operations.
    All methods are static — no instantiation required.
    """

    # ------------------------------------------------------------------
    # Integration CRUD
    # ------------------------------------------------------------------

    @staticmethod
    async def get_integration(
        db: AsyncSession, user_id
    ) -> Optional[GoogleIntegration]:
        """Fetch the GoogleIntegration record for a user, or None if not connected."""
        stmt = select(GoogleIntegration).where(GoogleIntegration.user_id == user_id)
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def save_integration(
        db: AsyncSession,
        user_id,
        access_token: str,
        refresh_token: Optional[str],
        token_expiry: datetime,
        google_email: str,
    ) -> GoogleIntegration:
        """
        Upsert a GoogleIntegration record after successful OAuth exchange.
        If the user already has an integration, tokens are updated in-place.

        Args:
            db:            AsyncSession
            user_id:       UUID of the user
            access_token:  New access token
            refresh_token: New refresh token (may be None on re-auth without consent)
            token_expiry:  Expiry datetime (timezone-aware)
            google_email:  Google account email

        Returns:
            The saved/updated GoogleIntegration instance.
        """
        existing = await SheetsService.get_integration(db, user_id)

        if existing:
            existing.access_token = access_token
            if refresh_token:
                existing.refresh_token = refresh_token
            existing.token_expiry = token_expiry
            existing.google_email = google_email
            existing.updated_at = datetime.now(timezone.utc)
            db.add(existing)
            await db.commit()
            await db.refresh(existing)
            logger.info(f"Updated GoogleIntegration for user {user_id}")
            return existing

        integration = GoogleIntegration(
            user_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expiry=token_expiry,
            google_email=google_email,
            is_provisioned=False,
        )
        db.add(integration)
        await db.commit()
        await db.refresh(integration)
        logger.info(f"Created new GoogleIntegration for user {user_id}")
        return integration

    @staticmethod
    async def delete_integration(db: AsyncSession, user_id) -> bool:
        """
        Remove the GoogleIntegration record. Revokes tokens first (best effort).

        Returns:
            True if a record was found and deleted, False if no record existed.
        """
        integration = await SheetsService.get_integration(db, user_id)
        if not integration:
            return False

        # Revoke access token (non-blocking, non-fatal)
        try:
            await GoogleOAuthService.revoke_token(integration.access_token)
        except Exception as e:
            logger.warning(f"Token revocation failed for user {user_id} (continuing): {e}")

        await db.delete(integration)
        await db.commit()
        logger.info(f"Deleted GoogleIntegration for user {user_id}")
        return True

    # ------------------------------------------------------------------
    # Spreadsheet provisioning — called by Celery task
    # ------------------------------------------------------------------

    @staticmethod
    async def provision_spreadsheet(db: AsyncSession, user_id: str, user_name: str) -> GoogleIntegration:
        """
        Create and configure the user's personal Google Spreadsheet.
        Called by the `provision_user_spreadsheet` Celery task after OAuth.

        Steps:
          1. Load the integration + get a valid token
          2. Create a blank spreadsheet via Sheets API
          3. Add + format the 6 canonical tabs
          4. Share with the user's Google email
          5. Persist spreadsheet_id, spreadsheet_url, tab_gids to DB

        Args:
            db:        AsyncSession
            user_id:   String UUID of the user
            user_name: Full name for the spreadsheet title

        Returns:
            Updated GoogleIntegration with is_provisioned=True

        Raises:
            ValueError: If no integration found for user_id
            GoogleOAuthTokenError: If token refresh fails
            GoogleSheetsAPIError: If spreadsheet creation fails
        """
        import uuid as _uuid
        uid = _uuid.UUID(user_id) if isinstance(user_id, str) else user_id

        integration = await SheetsService.get_integration(db, uid)
        if not integration:
            raise ValueError(f"No GoogleIntegration found for user {user_id}")

        # Get a valid (possibly refreshed) access token
        access_token = await GoogleOAuthService.get_valid_access_token(db, integration)

        client = GoogleSheetsAPIClient(access_token=access_token)

        # Create the spreadsheet
        title = f"AutoApply AI — {user_name} Job Tracker"
        spreadsheet_id, spreadsheet_url = await client.create_spreadsheet(title)

        # Provision all tabs with formatted headers
        tab_gids = await client.provision_tabs(spreadsheet_id)

        # Share with user's own Google account so they can open it
        await client.share_spreadsheet(spreadsheet_id, integration.google_email)

        # Persist to DB
        integration.spreadsheet_id = spreadsheet_id
        integration.spreadsheet_url = spreadsheet_url
        integration.tab_gids = tab_gids
        integration.is_provisioned = True
        integration.last_sync_at = datetime.now(timezone.utc)
        integration.updated_at = datetime.now(timezone.utc)
        db.add(integration)
        await db.commit()
        await db.refresh(integration)

        # Enqueue and trigger immediate backfill sync
        try:
            await SheetsService.enqueue_historical_backfill(db, uid)
            await SheetsService.process_pending_events(db)
            logger.info(f"Triggered immediate historical data sync for connected user {user_id}")
        except Exception as backfill_err:
            logger.error(f"Failed running immediate historical sync: {backfill_err}", exc_info=True)

        logger.info(
            f"Successfully provisioned spreadsheet for user {user_id}: "
            f"{spreadsheet_id} ({spreadsheet_url})"
        )
        return integration

    # ------------------------------------------------------------------
    # EventQueue processing — called by Celery periodic task
    # ------------------------------------------------------------------

    @staticmethod
    async def process_pending_events(db: AsyncSession) -> int:
        """
        Fetch PENDING events from sheets.event_queue and write them to the
        corresponding user's Google Spreadsheet.

        Each event is processed atomically:
          - Load user's GoogleIntegration (skip if disconnected)
          - Get valid access token (auto-refresh if needed)
          - Write/update row via GoogleSheetsAPIClient
          - Track written rows in WrittenRecord for idempotent updates
          - Mark event as SUCCESS or increment retry_count on failure
        """
        from app.config import settings

        stmt = (
            select(EventQueue)
            .where(EventQueue.status == "PENDING")
            .order_by(EventQueue.created_at.asc())
            .limit(settings.SHEETS_BATCH_SIZE)
        )
        result = await db.execute(stmt)
        events = result.scalars().all()

        processed_count = 0
        updated_users = set()

        for event in events:
            t_start = time.time()
            integration = None
            try:
                # Load integration for this user
                integration = await SheetsService.get_integration(db, event.user_id)
                if not integration or not integration.is_provisioned:
                    logger.debug(
                        f"Skipping event {event.id}: user {event.user_id} has no active integration"
                    )
                    event.status = "SKIPPED"
                    event.last_error = "User has not connected Google Sheets"
                    db.add(event)
                    await db.commit()
                    continue

                # Get valid access token (auto-refresh)
                try:
                    access_token = await GoogleOAuthService.get_valid_access_token(db, integration)
                except (GoogleOAuthTokenError, ValueError) as e:
                    logger.warning(f"Token invalid for user {event.user_id}: {e}")
                    event.retry_count += 1
                    event.last_error = str(e)
                    if event.retry_count >= event.max_retries:
                        event.status = "FAILED"
                    db.add(event)
                    await db.commit()
                    
                    duration = time.time() - t_start
                    sheets_sync_logger.error(
                        f"User={event.user_id} | SheetID={integration.spreadsheet_id} | "
                        f"EventType={event.event_type} | RowsWritten=0 | Retries={event.retry_count} | "
                        f"Duration={duration:.2f}s | Error=Token invalid ({e}) | Response=FAILED"
                    )
                    continue

                sheets_client = GoogleSheetsAPIClient(access_token=access_token)
                payload = event.payload

                # Ensure we have application_id
                app_id = payload.get("application_id")
                if not app_id:
                    event.status = "FAILED"
                    event.last_error = "Missing application_id in event payload"
                    db.add(event)
                    await db.commit()
                    continue

                # Query latest data from PostgreSQL (Source of Truth)
                stmt_app = select(Application).where(Application.id == (UUID(app_id) if isinstance(app_id, str) else app_id))
                res_app = await db.execute(stmt_app)
                app = res_app.scalars().first()
                if not app:
                    event.status = "FAILED"
                    event.last_error = f"Application {app_id} not found in database"
                    db.add(event)
                    await db.commit()
                    continue

                stmt_job = select(JobPosting).where(JobPosting.id == app.job_id)
                res_job = await db.execute(stmt_job)
                job = res_job.scalars().first()
                if not job:
                    raise ValueError(f"Job posting {app.job_id} not found for application {app.id}")

                stmt_res = select(Resume).where(Resume.id == app.resume_id)
                res_res = await db.execute(stmt_res)
                resume = res_res.scalars().first()

                # Query user profile and preferences to build breakdown dynamically
                stmt_p = select(CandidateProfile).where(CandidateProfile.user_id == app.user_id)
                res_p = await db.execute(stmt_p)
                profile = res_p.scalars().first()

                stmt_pref = select(Preferences).where(Preferences.user_id == app.user_id)
                res_pref = await db.execute(stmt_pref)
                prefs = res_pref.scalars().first()

                breakdown_parts = []
                if job.required_skills and prefs and prefs.required_skills:
                    j_skills = set(s.lower().strip() for s in job.required_skills)
                    c_skills = set(s.lower().strip() for s in prefs.required_skills)
                    matched = len(j_skills.intersection(c_skills))
                    breakdown_parts.append(f"Skills: {matched}/{len(j_skills)}")
                else:
                    breakdown_parts.append("Skills: —")

                if job.experience_min_years is not None and profile and profile.years_of_experience is not None:
                    exp_diff = float(profile.years_of_experience) - float(job.experience_min_years)
                    status_exp = "Match" if exp_diff >= 0 else f"Need {job.experience_min_years}y (Have {profile.years_of_experience}y)"
                    breakdown_parts.append(f"Exp: {status_exp}")
                else:
                    breakdown_parts.append("Exp: —")

                if job.location and prefs and prefs.preferred_locations:
                    job_loc = job.location.lower()
                    is_loc_match = any(loc.lower() in job_loc for loc in prefs.preferred_locations)
                    status_loc = "Match" if is_loc_match else ("Remote" if job.is_remote else "Mismatch")
                    breakdown_parts.append(f"Loc: {status_loc}")
                else:
                    breakdown_parts.append("Loc: —")

                match_breakdown_str = ", ".join(breakdown_parts)

                # Fetch application events to build timeline
                stmt_ev = select(ApplicationEvent).where(ApplicationEvent.application_id == app.id).order_by(ApplicationEvent.created_at.asc())
                res_ev = await db.execute(stmt_ev)
                ev_list = res_ev.scalars().all()
                timeline_str = " -> ".join([ev.event_type for ev in ev_list]) if ev_list else app.status

                # Build modern sync payload
                sync_payload = {
                    "application_id": str(app.id),
                    "company_name": job.company_name,
                    "role_title": job.role_title,
                    "location": job.location or "Remote",
                    "source": job.source or "LinkedIn",
                    "resume_name": resume.original_filename if resume else "Resume",
                    "match_score": int(app.match_score) if app.match_score is not None else 0,
                    "match_breakdown": match_breakdown_str,
                    "status": app.status,
                    "timeline": timeline_str,
                    "errors": app.last_error or "—",
                    "interview_status": "Scheduled" if app.status in ("INTERVIEW", "INTERVIEWING", "INTERVIEW_SCHEDULED", "OA_RECEIVED") else "—",
                    "recruiter_contact": app.notes or "—",
                    "source_url": job.source_url,
                    "submitted_at": app.submitted_at.strftime("%Y-%m-%d") if app.submitted_at else (app.created_at.strftime("%Y-%m-%d") if app.created_at else datetime.now(timezone.utc).strftime("%Y-%m-%d")),
                    "notes": app.notes or "",
                }

                rows_written = 0

                # 1. Sync to All Jobs sheet (always)
                all_jobs_tab = "🔍 All Jobs"
                job_row_data = SheetsService._build_job_row(sync_payload)
                stmt_wr_job = select(WrittenRecord).where(
                    WrittenRecord.user_id == event.user_id,
                    WrittenRecord.sheet_name == all_jobs_tab,
                    WrittenRecord.record_id == app_id,
                )
                res_wr_job = await db.execute(stmt_wr_job)
                record_job = res_wr_job.scalars().first()

                job_success = False
                if record_job and record_job.row_index:
                    job_success = await sheets_client.update_row(
                        spreadsheet_id=integration.spreadsheet_id,
                        tab_name=all_jobs_tab,
                        row_index=record_job.row_index,
                        row_data=job_row_data,
                    )
                    if job_success:
                        record_job.data = sync_payload
                        record_job.last_updated_at = datetime.now(timezone.utc)
                        db.add(record_job)
                        rows_written += 1
                else:
                    row_index = await sheets_client.append_row(
                        spreadsheet_id=integration.spreadsheet_id,
                        tab_name=all_jobs_tab,
                        row_data=job_row_data,
                    )
                    if row_index:
                        job_success = True
                        record_job = WrittenRecord(
                            user_id=event.user_id,
                            sheet_name=all_jobs_tab,
                            record_id=app_id,
                            record_type="JOB",
                            row_index=row_index,
                            data=sync_payload,
                        )
                        db.add(record_job)
                        rows_written += 1

                # 2. Sync to Applications sheet if not skipped
                is_skipped = app.status.upper().startswith("SKIPPED_")
                app_success = True
                if not is_skipped:
                    app_row_data = SheetsService._build_application_row(sync_payload)
                    primary_tab = "📊 Applications"
                    
                    stmt_wr_app = select(WrittenRecord).where(
                        WrittenRecord.user_id == event.user_id,
                        WrittenRecord.sheet_name == primary_tab,
                        WrittenRecord.record_id == app_id,
                    )
                    res_wr_app = await db.execute(stmt_wr_app)
                    record_app = res_wr_app.scalars().first()

                    app_success = False
                    if record_app and record_app.row_index:
                        app_success = await sheets_client.update_row(
                            spreadsheet_id=integration.spreadsheet_id,
                            tab_name=primary_tab,
                            row_index=record_app.row_index,
                            row_data=app_row_data,
                        )
                        if app_success:
                            record_app.data = sync_payload
                            record_app.last_updated_at = datetime.now(timezone.utc)
                            db.add(record_app)
                            rows_written += 1
                    else:
                        row_index = await sheets_client.append_row(
                            spreadsheet_id=integration.spreadsheet_id,
                            tab_name=primary_tab,
                            row_data=app_row_data,
                        )
                        if row_index:
                            app_success = True
                            record_app = WrittenRecord(
                                user_id=event.user_id,
                                sheet_name=primary_tab,
                                record_id=app_id,
                                record_type="APPLICATION",
                                row_index=row_index,
                                data=sync_payload,
                            )
                            db.add(record_app)
                            rows_written += 1

                # 3. Sync to Secondary tab (Interviews / Offers / Rejected) if applicable
                secondary_tab = classify_application_tab(job.role_title, app.status)
                if app_success and secondary_tab != "📊 Applications":
                    secondary_row = SheetsService._build_secondary_row(sync_payload, secondary_tab)
                    sec_key = f"{app_id}_{secondary_tab}"

                    stmt_wr2 = select(WrittenRecord).where(
                        WrittenRecord.user_id == event.user_id,
                        WrittenRecord.sheet_name == secondary_tab,
                        WrittenRecord.record_id == sec_key,
                    )
                    res_wr2 = await db.execute(stmt_wr2)
                    record2 = res_wr2.scalars().first()

                    if record2 and record2.row_index:
                        await sheets_client.update_row(
                            spreadsheet_id=integration.spreadsheet_id,
                            tab_name=secondary_tab,
                            row_index=record2.row_index,
                            row_data=secondary_row,
                        )
                        rows_written += 1
                    else:
                        row_idx2 = await sheets_client.append_row(
                            spreadsheet_id=integration.spreadsheet_id,
                            tab_name=secondary_tab,
                            row_data=secondary_row,
                        )
                        if row_idx2:
                            db.add(WrittenRecord(
                                user_id=event.user_id,
                                sheet_name=secondary_tab,
                                record_id=sec_key,
                                record_type="APPLICATION",
                                row_index=row_idx2,
                                data=sync_payload,
                            ))
                            rows_written += 1

                if job_success and app_success:
                    event.status = "SUCCESS"
                    event.processed_at = datetime.now(timezone.utc)
                    processed_count += 1
                    integration.last_sync_at = datetime.now(timezone.utc)
                    db.add(integration)
                    
                    # Track user for metrics update
                    updated_users.add((event.user_id, integration.spreadsheet_id))
                    
                    duration = time.time() - t_start
                    sheets_sync_logger.info(
                        f"User={event.user_id} | SheetID={integration.spreadsheet_id} | "
                        f"EventType={event.event_type} | RowsWritten={rows_written} | Retries={event.retry_count} | "
                        f"Duration={duration:.2f}s | Error=None | Response=HTTP 200"
                    )
                else:
                    raise RuntimeError("Failed writing to Google Sheets")

            except Exception as e:
                logger.error(f"Failed to process sheet event '{event.id}': {e}", exc_info=True)
                event.retry_count += 1
                event.last_error = str(e)[:500]
                if event.retry_count >= event.max_retries:
                    event.status = "FAILED"
                
                duration = time.time() - t_start
                sheets_sync_logger.error(
                    f"User={event.user_id} | SheetID={integration.spreadsheet_id if integration else 'None'} | "
                    f"EventType={event.event_type} | RowsWritten=0 | Retries={event.retry_count} | "
                    f"Duration={duration:.2f}s | Error={str(e)} | Response=FAILED"
                )

            db.add(event)
            await db.commit()

        # Recalculate metrics for all updated users
        for user_id, spreadsheet_id in updated_users:
            try:
                await SheetsService.recalculate_user_metrics(db, user_id, spreadsheet_id)
                logger.info(f"Recalculated weekly metrics for user {user_id}")
            except Exception as metr_err:
                logger.error(f"Failed to recalculate weekly metrics for user {user_id}: {metr_err}", exc_info=True)

        return processed_count

    # ------------------------------------------------------------------
    # Row builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_application_row(payload: dict) -> list:
        """Build the row for the 📊 Applications tab from an event payload."""
        return [
            payload.get("submitted_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            payload.get("company_name", "Unknown"),
            payload.get("role_title", "Developer"),
            payload.get("location") or "Remote",
            payload.get("source") or "LinkedIn",
            payload.get("resume_name") or "Resume",
            f"{payload.get('match_score') or 0}%",
            payload.get("match_breakdown") or "—",
            payload.get("status", "SUBMITTED"),
            payload.get("timeline") or "—",
            payload.get("errors") or "—",
            payload.get("interview_status") or "—",
            payload.get("recruiter_contact") or "—",
            payload.get("source_url") or "",
            payload.get("notes") or "",
        ]

    @staticmethod
    def _build_job_row(payload: dict) -> list:
        """Build the row for the 🔍 All Jobs tab from an event payload."""
        return [
            payload.get("submitted_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            payload.get("company_name", "Unknown"),
            payload.get("role_title", "Developer"),
            payload.get("location") or "Remote",
            payload.get("source") or "LinkedIn",
            f"{payload.get('match_score') or 0}%",
            payload.get("status", "DISCOVERED"),
            payload.get("source_url") or "",
        ]

    @staticmethod
    def _build_secondary_row(payload: dict, tab_name: str) -> list:
        """Build a row appropriate for Interview / Offer / Rejected tabs."""
        date = payload.get("submitted_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        company = payload.get("company_name", "Unknown")
        role = payload.get("role_title", "Developer")

        if tab_name == "🎯 Interviews":
            return [
                date, company, role,
                payload.get("interview_type") or "—",
                payload.get("interview_round") or "1",
                payload.get("recruiter_contact") or "—",
                payload.get("interview_status") or "Scheduled",
                "", "",
            ]
        elif tab_name == "🏆 Offers":
            return [date, company, role, "—", "USD", "—", "—", "Pending", ""]
        elif tab_name == "❌ Rejected":
            return [date, company, role, payload.get("status", "REJECTED"), "—", ""]
        else:
            return [date, company, role, payload.get("source_url") or ""]

    @staticmethod
    def _get_week_start(dt: datetime) -> str:
        """Get the Monday of the week for a given datetime, formatted as YYYY-MM-DD."""
        date_obj = dt.date()
        monday = date_obj - timedelta(days=date_obj.weekday())
        return monday.strftime("%Y-%m-%d")

    @staticmethod
    async def recalculate_user_metrics(db: AsyncSession, user_id, spreadsheet_id: str) -> None:
        """
        Compute weekly application statistics for a user from PostgreSQL
        and overwrite their 📈 Metrics tab.
        """
        from collections import defaultdict

        # Fetch all non-skipped applications for the user
        stmt = (
            select(Application)
            .where(
                Application.user_id == user_id,
                ~Application.status.like("SKIPPED_%")
            )
        )
        res = await db.execute(stmt)
        apps = res.scalars().all()

        if not apps:
            return

        # Group by week start
        metrics = defaultdict(lambda: {"sent": 0, "interviews": 0, "offers": 0, "rejections": 0})

        for app in apps:
            dt = app.submitted_at or app.created_at
            if not dt:
                continue
            week_str = SheetsService._get_week_start(dt)
            
            metrics[week_str]["sent"] += 1
            
            status_upper = app.status.upper() if app.status else ""
            if status_upper in ("INTERVIEW", "INTERVIEWING", "INTERVIEW_SCHEDULED", "OA_RECEIVED"):
                metrics[week_str]["interviews"] += 1
            elif status_upper in ("OFFER", "OFFER_ACCEPTED", "OFFER_DECLINED"):
                metrics[week_str]["offers"] += 1
            elif status_upper in ("REJECTED", "REJECTION", "CLOSED", "DECLINED_BY_USER"):
                metrics[week_str]["rejections"] += 1

        # Build rows
        rows = []
        for week_str in sorted(metrics.keys()):
            m = metrics[week_str]
            sent = m["sent"]
            interviews = m["interviews"]
            offers = m["offers"]
            rejections = m["rejections"]
            
            responses = interviews + offers + rejections
            resp_rate = (responses / sent * 100.0) if sent > 0 else 0.0
            int_rate = (interviews / sent * 100.0) if sent > 0 else 0.0
            
            rows.append([
                week_str,
                sent,
                interviews,
                offers,
                rejections,
                f"{resp_rate:.1f}%",
                f"{int_rate:.1f}%"
            ])

        # Overwrite in spreadsheet
        integration = await SheetsService.get_integration(db, user_id)
        if not integration:
            return
        
        try:
            access_token = await GoogleOAuthService.get_valid_access_token(db, integration)
        except Exception:
            return
        
        client = GoogleSheetsAPIClient(access_token=access_token)
        tab_name = "📈 Metrics"
        await client.clear_values(spreadsheet_id, tab_name)
        if rows:
            await client.update_values(spreadsheet_id, tab_name, f"'{tab_name}'!A2", rows)

    @staticmethod
    async def enqueue_historical_backfill(db: AsyncSession, user_id) -> int:
        """
        Query all existing Application records for the user and enqueue an
        APPLICATION_SYNC event for each to backfill their spreadsheet.
        """
        stmt = select(Application).where(Application.user_id == user_id).order_by(Application.created_at.asc())
        res = await db.execute(stmt)
        apps = res.scalars().all()
        
        count = 0
        for app in apps:
            # Check if sync event already enqueued
            stmt_evt = select(EventQueue).where(
                EventQueue.user_id == user_id,
                EventQueue.event_type == "APPLICATION_SYNC",
                EventQueue.payload["application_id"].as_string() == str(app.id)
            )
            res_evt = await db.execute(stmt_evt)
            if not res_evt.scalars().first():
                event = EventQueue(
                    user_id=user_id,
                    event_type="APPLICATION_SYNC",
                    payload={"application_id": str(app.id)},
                    status="PENDING"
                )
                db.add(event)
                count += 1
        
        await db.commit()
        logger.info(f"Enqueued {count} historical backfill sync events for user {user_id}")
        return count

    # ------------------------------------------------------------------
    # Legacy compat — keep old get_spreadsheet / initialize_spreadsheet
    # for backward compatibility with old router endpoints
    # ------------------------------------------------------------------

    @staticmethod
    async def get_spreadsheet(db: AsyncSession, user_id) -> Optional[UserSpreadsheet]:
        """
        Legacy compat: Return a fake UserSpreadsheet-like object if the user
        has a GoogleIntegration, so the old /sheets/status endpoint still works.
        """
        integration = await SheetsService.get_integration(db, user_id)
        if not integration or not integration.is_provisioned:
            return None
        # Return a minimal duck-typed object
        class _FakeSheet:
            def __init__(self, i):
                self.spreadsheet_id = i.spreadsheet_id
                self.spreadsheet_url = i.spreadsheet_url
                self.last_sync_time = i.last_sync_at
        return _FakeSheet(integration)

    @staticmethod
    async def initialize_spreadsheet(db: AsyncSession, user: User) -> object:
        """
        Legacy compat stub: If user already has a GoogleIntegration,
        return a fake sheet-like object. Otherwise raise an informative error.
        """
        integration = await SheetsService.get_integration(db, user.id)
        if integration and integration.is_provisioned:
            class _FakeSheet:
                def __init__(self, i):
                    self.spreadsheet_id = i.spreadsheet_id
                    self.spreadsheet_url = i.spreadsheet_url
                    self.last_sync_time = i.last_sync_at
            return _FakeSheet(integration)
        raise RuntimeError(
            "Google Sheets is not connected via OAuth. "
            "Please use GET /api/v1/integrations/google/connect to connect your Google account."
        )
