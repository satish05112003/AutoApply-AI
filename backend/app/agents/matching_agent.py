import logging
from typing import Dict, Any, Optional, List
from uuid import UUID
from sqlalchemy import select
from app.agents.base_agent import BaseAgent, AgentResult
from app.models.profile import CandidateProfile, Preferences, Resume
from app.models.jobs import JobPosting
from app.config import settings

logger = logging.getLogger("autoapply_ai.agents.matching")

# ---------------------------------------------------------------------------
# Role synonym expansion — maps preferred_roles entries to equivalent titles
# ---------------------------------------------------------------------------
ROLE_SYNONYMS: Dict[str, List[str]] = {
    # Software engineering variants
    "software engineer": [
        "software", "engineer", "developer", "sde", "swe",
        "programmer", "software developer", "software development",
    ],
    "backend engineer": [
        "backend", "back-end", "back end", "server", "api engineer",
        "platform engineer", "python developer", "java developer",
    ],
    "frontend engineer": [
        "frontend", "front-end", "front end", "react engineer",
        "ui engineer", "web engineer",
    ],
    "full stack engineer": [
        "full stack", "fullstack", "full-stack",
    ],
    # AI / ML variants
    "machine learning engineer": [
        "machine learning", "ml engineer", "ai engineer", "deep learning",
        "applied scientist", "research engineer", "llm engineer",
        "nlp engineer", "computer vision engineer", "generative ai",
    ],
    "ml engineer": [
        "machine learning", "ml", "ai engineer", "deep learning",
        "applied scientist", "research scientist",
    ],
    "ai engineer": [
        "machine learning", "ml engineer", "artificial intelligence",
        "deep learning", "llm", "generative ai", "applied scientist",
    ],
    # Data
    "data engineer": [
        "data engineer", "data pipeline", "etl", "analytics engineer",
        "data platform",
    ],
    "data scientist": [
        "data scientist", "data science", "machine learning", "analytics",
    ],
    # DevOps/Infra
    "devops engineer": [
        "devops", "sre", "site reliability", "platform engineer",
        "infrastructure engineer", "cloud engineer",
    ],
    "sre": [
        "site reliability", "sre", "devops", "platform engineer",
    ],
    # Generic
    "developer": [
        "developer", "engineer", "programmer", "sde", "swe",
    ],
    "python developer": [
        "python", "django", "fastapi", "flask", "backend",
    ],
}


def _role_matches(job_title: str, preferred_roles: List[str]) -> bool:
    """
    Check if job_title matches any of preferred_roles using synonym expansion.
    
    Algorithm:
    1. Direct substring match (either direction)
    2. Expand preferred role via ROLE_SYNONYMS and check any synonym in title
    3. Expand job title via ROLE_SYNONYMS and check any synonym in preferred roles
    """
    jt = job_title.lower().strip()

    for role in preferred_roles:
        r = role.lower().strip()

        # 1. Direct match
        if r in jt or jt in r:
            return True

        # 2. Expand preferred role → check synonyms in job title
        synonyms = ROLE_SYNONYMS.get(r, [])
        for syn in synonyms:
            if syn in jt:
                return True

        # 3. Expand job title → see if any synonym matches the preferred role
        for canonical, syns in ROLE_SYNONYMS.items():
            if canonical in jt or any(s in jt for s in syns):
                # job title maps to this canonical; check if preferred role is related
                if r in canonical or canonical in r:
                    return True
                if any(r in s or s in r for s in syns):
                    return True

    return False

