import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.agents import ScreeningAnswer
from app.models.profile import CandidateProfile, Preferences
from app.llm.router import llm_router

logger = logging.getLogger("autoapply_ai.screening_engine")

class ScreeningQuestionEngine:
    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id
        self.llm = llm_router

    def _normalize_and_hash(self, question: str) -> str:
        """Clean and SHA256 hash a question text for caching keys."""
        cleaned = " ".join(question.strip().lower().split())
        return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()

    async def get_answer(self, question_text: str, profile_data: Dict[str, Any]) -> Tuple[str, bool]:
        """
        Get answer for a screening question.
        Check rule-based templates first, then DB cache, and finally fall back to LLM.
        Returns: Tuple[answer_text, used_cache]
        """
        u_id = UUID(self.user_id) if isinstance(self.user_id, str) else self.user_id
        
        # Load fresh profile and preferences for rule-based match
        stmt_pref = select(Preferences).where(Preferences.user_id == u_id)
        res_pref = await self.db.execute(stmt_pref)
        prefs = res_pref.scalars().first()

        stmt_prof = select(CandidateProfile).where(CandidateProfile.user_id == u_id)
        res_prof = await self.db.execute(stmt_prof)
        profile = res_prof.scalars().first()

        # 1. Check common question templates (Rule-based pre-computed answers)
        template_answer = self._check_templates(question_text, prefs, profile)
        if template_answer:
            logger.info(f"ScreeningEngine: Template rule-based match for question: '{question_text}' -> '{template_answer}'")
            return template_answer, True

        q_hash = self._normalize_and_hash(question_text)

        # 2. Check database cache
        stmt = select(ScreeningAnswer).where(
            ScreeningAnswer.user_id == u_id,
            ScreeningAnswer.question_hash == q_hash
        )
        result = await self.db.execute(stmt)
        cached = result.scalars().first()
        
        if cached:
            cached.use_count += 1
            cached.last_used_at = datetime.now(timezone.utc)
            self.db.add(cached)
            await self.db.commit()
            logger.info(f"ScreeningEngine: Cache hit for question hash: {q_hash}")
            return cached.answer_text, True

        # 3. Cache miss: Generate tailored answer via LLM
        logger.info(f"ScreeningEngine: Cache miss. Generating answer via LLM for: {question_text}")
        answer = await self._generate_answer_from_llm(question_text, profile_data)

        # 4. Store new answer in database
        try:
            async with self.db.begin_nested():
                new_answer = ScreeningAnswer(
                    user_id=u_id,
                    question_hash=q_hash,
                    question_text=question_text,
                    answer_text=answer,
                    answer_source="AI_GENERATED"
                )
                self.db.add(new_answer)
                await self.db.flush()
            await self.db.commit()
        except Exception as e:
            logger.info(f"ScreeningEngine: Duplicate key or integrity error on insert, fetching cached value: {e}")
            stmt = select(ScreeningAnswer).where(
                ScreeningAnswer.user_id == u_id,
                ScreeningAnswer.question_hash == q_hash
            )
            result = await self.db.execute(stmt)
            cached = result.scalars().first()
            if cached:
                answer = cached.answer_text

        return answer, False

    def _check_templates(self, question: str, prefs: Optional[Preferences], profile: Optional[CandidateProfile]) -> Optional[str]:
        """Check question text against standard regex patterns for common profile metrics."""
        ql = question.lower()
        
        # A. Salary expectation
        if any(kw in ql for kw in ["salary", "ctc", "compensation", "expectation", "expected pay"]):
            salary = 0
            if prefs:
                salary = prefs.preferred_salary_inr or prefs.min_salary_inr or 0
            if salary > 0:
                lakhs = salary // 100000
                return f"My salary expectation is around {lakhs} LPA, negotiable depending on the overall role and benefits."
            return "My salary expectation is negotiable and open to discussion depending on the role requirements."

        # B. Notice period / Start date
        if any(kw in ql for kw in ["notice period", "notice", "start date", "joining", "how soon", "available"]):
            notice_days = prefs.notice_period_days if prefs else 0
            if notice_days == 0:
                return "I am available to start immediately."
            return f"My notice period is {notice_days} days."

        # C. Relocation
        if any(kw in ql for kw in ["relocate", "relocation", "willing to work", "move to"]):
            locations = prefs.preferred_locations if (prefs and prefs.preferred_locations) else []
            if locations and "remote" not in [loc.lower() for loc in locations]:
                loc_list = ", ".join(locations)
                return f"Yes, I am willing to relocate and work in my preferred locations: {loc_list}."
            return "I prefer remote roles but am open to discussing relocation for the right opportunity."

        # D. Work authorization & Visa sponsorship
        if any(kw in ql for kw in ["visa", "sponsorship", "sponsor", "authorized", "citizenship", "citizen"]):
            work_auth = prefs.work_authorization if prefs else "INDIA_CITIZEN"
            if work_auth == "INDIA_CITIZEN":
                return "Yes, I am authorized to work in India and do not require visa sponsorship."
            return "I am authorized to work and do not require visa sponsorship."

        # E. Years of experience
        if any(kw in ql for kw in ["years of experience", "total experience", "how many years"]):
            yoe = profile.years_of_experience if profile else 0.0
            if yoe > 0:
                # Format to remove decimal if it is integer
                yoe_str = f"{int(yoe)}" if yoe == int(yoe) else f"{yoe}"
                return f"I have {yoe_str} years of professional software engineering experience."
            return "I have relevant experience in software engineering and machine learning roles as detailed in my resume."

        # F. Links
        if any(kw in ql for kw in ["github", "linkedin", "website", "portfolio"]):
            if "github" in ql and profile and profile.github_url:
                return profile.github_url
            if "linkedin" in ql and profile and profile.linkedin_url:
                return profile.linkedin_url
            if ("website" in ql or "portfolio" in ql) and profile and profile.portfolio_url:
                return profile.portfolio_url
            return "Links to my GitHub, LinkedIn, and portfolio are provided directly in my resume."

        return None

    async def _generate_answer_from_llm(self, question: str, profile_data: Dict[str, Any]) -> str:
        summary = profile_data.get("summary", "")
        skills = ", ".join(profile_data.get("skills", []))
        
        # Build prompt depending on question type keywords
        q_lower = question.lower()
        
        if "tell me about yourself" in q_lower or "introduce yourself" in q_lower or "tell us about yourself" in q_lower:
            prompt = (
                f"Candidate Summary: {summary}\n"
                f"Candidate Skills: {skills}\n"
                f"Question: {question}\n"
                f"Write a 3-sentence professional introduction for this question. "
                f"Keep it concise, confident, and generic enough to be re-usable. Do not mention any company names."
            )
            system = "You are a professional software engineer answering a standard recruiter question. Write in first-person."
            
        elif "why should we hire you" in q_lower or "why are you a good fit" in q_lower:
            prompt = (
                f"Candidate Summary: {summary}\n"
                f"Candidate Skills: {skills}\n"
                f"Question: {question}\n"
                f"Write a compelling 3-sentence answer highlighting how their technical skills and projects fit engineering team objectives."
            )
            system = "You are an applicant pitching your engineering capabilities. Write in first-person."
            
        else:
            prompt = (
                f"Candidate Context:\n"
                f"- Profile summary: {summary}\n"
                f"- Technical skills: {skills}\n"
                f"Question to answer: {question}\n"
                f"Generate a professional, short, and accurate answer (max 3 sentences) to this question using the candidate's context. "
                f"Do not invent facts not supported by their background."
            )
            system = "You are a job seeker answering a screening question. Be concise, direct, and completely honest."

        try:
            ans = await self.llm.think(prompt, system, model="phi3:mini")
            return ans.strip()
        except Exception as e:
            logger.warning(f"ScreeningEngine LLM call failed: {e}. Falling back to heuristic answers.")
            
            # Heuristic fallback (if check_templates didn't catch it)
            ql = q_lower
            if "notice" in ql or "start" in ql or "available" in ql:
                return "I am available to start immediately."
            elif "visa" in ql or "sponsorship" in ql or "sponsor" in ql:
                return "I do not require visa sponsorship to work."
            elif "experience" in ql or "years of" in ql:
                return "I have relevant experience in software engineering and machine learning roles as detailed in my resume."
            else:
                return "Yes, I have relevant experience and am confident in my ability to perform this role effectively."
