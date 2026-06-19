from typing import List, Optional, Dict, Any
from uuid import UUID
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.profile import CandidateProfile, Education, Experience, Skill, Project, Achievement, Preferences
import logging
from app.api.schemas.profile import (
    CandidateProfileUpdate,
    EducationCreate,
    EducationUpdate,
    ExperienceCreate,
    ExperienceUpdate,
    SkillCreate,
    SkillUpdate,
    ProjectCreate,
    ProjectUpdate,
    AchievementCreate,
    AchievementUpdate,
    PreferencesUpdate
)

logger = logging.getLogger("autoapply_ai.services.profile")


class ProfileService:
    @staticmethod
    async def get_profile(db: AsyncSession, user_id: UUID) -> Optional[CandidateProfile]:
        stmt = select(CandidateProfile).where(CandidateProfile.user_id == user_id)
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def update_profile(db: AsyncSession, user_id: UUID, data: CandidateProfileUpdate) -> CandidateProfile:
        profile = await ProfileService.get_profile(db, user_id)
        if not profile:
            profile = CandidateProfile(user_id=user_id)
            db.add(profile)
            await db.flush()

        update_data = data.model_dump(exclude_unset=True)
        for key, val in update_data.items():
            setattr(profile, key, val)
        
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
        
        # Recalculate score
        await ProfileService.update_completeness_score(db, user_id)
        return profile

    # --- Education CRUD ---
    @staticmethod
    async def get_education(db: AsyncSession, user_id: UUID) -> List[Education]:
        stmt = select(Education).where(Education.user_id == user_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def add_education(db: AsyncSession, user_id: UUID, data: EducationCreate) -> Education:
        edu = Education(user_id=user_id, **data.model_dump())
        db.add(edu)
        await db.commit()
        await db.refresh(edu)
        await ProfileService.update_completeness_score(db, user_id)
        return edu

    @staticmethod
    async def update_education(db: AsyncSession, user_id: UUID, edu_id: UUID, data: EducationUpdate) -> Optional[Education]:
        logger.info(f"update_education: user_id={user_id}, edu_id={edu_id}, payload={data.model_dump(exclude_unset=True)}")
        stmt = select(Education).where(Education.id == edu_id, Education.user_id == user_id)
        result = await db.execute(stmt)
        edu = result.scalars().first()
        if not edu:
            logger.warning(f"update_education: record not found for edu_id={edu_id}, user_id={user_id}")
            return None
            
        update_data = data.model_dump(exclude_unset=True)
        for key, val in update_data.items():
            setattr(edu, key, val)
        db.add(edu)
        try:
            await db.commit()
            await db.refresh(edu)
            logger.info(f"update_education: successfully committed changes to edu_id={edu_id}")
        except Exception as e:
            logger.exception(f"update_education: database commit failed for edu_id={edu_id}")
            await db.rollback()
            raise e
        return edu


    @staticmethod
    async def delete_education(db: AsyncSession, user_id: UUID, edu_id: UUID) -> bool:
        stmt = delete(Education).where(Education.id == edu_id, Education.user_id == user_id)
        result = await db.execute(stmt)
        await db.commit()
        await ProfileService.update_completeness_score(db, user_id)
        return result.rowcount > 0

    # --- Experience CRUD ---
    @staticmethod
    async def get_experience(db: AsyncSession, user_id: UUID) -> List[Experience]:
        stmt = select(Experience).where(Experience.user_id == user_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def add_experience(db: AsyncSession, user_id: UUID, data: ExperienceCreate) -> Experience:
        exp = Experience(user_id=user_id, **data.model_dump())
        db.add(exp)
        await db.commit()
        await db.refresh(exp)
        await ProfileService.update_completeness_score(db, user_id)
        return exp

    @staticmethod
    async def update_experience(db: AsyncSession, user_id: UUID, exp_id: UUID, data: ExperienceUpdate) -> Optional[Experience]:
        logger.info(f"update_experience: user_id={user_id}, exp_id={exp_id}, payload={data.model_dump(exclude_unset=True)}")
        stmt = select(Experience).where(Experience.id == exp_id, Experience.user_id == user_id)
        result = await db.execute(stmt)
        exp = result.scalars().first()
        if not exp:
            logger.warning(f"update_experience: record not found for exp_id={exp_id}, user_id={user_id}")
            return None
            
        update_data = data.model_dump(exclude_unset=True)
        for key, val in update_data.items():
            setattr(exp, key, val)
        db.add(exp)
        try:
            await db.commit()
            await db.refresh(exp)
            logger.info(f"update_experience: successfully committed changes to exp_id={exp_id}")
        except Exception as e:
            logger.exception(f"update_experience: database commit failed for exp_id={exp_id}")
            await db.rollback()
            raise e
        return exp


    @staticmethod
    async def delete_experience(db: AsyncSession, user_id: UUID, exp_id: UUID) -> bool:
        stmt = delete(Experience).where(Experience.id == exp_id, Experience.user_id == user_id)
        result = await db.execute(stmt)
        await db.commit()
        await ProfileService.update_completeness_score(db, user_id)
        return result.rowcount > 0

    # --- Skills CRUD ---
    @staticmethod
    async def get_skills(db: AsyncSession, user_id: UUID) -> List[Skill]:
        stmt = select(Skill).where(Skill.user_id == user_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def add_skill(db: AsyncSession, user_id: UUID, data: SkillCreate) -> Skill:
        # Check unique constraint
        stmt = select(Skill).where(Skill.user_id == user_id, Skill.skill_name == data.skill_name)
        result = await db.execute(stmt)
        existing = result.scalars().first()
        if existing:
            # Update proficiency or details; coerce None -> "INTERMEDIATE"
            existing.proficiency_level = data.proficiency_level or existing.proficiency_level or "INTERMEDIATE"
            existing.years_of_experience = data.years_of_experience or existing.years_of_experience
            existing.is_primary = data.is_primary if data.is_primary is not None else existing.is_primary
            db.add(existing)
            await db.commit()
            await db.refresh(existing)
            return existing

        # Coerce proficiency_level — never allow NULL in the DB
        skill_data = data.model_dump()
        skill_data["proficiency_level"] = skill_data.get("proficiency_level") or "INTERMEDIATE"

        skill = Skill(user_id=user_id, **skill_data)
        db.add(skill)
        await db.commit()
        await db.refresh(skill)
        await ProfileService.update_completeness_score(db, user_id)
        return skill

    @staticmethod
    async def delete_skill(db: AsyncSession, user_id: UUID, skill_id: UUID) -> bool:
        stmt = delete(Skill).where(Skill.id == skill_id, Skill.user_id == user_id)
        result = await db.execute(stmt)
        await db.commit()
        await ProfileService.update_completeness_score(db, user_id)
        return result.rowcount > 0

    @staticmethod
    async def update_skill(db: AsyncSession, user_id: UUID, skill_id: UUID, data: SkillUpdate) -> Optional[Skill]:
        logger.info(f"update_skill: user_id={user_id}, skill_id={skill_id}, payload={data.model_dump(exclude_unset=True)}")
        stmt = select(Skill).where(Skill.id == skill_id, Skill.user_id == user_id)
        result = await db.execute(stmt)
        skill = result.scalars().first()
        if not skill:
            logger.warning(f"update_skill: record not found for skill_id={skill_id}, user_id={user_id}")
            return None
            
        if data.skill_name and data.skill_name != skill.skill_name:
            conflict_stmt = select(Skill).where(Skill.user_id == user_id, Skill.skill_name == data.skill_name, Skill.id != skill_id)
            conflict_res = await db.execute(conflict_stmt)
            if conflict_res.scalars().first():
                logger.warning(f"update_skill: duplicate skill_name={data.skill_name} for user_id={user_id}")
                raise ValueError("A skill with this name already exists.")
                
        update_data = data.model_dump(exclude_unset=True)
        for key, val in update_data.items():
            setattr(skill, key, val)
        db.add(skill)
        try:
            await db.commit()
            await db.refresh(skill)
            logger.info(f"update_skill: successfully committed changes to skill_id={skill_id}")
        except Exception as e:
            logger.exception(f"update_skill: database commit failed for skill_id={skill_id}")
            await db.rollback()
            raise e
        return skill


    # --- Projects CRUD ---
    @staticmethod
    async def get_projects(db: AsyncSession, user_id: UUID) -> List[Project]:
        stmt = select(Project).where(Project.user_id == user_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def add_project(db: AsyncSession, user_id: UUID, data: ProjectCreate) -> Project:
        proj = Project(user_id=user_id, **data.model_dump())
        db.add(proj)
        await db.commit()
        await db.refresh(proj)
        await ProfileService.update_completeness_score(db, user_id)
        return proj

    @staticmethod
    async def update_project(db: AsyncSession, user_id: UUID, proj_id: UUID, data: ProjectUpdate) -> Optional[Project]:
        logger.info(f"update_project: user_id={user_id}, proj_id={proj_id}, payload={data.model_dump(exclude_unset=True)}")
        stmt = select(Project).where(Project.id == proj_id, Project.user_id == user_id)
        result = await db.execute(stmt)
        proj = result.scalars().first()
        if not proj:
            logger.warning(f"update_project: record not found for proj_id={proj_id}, user_id={user_id}")
            return None
            
        update_data = data.model_dump(exclude_unset=True)
        for key, val in update_data.items():
            setattr(proj, key, val)
        db.add(proj)
        try:
            await db.commit()
            await db.refresh(proj)
            logger.info(f"update_project: successfully committed changes to proj_id={proj_id}")
        except Exception as e:
            logger.exception(f"update_project: database commit failed for proj_id={proj_id}")
            await db.rollback()
            raise e
        return proj

    @staticmethod
    async def delete_project(db: AsyncSession, user_id: UUID, proj_id: UUID) -> bool:
        stmt = delete(Project).where(Project.id == proj_id, Project.user_id == user_id)
        result = await db.execute(stmt)
        await db.commit()
        await ProfileService.update_completeness_score(db, user_id)
        return result.rowcount > 0

    # --- Achievements CRUD ---
    @staticmethod
    async def get_achievements(db: AsyncSession, user_id: UUID) -> List[Achievement]:
        stmt = select(Achievement).where(Achievement.user_id == user_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def add_achievement(db: AsyncSession, user_id: UUID, data: AchievementCreate) -> Achievement:
        ach = Achievement(user_id=user_id, **data.model_dump())
        db.add(ach)
        await db.commit()
        await db.refresh(ach)
        await ProfileService.update_completeness_score(db, user_id)
        return ach

    @staticmethod
    async def delete_achievement(db: AsyncSession, user_id: UUID, ach_id: UUID) -> bool:
        stmt = delete(Achievement).where(Achievement.id == ach_id, Achievement.user_id == user_id)
        result = await db.execute(stmt)
        await db.commit()
        await ProfileService.update_completeness_score(db, user_id)
        return result.rowcount > 0

    @staticmethod
    async def update_achievement(db: AsyncSession, user_id: UUID, ach_id: UUID, data: AchievementUpdate) -> Optional[Achievement]:
        logger.info(f"update_achievement: user_id={user_id}, ach_id={ach_id}, payload={data.model_dump(exclude_unset=True)}")
        stmt = select(Achievement).where(Achievement.id == ach_id, Achievement.user_id == user_id)
        result = await db.execute(stmt)
        ach = result.scalars().first()
        if not ach:
            logger.warning(f"update_achievement: record not found for ach_id={ach_id}, user_id={user_id}")
            return None
            
        update_data = data.model_dump(exclude_unset=True)
        for key, val in update_data.items():
            setattr(ach, key, val)
        db.add(ach)
        try:
            await db.commit()
            await db.refresh(ach)
            logger.info(f"update_achievement: successfully committed changes to ach_id={ach_id}")
        except Exception as e:
            logger.exception(f"update_achievement: database commit failed for ach_id={ach_id}")
            await db.rollback()
            raise e
        return ach

    # --- Preferences CRUD ---
    @staticmethod
    async def get_preferences(db: AsyncSession, user_id: UUID) -> Preferences:
        stmt = select(Preferences).where(Preferences.user_id == user_id)
        result = await db.execute(stmt)
        prefs = result.scalars().first()
        if not prefs:
            prefs = Preferences(user_id=user_id)
            db.add(prefs)
            await db.commit()
            await db.refresh(prefs)
        return prefs

    @staticmethod
    async def update_preferences(db: AsyncSession, user_id: UUID, data: PreferencesUpdate) -> Preferences:
        prefs = await ProfileService.get_preferences(db, user_id)
        update_data = data.model_dump(exclude_unset=True)
        for key, val in update_data.items():
            setattr(prefs, key, val)
        db.add(prefs)
        await db.commit()
        await db.refresh(prefs)
        return prefs

    # --- Completeness Score Engine ---
    @staticmethod
    async def compute_completeness_details(db: AsyncSession, user_id: UUID) -> Dict[str, Any]:
        score = 0
        missing = []

        profile = await ProfileService.get_profile(db, user_id)
        # 1. Profile basic fields: max 20%
        p_score = 0
        if profile:
            if profile.linkedin_url: p_score += 4
            if profile.github_url: p_score += 4
            if profile.portfolio_url: p_score += 4
            if profile.profile_summary: p_score += 4
            if profile.years_of_experience is not None: p_score += 4
        if p_score < 20:
            missing.append("Candidate contact details and executive summary (linkedin, github, summary)")
        score += p_score

        # 2. Education records: 20%
        edus = await ProfileService.get_education(db, user_id)
        if edus:
            score += 20
        else:
            missing.append("Education details (Degree, Institution name)")

        # 3. Experience records: 20%
        exps = await ProfileService.get_experience(db, user_id)
        if exps:
            score += 20
        else:
            missing.append("Work or internship experience details")

        # 4. Skills list: 20%
        skills = await ProfileService.get_skills(db, user_id)
        if skills:
            score += 20
        else:
            missing.append("Candidate tech skills catalog")

        # 5. Projects list: 15%
        projs = await ProfileService.get_projects(db, user_id)
        if projs:
            score += 15
        else:
            missing.append("Notable personal/academic projects description")

        # 6. Achievements: 5%
        achs = await ProfileService.get_achievements(db, user_id)
        if achs:
            score += 5
        else:
            missing.append("Certificates or awards listings")

        return {"score": min(score, 100), "missing_sections": missing}

    @staticmethod
    async def update_completeness_score(db: AsyncSession, user_id: UUID) -> int:
        details = await ProfileService.compute_completeness_details(db, user_id)
        score = details["score"]
        
        # Save score back to profile
        profile = await ProfileService.get_profile(db, user_id)
        if profile:
            profile.profile_completeness_score = score
            db.add(profile)
            await db.commit()
            
        return score
