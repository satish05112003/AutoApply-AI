import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, Any
from app.config import settings

logger = logging.getLogger("autoapply_ai.notifications")

class NotificationService:
    @staticmethod
    async def send_email(to_email: str, subject: str, body_text: str) -> bool:
        """Send an email using SMTP credentials configuration."""
        if not settings.SMTP_HOST or not settings.SMTP_USER:
            logger.warning("SMTP server settings not configured. Skipping email dispatch.")
            return False

        try:
            msg = MIMEMultipart()
            msg["From"] = settings.FROM_EMAIL
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body_text, "plain"))
            
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.FROM_EMAIL, to_email, msg.as_string())
            server.quit()
            logger.info(f"Email sent successfully to: {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to '{to_email}': {e}", exc_info=True)
            return False

    @staticmethod
    async def send_telegram(chat_id: str, message: str) -> bool:
        """Send an alert message directly to a candidate's Telegram chat via Bot API."""
        if not settings.TELEGRAM_BOT_TOKEN:
            logger.warning("Telegram Bot token not configured. Skipping message dispatch.")
            return False

        try:
            import httpx
            url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    logger.info(f"Telegram notification sent to chat: {chat_id}")
                    return True
                else:
                    logger.warning(f"Telegram API returned non-200 code: {res.status_code} - {res.text}")
                    return False
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}", exc_info=True)
            return False
