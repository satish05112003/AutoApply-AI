import logging
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.auth import User
from app.models.sheets import UserSpreadsheet, EventQueue, WrittenRecord
from app.integrations.google_sheets_client import google_sheets_client

logger = logging.getLogger("autoapply_ai.services.sheets")

class SheetsService:
    @staticmethod
    async def initialize_spreadsheet(db: AsyncSession, user: User) -> UserSpreadsheet:
        """Create and link a candidate's Google sheet tracker."""
        stmt = select(UserSpreadsheet).where(UserSpreadsheet.user_id == user.id)
        result = await db.execute(stmt)
        existing = result.scalars().first()
        if existing:
            return existing

        # Create spreadsheet title
        title = f"AutoApply AI Job Tracker ({user.full_name})"
        
        # Call Google sheets client
        sheet_id, sheet_url = google_sheets_client.create_spreadsheet(title, user.email)

        new_sheet = UserSpreadsheet(
            user_id=user.id,
            spreadsheet_id=sheet_id,
            spreadsheet_url=sheet_url,
            is_initialized=True,
            last_sync_time=datetime.now(timezone.utc)
        )
        db.add(new_sheet)
        await db.commit()
        await db.refresh(new_sheet)
        
        logger.info(f"Initialized spreadsheet tracker for user '{user.id}' at {sheet_url}")
        return new_sheet

    @staticmethod
    async def get_spreadsheet(db: AsyncSession, user_id) -> Optional[UserSpreadsheet]:
        stmt = select(UserSpreadsheet).where(UserSpreadsheet.user_id == user_id)
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def process_pending_events(db: AsyncSession) -> int:
        """Query sheets.event_queue for pending sync operations and write them to target user sheets."""
        # Import settings inside method to avoid circular import issues
        from app.config import settings
        
        stmt = select(EventQueue).where(EventQueue.status == "PENDING").order_by(EventQueue.created_at.asc()).limit(settings.SHEETS_BATCH_SIZE)
        result = await db.execute(stmt)
        events = result.scalars().all()
        
        processed_count = 0
        for event in events:
            try:
                # Load user's spreadsheet details
                stmt_s = select(UserSpreadsheet).where(UserSpreadsheet.user_id == event.user_id)
                res_s = await db.execute(stmt_s)
                sheet = res_s.scalars().first()
                
                if not sheet:
                    # Initialize default sheet if missing
                    stmt_u = select(User).where(User.id == event.user_id)
                    res_u = await db.execute(stmt_u)
                    user = res_u.scalars().first()
                    if user:
                        sheet = await SheetsService.initialize_spreadsheet(db, user)
                        
                if sheet:
                    # Process event types
                    payload = event.payload
                    status = payload.get("status", "SUBMITTED")
                    work_type = payload.get("work_type", "FULL_TIME")
                    role_title = (payload.get("role_title") or "").lower()
                    
                    # 1. Base classification
                    tab_name = "BACKEND"
                    if "intern" in role_title or work_type == "INTERNSHIP" or "internship" in work_type.lower():
                        tab_name = "INTERNSHIPS"
                    elif any(k in role_title for k in ["web3", "blockchain", "solidity", "crypto", "ethereum"]):
                        tab_name = "WEB3"
                    elif any(k in role_title for k in ["embedded", "firmware", "vlsi", "hardware", "microcontroller"]):
                        tab_name = "EMBEDDED"
                    elif any(k in role_title for k in ["data sci", "data analyst"]):
                        tab_name = "DATA_SCIENCE"
                    elif any(k in role_title for k in ["genai", "generative ai", "llm", "gpt", "prompt"]):
                        tab_name = "GENAI"
                    elif any(k in role_title for k in ["ai", "ml", "machine learning", "deep learning", "nlp", "computer vision"]):
                        tab_name = "AI_ML"
                    
                    # 2. Check if a record already exists for this application in the base tab
                    app_id = payload.get("application_id")
                    stmt_wr = select(WrittenRecord).where(
                        WrittenRecord.user_id == event.user_id,
                        WrittenRecord.sheet_name == tab_name,
                        WrittenRecord.record_id == app_id
                    )
                    res_wr = await db.execute(stmt_wr)
                    record = res_wr.scalars().first()
                    
                    row_data = [
                        payload.get("submitted_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        payload.get("company_name", "Unknown"),
                        payload.get("role_title", "Developer"),
                        payload.get("location") or "Remote",
                        payload.get("source") or "linkedin",
                        payload.get("resume_name") or "Resume",
                        f"{payload.get('match_score') or 0}%",
                        status,
                        payload.get("interview_status") or "None",
                        payload.get("recruiter_contact") or "None",
                        payload.get("source_url") or ""
                    ]
                    
                    success = False
                    if record and record.row_index:
                        # Existing record: update the row directly in Google Sheets!
                        success = google_sheets_client.update_row(
                            spreadsheet_id=sheet.spreadsheet_id,
                            row_index=record.row_index,
                            row_data=row_data,
                            sheet_name=tab_name
                        )
                        if success:
                            record.data = payload
                            db.add(record)
                    else:
                        # New record: append row
                        row_index = google_sheets_client.append_row(
                            spreadsheet_id=sheet.spreadsheet_id,
                            row_data=row_data,
                            sheet_name=tab_name
                        )
                        if row_index:
                            success = True
                            record = WrittenRecord(
                                user_id=event.user_id,
                                sheet_name=tab_name,
                                record_id=app_id,
                                record_type="APPLICATION",
                                row_index=row_index,
                                data=payload
                            )
                            db.add(record)
                    
                    # 3. If new status is REJECTED or OFFER, also add copy to the designated tab
                    if success and status in ["REJECTED", "OFFER"]:
                        sec_tab = "REJECTIONS" if status == "REJECTED" else "OFFERS"
                        
                        stmt_wr2 = select(WrittenRecord).where(
                            WrittenRecord.user_id == event.user_id,
                            WrittenRecord.sheet_name == sec_tab,
                            WrittenRecord.record_id == app_id
                        )
                        res_wr2 = await db.execute(stmt_wr2)
                        record2 = res_wr2.scalars().first()
                        
                        if record2 and record2.row_index:
                            google_sheets_client.update_row(
                                spreadsheet_id=sheet.spreadsheet_id,
                                row_index=record2.row_index,
                                row_data=row_data,
                                sheet_name=sec_tab
                            )
                        else:
                            row_index2 = google_sheets_client.append_row(
                                spreadsheet_id=sheet.spreadsheet_id,
                                row_data=row_data,
                                sheet_name=sec_tab
                            )
                            if row_index2:
                                record2 = WrittenRecord(
                                    user_id=event.user_id,
                                    sheet_name=sec_tab,
                                    record_id=app_id,
                                    record_type="APPLICATION",
                                    row_index=row_index2,
                                    data=payload
                                )
                                db.add(record2)
                    
                    if success:
                        event.status = "SUCCESS"
                        event.processed_at = datetime.now(timezone.utc)
                        processed_count += 1
                    else:
                        raise RuntimeError("Failed executing Google sheet sync operation.")
            except Exception as e:
                logger.error(f"Failed to process sheet sync event '{event.id}': {e}")
                event.retry_count += 1
                if event.retry_count >= event.max_retries:
                    event.status = "FAILED"
                event.last_error = str(e)
            
            db.add(event)
            await db.commit()
            
        return processed_count
