import imaplib
import email
from email.header import decode_header
import re
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Tuple
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.profile import Preferences, Resume
from app.models.applications import Application, ApplicationEvent
from app.models.jobs import JobPosting
from app.models.sheets import EventQueue
from app.services.notification_service import NotificationService

logger = logging.getLogger("autoapply_ai.services.email_monitoring")

def normalize_company_name(name: str) -> str:
    """Helper to clean and normalize company names for fuzzy string matching."""
    name = name.lower()
    # Remove punctuation
    name = re.sub(r'[^\w\s]', '', name)
    # Remove common corporate suffixes
    suffixes = [
        "pvt", "ltd", "inc", "co", "llc", "corp", "corporation", 
        "solutions", "technologies", "private", "limited"
    ]
    words = name.split()
    cleaned_words = [w for w in words if w not in suffixes]
    return " ".join(cleaned_words).strip()

def extract_recruiter_name(from_str: str) -> str:
    """Extract name from From header: e.g. 'John Doe <john@company.com>' -> 'John Doe'"""
    match = re.match(r'^["\']?([^"\'<]+?)["\']?\s*<.+>$', from_str)
    if match:
        name = match.group(1).strip()
        if name:
            return name
    parts = from_str.split('<')
    if len(parts) > 1:
        name = parts[0].replace('"', '').replace("'", "").strip()
        if name:
            return name
    if '@' in from_str:
        email_part = from_str.split('<')[-1].replace('>', '').strip()
        name_part = email_part.split('@')[0]
        name = " ".join(p.capitalize() for p in re.split(r'[\._-]', name_part))
        return name
    return from_str

