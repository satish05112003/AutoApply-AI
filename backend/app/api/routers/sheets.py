import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user
from app.database import get_db
from app.models.auth import User
from app.services.sheets_service import SheetsService

router = APIRouter()
logger = logging.getLogger("autoapply_ai.routers.sheets")

@router.get("/status")
async def get_sheets_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Fetch status and URL of the candidate's linked Google sheets tracker."""
    sheet = await SheetsService.get_spreadsheet(db, user.id)
    if not sheet:
        return {"linked": False, "spreadsheet_url": None, "spreadsheet_id": None}
    return {
        "linked": True,
        "spreadsheet_url": sheet.spreadsheet_url,
        "spreadsheet_id": sheet.spreadsheet_id,
        "last_sync_time": sheet.last_sync_time
    }

@router.post("/initialize")
async def initialize_sheets_tracker(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Manually trigger creation/linking of Google sheets tracker."""
    try:
        sheet = await SheetsService.initialize_spreadsheet(db, user)
        return {
            "message": "Google sheets tracker linked successfully.",
            "spreadsheet_url": sheet.spreadsheet_url
        }
    except Exception as e:
        logger.error(f"Failed linking sheets: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Google sheets integration failed: {e}"
        )
