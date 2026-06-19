import logging
import traceback
from typing import List
from uuid import UUID
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user
from app.api.schemas.profile import (
    CandidateProfileResponse,
    CandidateProfileUpdate,
    EducationCreate,
    EducationUpdate,
    EducationResponse,
    ExperienceCreate,
    ExperienceUpdate,
    ExperienceResponse,
    SkillCreate,
    SkillUpdate,
    SkillResponse,
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    AchievementCreate,
    AchievementUpdate,
    AchievementResponse,
    PreferencesResponse,
    PreferencesUpdate,
    ProfileCompletenessResponse,
)
from app.database import get_db
from app.models.auth import User
from app.services.profile_service import ProfileService
from app.services.backup_service import auto_backup

logger = logging.getLogger("autoapply_ai.routers.profile")
router = APIRouter()


# --- General Profile ---
@router.get("", response_model=CandidateProfileResponse)
async def get_profile(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    profile = await ProfileService.get_profile(db, user.id)
    if not profile:
        profile = await ProfileService.update_profile(db, user.id, CandidateProfileUpdate())
    return profile

@router.put("", response_model=CandidateProfileResponse)
async def update_profile(data: CandidateProfileUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        return await ProfileService.update_profile(db, user.id, data)
    except Exception as e:
        logger.exception("update_profile failed for user_id=%s", user.id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# --- Education ---
@router.get("/education", response_model=List[EducationResponse])
async def get_education(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await ProfileService.get_education(db, user.id)

@router.post("/education", response_model=EducationResponse, status_code=status.HTTP_201_CREATED)
async def add_education(data: EducationCreate, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await ProfileService.add_education(db, user.id, data)
    background_tasks.add_task(auto_backup, db, user.id)
    return result

@router.put("/education/{id}", response_model=EducationResponse)
async def update_education(id: UUID, data: EducationUpdate, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    logger.info("PUT /education/%s user=%s payload=%s", id, user.id, data.model_dump(exclude_unset=True))
    try:
        edu = await ProfileService.update_education(db, user.id, id, data)
        if not edu:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Education record not found.")
        background_tasks.add_task(auto_backup, db, user.id)
        return edu
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("update_education failed for id=%s user=%s", id, user.id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.delete("/education/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_education(id: UUID, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deleted = await ProfileService.delete_education(db, user.id, id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Education record not found.")
    background_tasks.add_task(auto_backup, db, user.id)


# --- Experience ---
@router.get("/experience", response_model=List[ExperienceResponse])
async def get_experience(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await ProfileService.get_experience(db, user.id)

@router.post("/experience", response_model=ExperienceResponse, status_code=status.HTTP_201_CREATED)
async def add_experience(data: ExperienceCreate, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await ProfileService.add_experience(db, user.id, data)
    background_tasks.add_task(auto_backup, db, user.id)
    return result

@router.put("/experience/{id}", response_model=ExperienceResponse)
async def update_experience(id: UUID, data: ExperienceUpdate, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    logger.info("PUT /experience/%s user=%s payload=%s", id, user.id, data.model_dump(exclude_unset=True))
    try:
        exp = await ProfileService.update_experience(db, user.id, id, data)
        if not exp:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experience record not found.")
        background_tasks.add_task(auto_backup, db, user.id)
        return exp
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("update_experience failed for id=%s user=%s", id, user.id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.delete("/experience/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_experience(id: UUID, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deleted = await ProfileService.delete_experience(db, user.id, id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experience record not found.")
    background_tasks.add_task(auto_backup, db, user.id)


# --- Skills ---
@router.get("/skills", response_model=List[SkillResponse])
async def get_skills(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await ProfileService.get_skills(db, user.id)

@router.post("/skills", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
async def add_skill(data: SkillCreate, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await ProfileService.add_skill(db, user.id, data)
    background_tasks.add_task(auto_backup, db, user.id)
    return result

@router.delete("/skills/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(id: UUID, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deleted = await ProfileService.delete_skill(db, user.id, id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found.")
    background_tasks.add_task(auto_backup, db, user.id)

@router.put("/skills/{id}", response_model=SkillResponse)
async def update_skill(id: UUID, data: SkillUpdate, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    logger.info("PUT /skills/%s user=%s payload=%s", id, user.id, data.model_dump(exclude_unset=True))
    try:
        skill = await ProfileService.update_skill(db, user.id, id, data)
        if not skill:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found.")
        background_tasks.add_task(auto_backup, db, user.id)
        return skill
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("update_skill failed for id=%s user=%s", id, user.id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# --- Projects ---
@router.get("/projects", response_model=List[ProjectResponse])
async def get_projects(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await ProfileService.get_projects(db, user.id)

@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def add_project(data: ProjectCreate, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await ProfileService.add_project(db, user.id, data)
    background_tasks.add_task(auto_backup, db, user.id)
    return result

@router.put("/projects/{id}", response_model=ProjectResponse)
async def update_project(id: UUID, data: ProjectUpdate, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    logger.info("PUT /projects/%s user=%s payload=%s", id, user.id, data.model_dump(exclude_unset=True))
    try:
        proj = await ProfileService.update_project(db, user.id, id, data)
        if not proj:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
        background_tasks.add_task(auto_backup, db, user.id)
        return proj
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("update_project failed for id=%s user=%s", id, user.id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.delete("/projects/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(id: UUID, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deleted = await ProfileService.delete_project(db, user.id, id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    background_tasks.add_task(auto_backup, db, user.id)


# --- Achievements ---
@router.get("/achievements", response_model=List[AchievementResponse])
async def get_achievements(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await ProfileService.get_achievements(db, user.id)

@router.post("/achievements", response_model=AchievementResponse, status_code=status.HTTP_201_CREATED)
async def add_achievement(data: AchievementCreate, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await ProfileService.add_achievement(db, user.id, data)
    background_tasks.add_task(auto_backup, db, user.id)
    return result

@router.delete("/achievements/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_achievement(id: UUID, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    deleted = await ProfileService.delete_achievement(db, user.id, id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Achievement not found.")
    background_tasks.add_task(auto_backup, db, user.id)

@router.put("/achievements/{id}", response_model=AchievementResponse)
async def update_achievement(id: UUID, data: AchievementUpdate, background_tasks: BackgroundTasks, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    logger.info("PUT /achievements/%s user=%s payload=%s", id, user.id, data.model_dump(exclude_unset=True))
    try:
        ach = await ProfileService.update_achievement(db, user.id, id, data)
        if not ach:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Achievement not found.")
        background_tasks.add_task(auto_backup, db, user.id)
        return ach
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("update_achievement failed for id=%s user=%s", id, user.id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# --- Preferences ---
@router.get("/preferences", response_model=PreferencesResponse)
async def get_preferences(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await ProfileService.get_preferences(db, user.id)

@router.put("/preferences", response_model=PreferencesResponse)
async def update_preferences(data: PreferencesUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await ProfileService.update_preferences(db, user.id, data)


# --- Completeness details ---
@router.get("/completeness", response_model=ProfileCompletenessResponse)
async def get_completeness(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await ProfileService.compute_completeness_details(db, user.id)