def get_email_body(msg: email.message.Message) -> str:
    """Extract and decode plain text body from a MIME email message."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            if content_type == "text/plain" and "attachment" not in content_disposition:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(errors="ignore")
                except Exception:
                    pass
            elif content_type == "text/html" and "attachment" not in content_disposition:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        html = payload.decode(errors="ignore")
                        # Stripping HTML tags for simple text matching
                        return re.sub(r'<[^<]+?>', '', html)
                except Exception:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode(errors="ignore")
        except Exception:
            pass
    return ""

class EmailMonitoringService:
    @staticmethod
    async def monitor_user_emails(db: AsyncSession, user: User) -> Dict[str, Any]:
        """Connects to Gmail IMAP, fetches recent emails, and updates matching job applications."""
        result_summary = {
            "emails_fetched": 0,
            "updates_detected": 0,
            "details": []
        }

        # 1. Fetch preferences for email monitoring
        stmt_pref = select(Preferences).where(Preferences.user_id == user.id)
        res_pref = await db.execute(stmt_pref)
        prefs = res_pref.scalars().first()

        if not prefs or not prefs.email_monitoring_enabled or not prefs.gmail_app_password:
            logger.info(f"Email monitoring disabled or credentials missing for user: {user.email}")
            return result_summary

        # 2. Query all user applications that are not in terminal states (REJECTED/OFFER)
        # We also need company name, so we load JobPosting relationship
        stmt_apps = select(Application).where(
            Application.user_id == user.id,
            Application.status.notin_(["REJECTED", "OFFER"])
        ).options(selectinload(Application.events))
        res_apps = await db.execute(stmt_apps)
        active_apps = res_apps.scalars().all()

        if not active_apps:
            logger.info(f"No active applications requiring monitoring for user: {user.email}")
            return result_summary

        # Load job details and resume for each application to build map and for sheets publishing
        app_mappings = []
        for app in active_apps:
            # Query job posting
            stmt_job = select(JobPosting).where(JobPosting.id == app.job_id)
            res_job = await db.execute(stmt_job)
            job = res_job.scalars().first()

            # Query resume
            stmt_resume = select(Resume).where(Resume.id == app.resume_id)
            res_resume = await db.execute(stmt_resume)
            resume = res_resume.scalars().first()

            if job:
                app_mappings.append({
                    "application": app,
                    "job": job,
                    "resume": resume,
                    "normalized_company": normalize_company_name(job.company_name)
                })

        # 3. Connect to IMAP
        try:
            logger.info(f"Connecting to Gmail IMAP for user {user.email}...")
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(user.email, prefs.gmail_app_password)
            mail.select("inbox")

            # Search since last 2 days to catch recent updates
            date_since = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%d-%b-%Y")
            status, data = mail.search(None, f'(SINCE "{date_since}")')
            
            if status != "OK" or not data[0]:
                logger.info("No recent messages found on IMAP search.")
                mail.close()
                mail.logout()
                return result_summary

            mail_ids = data[0].split()
            result_summary["emails_fetched"] = len(mail_ids)
            logger.info(f"Fetched {len(mail_ids)} recent emails for scan.")

            # Iterate messages starting from newest
            for mail_id in reversed(mail_ids):
                status, msg_data = mail.fetch(mail_id, "(RFC822)")
                if status != "OK":
                    continue
                
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                # Parse headers
                subject_header = decode_header(msg.get("Subject", ""))[0]
                subject = subject_header[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(errors="ignore")
                
                from_header = msg.get("From", "")
                from_decoded = decode_header(from_header)[0]
                from_str = from_decoded[0]
                if isinstance(from_str, bytes):
                    from_str = from_str.decode(errors="ignore")
                
                body = get_email_body(msg)
                
                # Check for calendar invite (.ics attachments or text/calendar content type)
                has_calendar_invite = False
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        filename = part.get_filename()
                        if content_type == "text/calendar" or (filename and filename.endswith(".ics")):
                            has_calendar_invite = True
                            break
                else:
                    if msg.get_content_type() == "text/calendar":
                        has_calendar_invite = True

                # Combine subject and body for matching
                search_blob = (subject + " " + body).lower()
                from_lower = from_str.lower()

                # Try to map to one of our active applications
                for mapping in app_mappings:
                    app = mapping["application"]
                    job = mapping["job"]
                    resume = mapping["resume"]
                    norm_comp = mapping["normalized_company"]

                    # Check if company name is mentioned in Subject/Body or from the sender domain
                    is_match = False
                    if norm_comp and len(norm_comp) >= 2:
                        if norm_comp in search_blob or norm_comp in from_lower:
                            is_match = True

                    if is_match:
                        # Determine new status based on content keywords
                        new_status = None
                        recruiter_contact = extract_recruiter_name(from_str)
                        
                        # Rejection Check
                        rejection_keywords = [
                            "not moving forward", "unfortunately", "thank you for your time",
                            "decided to pursue other", "regret to inform", "another candidate",
                            "unable to offer", "not select", "not be moving", "pursue other options",
                            "position has been filled", "not selected", "rejection", "closed application"
                        ]
                        # Interview Check
                        interview_keywords = [
                            "interview", "schedule", "availability to chat", "phone screen",
                            "discuss your application", "zoom link", "google meet", "calendar",
                            "meet with", "technical screening", "call with", "scheduling link",
                            "calendly.com", "book a slot", "schedule details"
                        ]
                        # Online Assessment Check
                        oa_keywords = [
                            "assessment", "hackerrank", "codility", "online test",
                            "coding challenge", "quiz", "test link", "take-home", "technical test",
                            "assignment"
                        ]
                        # Offer Check
                        offer_keywords = [
                            "offer letter", "pleased to offer", "join us", "congratulations",
                            "employment agreement", "offer details", "compensation package"
                        ]

                        if has_calendar_invite:
                            new_status = "INTERVIEW"
                        elif any(kw in search_blob for kw in offer_keywords):
                            new_status = "OFFER"
                        elif any(kw in search_blob for kw in rejection_keywords):
                            new_status = "REJECTED"
                        elif any(kw in search_blob for kw in interview_keywords):
                            new_status = "INTERVIEW"
                        elif any(kw in search_blob for kw in oa_keywords):
                            new_status = "OA_RECEIVED"

                        # If status changed and it's a progress update, execute it!
                        if new_status and new_status != app.status:
                            # Verify we don't downgrade status (e.g. from interview to OA)
                            status_order = {
                                "DISCOVERED": 0, "MATCHED": 1, "READY": 2, "SUBMITTED": 3,
                                "OA_RECEIVED": 4, "INTERVIEW": 5, "REJECTED": 6, "OFFER": 7
                            }
                            current_order = status_order.get(app.status, 0)
                            new_order = status_order.get(new_status, 0)
                            
                            # Rejection or Offer is always terminal.
                            # Standard updates must be forward-only unless it's a terminal status.
                            if new_order > current_order or new_status in ["REJECTED", "OFFER"]:
                                old_status = app.status
                                app.status = new_status
                                app.updated_at = datetime.now(timezone.utc)
                                
                                # Add ApplicationEvent
                                event = ApplicationEvent(
                                    application_id=app.id,
                                    user_id=user.id,
                                    event_type="EMAIL_MATCH",
                                    old_status=old_status,
                                    new_status=new_status,
                                    agent_name="EmailMonitoringAgent",
                                    details={
                                        "subject": subject,
                                        "sender": from_str,
                                        "matched_keyword": "calendar_invite" if has_calendar_invite else next((kw for kw in rejection_keywords + offer_keywords + interview_keywords + oa_keywords if kw in search_blob), "unknown")
                                    }
                                )
                                db.add(event)
                                
                                # Queue Google Sheets sync event
                                sheet_event = EventQueue(
                                    user_id=user.id,
                                    event_type="APPLICATION_SYNC",
                                    payload={"application_id": str(app.id)},
                                    status="PENDING"
                                )
                                db.add(sheet_event)
                                
                                await db.commit()
                                await db.refresh(app)
                                
                                result_summary["updates_detected"] += 1
                                update_info = {
                                    "company": job.company_name,
                                    "role": job.role_title,
                                    "old_status": old_status,
                                    "new_status": new_status,
                                    "subject": subject
                                }
                                result_summary["details"].append(update_info)
                                logger.info(f"Updated application for {job.company_name} to {new_status} based on email from {from_str}.")
                                
                                # Trigger user notifications
                                notif_msg = f"<b>AutoApply AI Alert</b>\n\nWe detected a recruiter response from <b>{job.company_name}</b> for the <b>{job.role_title}</b> position.\n\n<b>New Status:</b> {new_status}\n<b>Subject:</b> {subject}\n\nYour dashboard and Google Sheet have been updated automatically."
                                
                                # 1. Send Email Notification
                                if user.email_notifications:
                                    await NotificationService.send_email(
                                        to_email=user.email,
                                        subject=f"Application Update: {job.company_name} - {new_status}",
                                        body_text=f"We detected a recruiter response from {job.company_name} for the {job.role_title} position.\n\nNew Status: {new_status}\nSubject: {subject}\n\nYour dashboard and Google Sheet have been updated automatically."
                                    )
                                
                                # 2. Send Telegram Notification if enabled
                                if user.telegram_enabled and user.telegram_chat_id:
                                    await NotificationService.send_telegram(
                                        chat_id=user.telegram_chat_id,
                                        message=notif_msg
                                    )
                                
                                # Stop processing other active apps for this email to avoid duplicates
                                break

            mail.close()
            mail.logout()
            logger.info("IMAP scan completed and connection closed.")

        except Exception as e:
            logger.error(f"Gmail IMAP monitoring task failed: {e}", exc_info=True)
            result_summary["error"] = str(e)
            
        return result_summary