class MatchingAgent(BaseAgent):
    agent_name = "MatchingAgent"
    run_type = "JOB_MATCHING"

    async def run(self, input_data: Dict[str, Any]) -> AgentResult:
        """
        Input keys:
            job_id: str
        """
        job_id = input_data["job_id"]
        await self.initialize_run({"job_id": job_id})
        await self.log_info(f"Running profile matching analysis for job: {job_id}")

        try:
            u_id = UUID(self.user_id) if isinstance(self.user_id, str) else self.user_id
            job_db_id = UUID(job_id) if isinstance(job_id, str) else job_id

            # 1. Fetch Candidate profile and preferences
            stmt_p = select(CandidateProfile).where(CandidateProfile.user_id == u_id)
            res_p = await self.db.execute(stmt_p)
            profile = res_p.scalars().first()

            stmt_pref = select(Preferences).where(Preferences.user_id == u_id)
            res_pref = await self.db.execute(stmt_pref)
            prefs = res_pref.scalars().first()

            # 2. Fetch Job details
            stmt_j = select(JobPosting).where(JobPosting.id == job_db_id)
            res_j = await self.db.execute(stmt_j)
            job = res_j.scalars().first()

            if not profile or not prefs or not job:
                raise ValueError("Required database profiles, preferences, or job records missing.")

            # --- Negative keyword filter (expanded) ---
            # Discard non-tech roles that slipped past crawlers
            jt_lower = (job.role_title or "").lower().strip()
            pref_roles = prefs.preferred_roles or []

            negative_keywords = [
                "frontend", "ui/ux", "ui ux", "ux designer", "graphic designer",
                "marketing", "sales", "hr", "human resources", "recruitment", "recruiter",
                "finance", "financial", "accounting", "accountant", "controller",
                "legal", "counsel", "attorney", "compliance",
                "customer success", "customer support", "customer service",
                "operations manager", "operations associate", "business analyst",
                "content writer", "copywriter", "seo", "social media",
            ]
            has_neg_match = any(neg in jt_lower for neg in negative_keywords)

            neg_override = False
            if has_neg_match:
                for neg in negative_keywords:
                    if neg in jt_lower:
                        if any(neg in r.lower() for r in pref_roles):
                            neg_override = True
                            break

            if has_neg_match and not neg_override:
                await self.log_warning(f"Role '{job.role_title}' matched negative filter. SKIP.")
                result = AgentResult(success=True, output_data={
                    "decision": "SKIP",
                    "score": 0.0,
                    "reasoning": "SKIPPED_ROLE_MISMATCH"
                })
                await self.finalize_run(result)
                return result

            # --- Preferred / Target Roles enforcement (synonym-expanded) ---
            if pref_roles:
                if not _role_matches(job.role_title or "", pref_roles):
                    await self.log_info(
                        f"Role '{job.role_title}' does not match preferred roles {pref_roles} "
                        f"(after synonym expansion). SKIP."
                    )
                    result = AgentResult(success=True, output_data={
                        "decision": "SKIP",
                        "score": 0.0,
                        "reasoning": "SKIPPED_ROLE_MISMATCH"
                    })
                    await self.finalize_run(result)
                    return result

            # --- Blacklist Checks ---
            company_name = job.company_name or ""
            if prefs.blacklisted_companies and any(bc.lower().strip() == company_name.lower().strip() for bc in prefs.blacklisted_companies):
                await self.log_warning(f"Company '{company_name}' is blacklisted by user. Forcing SKIP.")
                result = AgentResult(success=True, output_data={"decision": "SKIP", "score": 0.0, "reasoning": "Company is blacklisted."})
                await self.finalize_run(result)
                return result

            # 3. Compute component scores
            # a) Skill Score: 40%
            job_skills = set(s.lower().strip() for s in (job.required_skills or []))
            candidate_skills = set(s.lower().strip() for s in (prefs.required_skills or []))
            
            if not job_skills:
                skill_score = 100.0
            else:
                matched_skills = candidate_skills.intersection(job_skills)
                skill_score = (len(matched_skills) / len(job_skills)) * 100.0
                
            # Add bonus for preferred skills
            preferred_matched = candidate_skills.intersection(set(s.lower().strip() for s in (job.preferred_skills or [])))
            skill_score = min(100.0, skill_score + (len(preferred_matched) * 5.0))

            # b) Experience Score: 20%
            years_experience = float(profile.years_of_experience or 0.0)
            job_exp_min = float(job.experience_min_years or 0.0)
            
            if years_experience >= job_exp_min:
                exp_score = 100.0
            elif years_experience == 0.0 and job_exp_min <= 1.0:
                exp_score = 90.0
            else:
                # Interpolation
                diff = job_exp_min - years_experience
                exp_score = max(0.0, 100.0 - (diff * 25.0))

            # c) Education Score: 15%
            # Mock CGPA score check
            cgpa = float(9.0) # mock check / default
            education_score = 100.0
            if cgpa >= 8.0: education_score = 100.0
            elif cgpa >= 7.0: education_score = 85.0
            else: education_score = 60.0

            # d) Location Score: 10%
            location_score = 100.0
            job_loc = (job.location or "").lower()
            if job.is_remote and "remote" in [r.lower() for r in (prefs.work_type_preference or [])]:
                location_score = 100.0
            elif any(loc.lower() in job_loc for loc in (prefs.preferred_locations or [])):
                location_score = 100.0
            else:
                location_score = 50.0

            # e) Salary Score: 10%
            salary_score = 100.0
            if job.salary_max_inr and prefs.min_salary_inr:
                if job.salary_max_inr >= prefs.min_salary_inr:
                    salary_score = 100.0
                else:
                    salary_score = (float(job.salary_max_inr) / float(prefs.min_salary_inr)) * 100.0

            # f) Semantic Similarity Score: 5% (Using cosine similarity)
            semantic_score = 80.0 # Default
            if job.job_description_embedding and profile.profile_embedding:
                try:
                    import numpy as np
                    v_job = np.array(job.job_description_embedding)
                    v_prof = np.array(profile.profile_embedding)
                    cosine_sim = np.dot(v_job, v_prof) / (np.linalg.norm(v_job) * np.linalg.norm(v_prof))
                    semantic_score = float(cosine_sim) * 100.0
                except Exception:
                    pass

            # 4. Total Compatibility Score calculation
            overall_score = (
                skill_score * 0.40 +
                exp_score * 0.20 +
                education_score * 0.15 +
                location_score * 0.10 +
                salary_score * 0.10 +
                semantic_score * 0.05
            )

            # 5. Apply threshold decision rules
            # auto_apply_threshold in Preferences is a float (0-100 score threshold)
            # Fall back to settings defaults if not set
            auto_apply_th = prefs.auto_apply_threshold if prefs.auto_apply_threshold is not None else 85.0
            min_match_th = prefs.min_match_score if prefs.min_match_score is not None else float(settings.MIN_MATCH_SCORE_TO_APPLY)
            
            if overall_score >= auto_apply_th:
                decision = "APPLY"
            elif overall_score >= min_match_th:
                decision = "REVIEW"
            else:
                decision = "SKIP"

            # 6. Ask LLM for reasoning (non-blocking — if LLM fails, use score summary)
            try:
                prompt = (
                    f"Job Role: {job.role_title} at {job.company_name}\n"
                    f"Compatibility scores:\n"
                    f"  Skill Match: {skill_score:.1f}%\n"
                    f"  Experience Match: {exp_score:.1f}%\n"
                    f"  Location Match: {location_score:.1f}%\n"
                    f"Overall Score: {overall_score:.1f}/100. Decision: {decision}\n"
                    f"Write one sentence explaining this match rating."
                )
                reasoning = await self.think(
                    prompt,
                    "You are a concise job matching assistant.",
                    model=settings.OLLAMA_DEFAULT_MODEL,
                    temperature=0.1
                )
            except Exception:
                reasoning = (
                    f"Score {overall_score:.1f}/100: skill={skill_score:.0f}%, "
                    f"exp={exp_score:.0f}%, location={location_score:.0f}%."
                )

            await self.emit_event("JOB_MATCHED", {"job_id": job_id, "score": float(overall_score), "decision": decision})
            await self.log_info(f"Match assessment completed. Score: {overall_score:.1f}/100. Decision: {decision}")

            result = AgentResult(success=True, output_data={
                "score": float(overall_score),
                "decision": decision,
                "reasoning": reasoning
            })
            await self.finalize_run(result)
            return result

        except Exception as e:
            await self.log_error(f"Failed to execute matching matrix calculations: {e}")
            result = AgentResult(success=False, error_message=str(e))
            await self.finalize_run(result)
            return result
