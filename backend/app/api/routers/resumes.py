import logging
from typing import List
from uuid import UUID
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from app.api.deps import get_current_user
from app.database import get_db
from app.models.auth import User
from app.models.profile import Resume
from app.api.schemas.profile import ResumeResponse, ResumeUploadResponse
from app.agents.resume_agent import ResumeAgent
from app.services.storage_service import StorageService
from app.services.backup_service import auto_backup

router = APIRouter()
logger = logging.getLogger("autoapply_ai.resumes")

@router.get("", response_model=List[ResumeResponse])
async def list_resumes(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Resume).where(Resume.user_id == user.id).order_by(Resume.upload_at.desc())
    result = await db.execute(stmt)
    resumes = result.scalars().all()
    return resumes

@router.post("/upload", response_model=ResumeUploadResponse)
async def upload_resume(
    file: UploadFile = File(...),
    resume_name: str = Form(...),
    is_primary: bool = Form(False),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Validate PDF content-type by extension
    if not file.filename.endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF resume files are supported."
        )

    try:
        pdf_bytes = await file.read()
        
        # Validate PDF content size and integrity
        if not pdf_bytes or len(pdf_bytes) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PDF file is empty."
            )
        if len(pdf_bytes) > 10 * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File is too large. Max allowed size is 10MB."
            )
        
        # Verify it can be opened as a valid PDF
        try:
            import fitz
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            if doc.page_count == 0:
                raise ValueError("PDF has zero pages.")
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PDF file is corrupted or invalid."
            )

        # Step 1: Extract text from PDF using local PDF parser
        from app.utils.resume_parser import extract_text_from_pdf
        raw_text = extract_text_from_pdf(pdf_bytes)

        # Step 2: Create a placeholder Resume record in DB to get its UUID
        new_resume = Resume(
            user_id=user.id,
            resume_name=resume_name,
            resume_type="PENDING",
            file_key=f"resumes/{user.id}/temp_{file.filename}",
            is_primary=is_primary,
            file_size_bytes=len(pdf_bytes),
            original_filename=file.filename,
            parsed_text=raw_text
        )
        db.add(new_resume)
        await db.commit()
        await db.refresh(new_resume)

        # Cache primitives immediately to avoid lazy-loading / MissingGreenlet exceptions post-commit
        resume_id = new_resume.id
        user_id = user.id
        resume_id_str = str(resume_id)
        user_id_str = str(user_id)

        # Handle is_primary rules: if true, reset other resumes
        if is_primary:
            await db.execute(
                update(Resume)
                .where(Resume.user_id == user_id, Resume.id != resume_id)
                .values(is_primary=False)
            )
            await db.commit()

        # Step 3: Store PDF file in storage/database
        file_key = f"resumes/{user_id}/{resume_id}.pdf"
        file_url = await StorageService.upload_file(file_key, pdf_bytes)
        
        # Update the file key and URL inside the database
        new_resume.file_key = file_key
        new_resume.file_url = file_url
        db.add(new_resume)
        await db.commit()

        # Step 4: Run AI analysis and return success (200 OK) with potential warnings
        agent = ResumeAgent(user_id=user_id_str, db=db)
        input_data = {
            "pdf_bytes": pdf_bytes,
            "filename": file.filename,
            "resume_id": resume_id_str,
            "resume_name": resume_name,
            "is_primary": is_primary
        }
        
        analysis_status = "success"
        warning = None
        
        try:
            agent_result = await agent.run(input_data)
            if not agent_result.success:
                analysis_status = "failed"
                warning = f"AI analysis failed: {agent_result.error_message}"
            else:
                analysis_status = agent_result.output_data.get("analysis_status", "success")
                warning = agent_result.output_data.get("warning")
        except Exception as agent_err:
            analysis_status = "failed"
            warning = "AI analysis temporarily unavailable. Resume stored successfully."
            logger.error(f"Failed running resume agent: {agent_err}", exc_info=True)

        # Auto-backup after successful upload
        background_tasks.add_task(auto_backup, db, user_id)
            
        # Refetch and return resume details
        refetched_stmt = select(Resume).where(Resume.id == resume_id)
        refetched_result = await db.execute(refetched_stmt)
        resume_record = refetched_result.scalars().first()
        
        return {
            "success": True,
            "resume_uploaded": True,
            "analysis_status": analysis_status,
            "warning": warning,
            "resume": resume_record
        }

    except HTTPException as http_exc:
        # Re-raise validation HTTPExceptions directly
        raise http_exc
    except Exception as e:
        logger.error(f"Failed uploading resume: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to parse and upload resume. Please try again."
        )

@router.get("/download-file", response_class=StreamingResponse)
async def download_resume_file(key: str, user: User = Depends(get_current_user)):
    """API endpoint to download the raw PDF bytes from storage."""
    # Safety check: ensure the file requested belongs to the current user
    if f"resumes/{user.id}/" not in key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized access to target resource."
        )
        
    try:
        file_bytes = await StorageService.download_file(key)
        import io
        return StreamingResponse(io.BytesIO(file_bytes), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={key.split('/')[-1]}"})
    except Exception as e:
        logger.error(f"Failed downloading file: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File key not found in storage."
        )

@router.get("/{id}", response_model=ResumeResponse)
async def get_resume(id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Resume).where(Resume.id == id, Resume.user_id == user.id)
    result = await db.execute(stmt)
    resume = result.scalars().first()
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found."
        )
    return resume

@router.delete("/{id}")
async def delete_resume(id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Resume).where(Resume.id == id, Resume.user_id == user.id)
    result = await db.execute(stmt)
    resume = result.scalars().first()
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found."
        )
        
    # Delete from Qdrant vector db
    try:
        from app.integrations.vector_db_client import qdrant_client
        qdrant_client.delete_point("resumes", str(id))
    except Exception as e:
        logger.warning(f"Failed deleting point from Qdrant: {e}")

    # Delete raw file from storage
    try:
        await StorageService.delete_file(resume.file_key)
    except Exception as e:
        logger.warning(f"Failed deleting file from storage key: {e}")

    # Delete from database
    await db.delete(resume)
    await db.commit()
    return {"message": "Resume successfully deleted."}

@router.put("/{id}/set-primary")
async def set_primary_resume(id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Resume).where(Resume.id == id, Resume.user_id == user.id)
    result = await db.execute(stmt)
    resume = result.scalars().first()
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found."
        )
        
    # Set all other user resumes to is_primary = False
    await db.execute(
        update(Resume)
        .where(Resume.user_id == user.id)
        .values(is_primary=False)
    )
    
    # Set target to True
    resume.is_primary = True
    db.add(resume)
    await db.commit()
    return {"message": "Primary resume selected successfully."}
