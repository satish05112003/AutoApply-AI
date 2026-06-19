import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Tuple
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
        Returns: Tuple[answer_text, used_cache]
        """
        q_hash = self._normalize_and_hash(question_text)
        u_id = UUID(self.user_id) if isinstance(self.user_id, str) else self.user_id

        # 1. Check database cache
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

        # 2. Cache miss: Generate tailored answer via LLM
        logger.info(f"ScreeningEngine: Cache miss. Generating answer via LLM for: {question_text}")
        answer = await self._generate_answer_from_llm(question_text, profile_data)

        # 3. Store new answer in database
        new_answer = ScreeningAnswer(
            user_id=u_id,
            question_hash=q_hash,
            question_text=question_text,
            answer_text=answer,
            answer_source="AI_GENERATED"
        )
        self.db.add(new_answer)
        await self.db.commit()

        return answer, False

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
            
        elif "salary" in q_lower or "expectation" in q_lower or "expected ctc" in q_lower:
            # Look up preferred salary
            pref_salary = profile_data.get("min_salary_inr", 800000)
            formatted_salary = f"{pref_salary // 100000} LPA" if pref_salary else "negotiable"
            prompt = (
                f"Candidate Salary preferences: {formatted_salary}\n"
                f"Question: {question}\n"
                f"Generate a professional response stating the salary expectation based on the candidate's preferences."
            )
            system = "Provide a polite, professional salary negotiation response. Keep it brief."
            
        else:
            # General screen questions
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
            
            # Simple rule-based fallback
            ql = q_lower
            if "salary" in ql or "expectation" in ql or "expected ctc" in ql:
                pref_salary = profile_data.get("min_salary_inr")
                if pref_salary:
                    return f"My salary expectation is around {pref_salary // 100000} LPA, negotiable depending on the overall role and benefits."
                return "My salary expectation is negotiable and open to discussion depending on the role requirements."
            elif "notice" in ql or "start" in ql or "available" in ql:
                notice = profile_data.get("notice_period_days", 0)
                if notice == 0:
                    return "I am available to start immediately."
                return f"My notice period is {notice} days."
            elif "visa" in ql or "sponsorship" in ql or "sponsor" in ql:
                return "I do not require visa sponsorship to work."
            elif "experience" in ql or "years of" in ql:
                return "I have relevant experience in software engineering and machine learning roles as detailed in my resume."
            elif "github" in ql or "linkedin" in ql or "website" in ql:
                return "Detailed links are provided in my resume."
            else:
                return "Yes, I have relevant experience and am confident in my ability to perform this role effectively."
