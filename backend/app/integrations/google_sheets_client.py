"""
Google Sheets API Client — Per-User OAuth2 Bearer Token Architecture

This module replaces the legacy service-account GoogleSheetsClient with a
per-request, per-user client that uses the user's own OAuth2 access token
to call the Google Sheets REST API directly via httpx.AsyncClient.

Key design principles:
  - No global state. Each instantiation takes an access_token at init time.
  - Pure async — all operations are awaitable.
  - Uses Google Sheets REST API v4 directly (no gspread dependency).
  - Raises GoogleSheetsAPIError on unrecoverable errors.
  - Callers (sheets_service.py, Celery tasks) are responsible for token refresh.
"""
import logging
import re
from typing import Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("autoapply_ai.integrations.google_sheets")

SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE_BASE = "https://www.googleapis.com/drive/v3"


class GoogleSheetsAPIError(Exception):
    """Raised when a Google Sheets API call fails in a non-retryable way."""


# ---------------------------------------------------------------------------
# Tab definitions — canonical structure for every user's spreadsheet
# ---------------------------------------------------------------------------

SPREADSHEET_TABS: List[Dict] = [
    {
        "name": "📊 Applications",
        "headers": [
            "Date Applied", "Company", "Role", "Location", "Source",
            "Resume Used", "Match Score", "Match Breakdown", "Status", "Timeline", "Errors", "Interview Stage",
            "Recruiter", "Apply URL", "Notes",
        ],
    },
    {
        "name": "🎯 Interviews",
        "headers": [
            "Date", "Company", "Role", "Interview Type", "Round",
            "Interviewer", "Outcome", "Next Steps", "Notes",
        ],
    },
    {
        "name": "🏆 Offers",
        "headers": [
            "Date", "Company", "Role", "Offer Amount", "Currency",
            "Start Date", "Deadline", "Decision", "Notes",
        ],
    },
    {
        "name": "❌ Rejected",
        "headers": [
            "Date", "Company", "Role", "Stage Rejected", "Reason", "Notes",
        ],
    },
    {
        "name": "🔍 All Jobs",
        "headers": [
            "Date Found", "Company", "Role", "Location", "Source",
            "Match Score", "Status", "Apply URL",
        ],
    },
    {
        "name": "📈 Metrics",
        "headers": [
            "Week", "Applications Sent", "Interviews", "Offers",
            "Rejections", "Response Rate %", "Interview Rate %",
        ],
    },
]


