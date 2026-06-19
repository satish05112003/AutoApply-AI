import json
import logging
from typing import Tuple, Dict, Any, Optional
from app.config import settings

logger = logging.getLogger("autoapply_ai.sheets_client")

class GoogleSheetsClient:
    def __init__(self):
        self.creds = None
        self.gc = None
        self._initialized = False

    def initialize(self) -> bool:
        """Attempt to parse service account JSON and authenticate with Google APIs."""
        if self._initialized:
            return True
            
        json_str = settings.GOOGLE_SERVICE_ACCOUNT_JSON
        if not json_str or json_str == "{}":
            logger.warning("Google service account credentials not configured. Running in MOCK sheets mode.")
            return False

        try:
            import gspread
            from google.oauth2.service_account import Credentials
            
            scopes = [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive"
            ]
            creds_info = json.loads(json_str)
            self.creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
            self.gc = gspread.authorize(self.creds)
            self._initialized = True
            logger.info("Google Sheets Client successfully authenticated.")
            return True
        except Exception as e:
            logger.error(f"Failed to authenticate with Google Sheets API: {e}", exc_info=True)
            return False

    def create_spreadsheet(self, title: str, user_email: str) -> Tuple[str, str]:
        """Create a new Google Spreadsheet with 9 default tabs and share access."""
        tabs = ["AI_ML", "GENAI", "DATA_SCIENCE", "BACKEND", "EMBEDDED", "WEB3", "INTERNSHIPS", "OFFERS", "REJECTIONS"]
        headers = [
            "Applied Date", "Company", "Role", "Location", "Source",
            "Resume Used", "Match Score", "Application Status", "Interview Status",
            "Recruiter Contact", "Apply URL"
        ]

        if not self.initialize():
            logger.info("MOCK: Creating spreadsheet for user: " + user_email)
            mock_id = f"mock-sheet-id-{hash(user_email)}"
            mock_url = f"https://docs.google.com/spreadsheets/d/{mock_id}/edit"
            return mock_id, mock_url

        try:
            # Create sheet
            sh = self.gc.create(title)
            sh.share(user_email, perm_type="user", role="writer")
            
            # Setup columns headers on all required tabs
            first = True
            for tab_name in tabs:
                if first:
                    worksheet = sh.get_worksheet(0)
                    worksheet.update_title(tab_name)
                    first = False
                else:
                    worksheet = sh.add_worksheet(title=tab_name, rows="100", cols="20")
                worksheet.append_row(headers)
            
            logger.info(f"Created multi-tab Google Spreadsheet: {sh.url}")
            return sh.id, sh.url
        except Exception as e:
            logger.error(f"Failed to create Google Spreadsheet: {e}", exc_info=True)
            mock_id = f"mock-sheet-id-fallback-{hash(user_email)}"
            return mock_id, f"https://docs.google.com/spreadsheets/d/{mock_id}/edit"

    def append_row(self, spreadsheet_id: str, row_data: list, sheet_name: str = "BACKEND") -> Optional[int]:
        """Append a single row of values to the specified sheet and return the row index."""
        if not self.initialize() or spreadsheet_id.startswith("mock-"):
            logger.info(f"MOCK: Appending row to sheet '{sheet_name}': {row_data}")
            return 2 # default mock row index

        try:
            sh = self.gc.open_by_key(spreadsheet_id)
            try:
                worksheet = sh.worksheet(sheet_name)
            except Exception:
                headers = [
                    "Applied Date", "Company", "Role", "Location", "Source",
                    "Resume Used", "Match Score", "Application Status", "Interview Status",
                    "Recruiter Contact", "Apply URL"
                ]
                worksheet = sh.add_worksheet(title=sheet_name, rows="100", cols="20")
                worksheet.append_row(headers)
                
            import re
            result = worksheet.append_row(row_data)
            updated_range = result.get("updates", {}).get("updatedRange", "")
            match = re.search(r"[A-Z]+(\d+)", updated_range.split("!")[-1])
            if match:
                return int(match.group(1))
            
            # Fallback: get row count
            return len(worksheet.get_all_values())
        except Exception as e:
            logger.error(f"Failed to append row to Google Spreadsheet '{spreadsheet_id}' in tab '{sheet_name}': {e}", exc_info=True)
            return None

    def update_row(self, spreadsheet_id: str, row_index: int, row_data: list, sheet_name: str) -> bool:
        """Update a specific row at index `row_index` in Google Sheets."""
        if not self.initialize() or spreadsheet_id.startswith("mock-"):
            logger.info(f"MOCK: Updating row {row_index} in sheet '{sheet_name}': {row_data}")
            return True

        try:
            sh = self.gc.open_by_key(spreadsheet_id)
            worksheet = sh.worksheet(sheet_name)
            # Update range, e.g. A12:K12 for a row with 11 cells
            end_col = chr(ord('A') + len(row_data) - 1)
            cell_range = f"A{row_index}:{end_col}{row_index}"
            worksheet.update(cell_range, [row_data])
            logger.info(f"Updated row {row_index} in Google Spreadsheet '{spreadsheet_id}' under tab '{sheet_name}'.")
            return True
        except Exception as e:
            logger.error(f"Failed to update row {row_index} in Google Spreadsheet '{spreadsheet_id}' under tab '{sheet_name}': {e}", exc_info=True)
            return False

# Global Client Instance
google_sheets_client = GoogleSheetsClient()