class GoogleSheetsAPIClient:
    """
    Async Google Sheets REST API client scoped to a single user's access token.

    Usage:
        client = GoogleSheetsAPIClient(access_token=token)
        spreadsheet_id, url = await client.create_spreadsheet("My Tracker")
        tab_gids = await client.provision_tabs(spreadsheet_id)
    """

    def __init__(self, access_token: str):
        self._token = access_token
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(headers=self._headers, timeout=60.0)

    # ------------------------------------------------------------------
    # Spreadsheet lifecycle
    # ------------------------------------------------------------------

    async def create_spreadsheet(self, title: str) -> Tuple[str, str]:
        """
        Create a new Google Spreadsheet owned by the authenticated user.

        Args:
            title: Human-readable spreadsheet title.

        Returns:
            (spreadsheet_id, spreadsheet_url) tuple.

        Raises:
            GoogleSheetsAPIError on failure.
        """
        body = {
            "properties": {"title": title},
            "sheets": [{"properties": {"title": "Sheet1"}}],
        }
        async with self._client() as client:
            resp = await client.post(SHEETS_BASE, json=body)

        if resp.status_code != 200:
            raise GoogleSheetsAPIError(
                f"Failed to create spreadsheet '{title}': {resp.status_code} {resp.text}"
            )

        data = resp.json()
        spreadsheet_id = data["spreadsheetId"]
        url = data.get("spreadsheetUrl") or f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        logger.info(f"Created Google Spreadsheet: {spreadsheet_id}")
        return spreadsheet_id, url

    async def provision_tabs(self, spreadsheet_id: str) -> Dict[str, int]:
        """
        Rename the default 'Sheet1' tab to the first tab, add the remaining tabs,
        write bold frozen headers on each, and return a map of tab_name → sheet_gid.

        Args:
            spreadsheet_id: ID of the spreadsheet to configure.

        Returns:
            Dict mapping tab name → integer sheet GID.
        """
        # Step 1: Get current sheet metadata to find the default sheet's GID
        meta = await self._get_spreadsheet_meta(spreadsheet_id)
        existing_sheets = meta.get("sheets", [])
        default_gid = existing_sheets[0]["properties"]["sheetId"] if existing_sheets else 0

        # Step 2: Build batchUpdate requests — rename default + add all others
        requests = []

        # Rename the default sheet to first tab
        first_tab = SPREADSHEET_TABS[0]
        requests.append({
            "updateSheetProperties": {
                "properties": {
                    "sheetId": default_gid,
                    "title": first_tab["name"],
                    "gridProperties": {"frozenRowCount": 1, "showGridLines": True},
                },
                "fields": "title,gridProperties.frozenRowCount,gridProperties.showGridLines",
            }
        })

        # Add remaining tabs
        for tab in SPREADSHEET_TABS[1:]:
            requests.append({
                "addSheet": {
                    "properties": {
                        "title": tab["name"],
                        "gridProperties": {"frozenRowCount": 1, "showGridLines": True},
                    }
                }
            })

        batch_resp = await self._batch_update(spreadsheet_id, requests)

        # Step 3: Build tab_name → gid mapping from batch response
        tab_gids: Dict[str, int] = {first_tab["name"]: default_gid}
        for reply in batch_resp.get("replies", []):
            props = reply.get("addSheet", {}).get("properties", {})
            if props.get("title") and props.get("sheetId") is not None:
                tab_gids[props["title"]] = props["sheetId"]

        # Step 4: Write bold headers on each tab using their GIDs and apply professional banding/conditional formatting
        header_requests = []
        for tab in SPREADSHEET_TABS:
            gid = tab_gids.get(tab["name"])
            if gid is None:
                logger.warning(f"Could not find GID for tab '{tab['name']}' — skipping headers")
                continue
            # Write header values
            header_requests.append(self._build_header_value_request(gid, tab["headers"]))
            # Apply bold + background color formatting to header row
            header_requests.append(self._build_header_format_request(gid, len(tab["headers"])))
            # Add banding for alternating rows
            header_requests.append(self._build_banding_request(gid, len(tab["headers"])))
            
            # Apply status column conditional highlights where applicable
            if tab["name"] == "📊 Applications":
                header_requests.extend(self._build_status_conditional_format_requests(gid, 8))
            elif tab["name"] == "🔍 All Jobs":
                header_requests.extend(self._build_status_conditional_format_requests(gid, 6))

        if header_requests:
            await self._batch_update(spreadsheet_id, header_requests)

        logger.info(f"Provisioned {len(tab_gids)} tabs on spreadsheet {spreadsheet_id}: {list(tab_gids.keys())}")
        return tab_gids

    # ------------------------------------------------------------------
    # Row operations
    # ------------------------------------------------------------------

    async def append_row(
        self,
        spreadsheet_id: str,
        tab_name: str,
        row_data: List,
    ) -> Optional[int]:
        """
        Append a row to the named tab and return the 1-indexed row number written.

        Args:
            spreadsheet_id: Target spreadsheet.
            tab_name:       Exact tab name (must match tab in spreadsheet).
            row_data:       List of cell values (strings, ints, floats).

        Returns:
            Row index (1-indexed) where data was written, or None on failure.
        """
        range_name = f"'{tab_name}'!A:A"
        body = {"values": [row_data]}

        async with self._client() as client:
            resp = await client.post(
                f"{SHEETS_BASE}/{spreadsheet_id}/values/{range_name}:append",
                params={
                    "valueInputOption": "USER_ENTERED",
                    "insertDataOption": "INSERT_ROWS",
                },
                json=body,
            )

        if resp.status_code != 200:
            logger.error(
                f"Failed to append row to '{tab_name}' in {spreadsheet_id}: "
                f"{resp.status_code} {resp.text}"
            )
            return None

        updated_range = resp.json().get("updates", {}).get("updatedRange", "")
        match = re.search(r"[A-Z]+(\d+)", updated_range.split("!")[-1])
        if match:
            return int(match.group(1))
        return None

    async def update_row(
        self,
        spreadsheet_id: str,
        tab_name: str,
        row_index: int,
        row_data: List,
    ) -> bool:
        """
        Overwrite a specific row (by 1-indexed row number) in a named tab.

        Args:
            spreadsheet_id: Target spreadsheet.
            tab_name:       Exact tab name.
            row_index:      1-indexed row number to overwrite.
            row_data:       New cell values.

        Returns:
            True on success, False on failure.
        """
        end_col = chr(ord("A") + len(row_data) - 1)
        range_name = f"'{tab_name}'!A{row_index}:{end_col}{row_index}"
        body = {"values": [row_data]}

        async with self._client() as client:
            resp = await client.put(
                f"{SHEETS_BASE}/{spreadsheet_id}/values/{range_name}",
                params={"valueInputOption": "USER_ENTERED"},
                json=body,
            )

        if resp.status_code != 200:
            logger.error(
                f"Failed to update row {row_index} in '{tab_name}' in {spreadsheet_id}: "
                f"{resp.status_code} {resp.text}"
            )
            return False

        return True

    # ------------------------------------------------------------------
    # Drive — share spreadsheet with user's Google account
    # ------------------------------------------------------------------

    async def share_spreadsheet(self, spreadsheet_id: str, google_email: str) -> None:
        """
        Grant writer access to the spreadsheet for the given Google email.
        This ensures the user can actually open the spreadsheet.

        Args:
            spreadsheet_id: The spreadsheet to share.
            google_email:   The email to grant writer permission to.
        """
        try:
            async with httpx.AsyncClient(headers=self._headers, timeout=30.0) as client:
                resp = await client.post(
                    f"{DRIVE_BASE}/files/{spreadsheet_id}/permissions",
                    json={
                        "role": "writer",
                        "type": "user",
                        "emailAddress": google_email,
                    },
                    params={"sendNotificationEmail": "false"},
                )
            if resp.status_code not in (200, 201):
                logger.warning(
                    f"Could not share spreadsheet {spreadsheet_id} with {google_email}: "
                    f"{resp.status_code} {resp.text}"
                )
            else:
                logger.info(f"Shared spreadsheet {spreadsheet_id} with {google_email}")
        except Exception as e:
            logger.warning(f"Share spreadsheet failed (non-fatal): {e}")

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    async def _get_spreadsheet_meta(self, spreadsheet_id: str) -> dict:
        """Fetch spreadsheet metadata (sheets list, properties)."""
        async with self._client() as client:
            resp = await client.get(
                f"{SHEETS_BASE}/{spreadsheet_id}",
                params={"fields": "sheets.properties"},
            )
        if resp.status_code != 200:
            raise GoogleSheetsAPIError(
                f"Failed to fetch spreadsheet metadata for {spreadsheet_id}: "
                f"{resp.status_code} {resp.text}"
            )
        return resp.json()

    async def _batch_update(self, spreadsheet_id: str, requests: List[dict]) -> dict:
        """Execute a batchUpdate on the spreadsheet."""
        async with self._client() as client:
            resp = await client.post(
                f"{SHEETS_BASE}/{spreadsheet_id}:batchUpdate",
                json={"requests": requests},
            )
        if resp.status_code != 200:
            raise GoogleSheetsAPIError(
                f"batchUpdate failed on {spreadsheet_id}: {resp.status_code} {resp.text}"
            )
        return resp.json()

    @staticmethod
    def _build_header_value_request(sheet_gid: int, headers: List[str]) -> dict:
        """Build a batchUpdate request to write header values in row 1."""
        return {
            "updateCells": {
                "rows": [{
                    "values": [
                        {
                            "userEnteredValue": {"stringValue": h},
                            "userEnteredFormat": {
                                "textFormat": {
                                    "bold": True,
                                    "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                                    "fontSize": 11,
                                    "fontFamily": "Segoe UI"
                                },
                                "backgroundColor": {"red": 0.12, "green": 0.16, "blue": 0.24},
                                "horizontalAlignment": "CENTER",
                            },
                        }
                        for h in headers
                    ]
                }],
                "fields": "userEnteredValue,userEnteredFormat",
                "start": {"sheetId": sheet_gid, "rowIndex": 0, "columnIndex": 0},
            }
        }

    @staticmethod
    def _build_header_format_request(sheet_gid: int, num_cols: int) -> dict:
        """Build a batchUpdate request to auto-resize columns for the header row."""
        return {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_gid,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": num_cols,
                }
            }
        }

    @staticmethod
    def _build_banding_request(sheet_gid: int, num_cols: int) -> dict:
        """Build an addBanding request to alternate row colors from row 2 down."""
        return {
            "addBanding": {
                "bandedRange": {
                    "range": {
                        "sheetId": sheet_gid,
                        "startRowIndex": 1,
                        "endRowIndex": 1000,
                        "startColumnIndex": 0,
                        "endColumnIndex": num_cols
                    },
                    "rowProperties": {
                        "firstBandColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                        "secondBandColor": {"red": 0.97, "green": 0.98, "blue": 0.99}
                    }
                }
            }
        }

    @staticmethod
    def _build_status_conditional_format_requests(sheet_gid: int, status_col_idx: int) -> List[dict]:
        """Build conditional formatting rules for status columns using modern premium palettes."""
        status_colors = {
            "SUBMITTED": ({"red": 0.85, "green": 0.93, "blue": 0.88}, {"red": 0.1, "green": 0.4, "blue": 0.2}),
            "OFFER": ({"red": 0.85, "green": 0.93, "blue": 0.88}, {"red": 0.1, "green": 0.4, "blue": 0.2}),
            "INTERVIEW": ({"red": 0.98, "green": 0.92, "blue": 0.8}, {"red": 0.6, "green": 0.3, "blue": 0.0}),
            "OA_RECEIVED": ({"red": 0.98, "green": 0.92, "blue": 0.8}, {"red": 0.6, "green": 0.3, "blue": 0.0}),
            "REJECTED": ({"red": 0.96, "green": 0.85, "blue": 0.85}, {"red": 0.6, "green": 0.1, "blue": 0.1}),
            "DECLINED_BY_USER": ({"red": 0.96, "green": 0.85, "blue": 0.85}, {"red": 0.6, "green": 0.1, "blue": 0.1}),
            "FAILED": ({"red": 0.96, "green": 0.85, "blue": 0.85}, {"red": 0.6, "green": 0.1, "blue": 0.1}),
            "PENDING_APPROVAL": ({"red": 0.88, "green": 0.92, "blue": 0.97}, {"red": 0.1, "green": 0.3, "blue": 0.6}),
            "SHORTLISTED": ({"red": 0.88, "green": 0.92, "blue": 0.97}, {"red": 0.1, "green": 0.3, "blue": 0.6}),
            "APPLYING": ({"red": 0.88, "green": 0.92, "blue": 0.97}, {"red": 0.1, "green": 0.3, "blue": 0.6}),
            "SKIPPED": ({"red": 0.93, "green": 0.93, "blue": 0.93}, {"red": 0.4, "green": 0.4, "blue": 0.4}),
        }

        rules = []
        for status_val, (bg, fg) in status_colors.items():
            rules.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{
                            "sheetId": sheet_gid,
                            "startRowIndex": 1,
                            "endRowIndex": 1000,
                            "startColumnIndex": status_col_idx,
                            "endColumnIndex": status_col_idx + 1
                        }],
                        "booleanRule": {
                            "condition": {
                                "type": "TEXT_CONTAINS",
                                "values": [{"userEnteredValue": status_val}]
                            },
                            "format": {
                                "backgroundColor": bg,
                                "textFormat": {"foregroundColor": fg, "bold": True}
                            }
                        }
                    },
                    "index": 0
                }
            })
        return rules

    async def clear_values(self, spreadsheet_id: str, tab_name: str) -> None:
        """Clear all values in a tab (excluding header)."""
        range_name = f"'{tab_name}'!A2:Z200"
        async with self._client() as client:
            resp = await client.post(
                f"{SHEETS_BASE}/{spreadsheet_id}/values/{range_name}:clear"
            )
        if resp.status_code != 200:
            logger.error(
                f"Failed to clear values in tab '{tab_name}': {resp.status_code} {resp.text}"
            )
            raise GoogleSheetsAPIError(f"Failed to clear values: {resp.text}")

    async def update_values(
        self, spreadsheet_id: str, tab_name: str, range_name: str, values: List[List]
    ) -> None:
        """Update values in a specific range."""
        body = {"values": values}
        async with self._client() as client:
            resp = await client.put(
                f"{SHEETS_BASE}/{spreadsheet_id}/values/{range_name}",
                params={"valueInputOption": "USER_ENTERED"},
                json=body,
            )
        if resp.status_code != 200:
            logger.error(
                f"Failed to update values in range '{range_name}': {resp.status_code} {resp.text}"
            )
            raise GoogleSheetsAPIError(f"Failed to update values: {resp.text}")


# ---------------------------------------------------------------------------
# Tab name classification helper — used by sheets_service.py
# ---------------------------------------------------------------------------

def classify_application_tab(role_title: str, status: str) -> str:
    """
    Determine which Applications-family tab a job application belongs in.

    Priority order:
      1. OFFER status → 🏆 Offers
      2. REJECTED status → ❌ Rejected
      3. Interview stage → 🎯 Interviews
      4. All others → 📊 Applications (primary log)

    Note: All events also go into 📊 Applications (the primary log).
    This function returns only the *secondary* tab if applicable.

    Args:
        role_title: Job title string.
        status:     Application status string.

    Returns:
        Tab name string from SPREADSHEET_TABS.
    """
    status_upper = status.upper() if status else ""
    if status_upper in ("OFFER", "OFFER_ACCEPTED", "OFFER_DECLINED"):
        return "🏆 Offers"
    if status_upper in ("REJECTED", "REJECTION", "CLOSED"):
        return "❌ Rejected"
    if status_upper in ("INTERVIEW", "INTERVIEWING", "INTERVIEW_SCHEDULED"):
        return "🎯 Interviews"
    return "📊 Applications"
