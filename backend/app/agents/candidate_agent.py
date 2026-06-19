import json
import logging
from typing import Dict, Any, Optional
from uuid import UUID
from sqlalchemy import select
from app.agents.base_agent import BaseAgent, AgentResult
from app.models.profile import CandidateProfile, Education, Experience, Skill, Project, Achievement, Preferences
from app.utils.embedding_utils import get_embedding
from app.config import settings

logger = logging.getLogger("autoapply_ai.agents.candidate")

class CandidateAgent(BaseAgent):
    agent_name = "CandidateAgent"
    run_type = "PROFILE_COMPILATION"

    async def run(self, input_data: Optional[Dict[str, Any]] = None) -> AgentResult:
        """
        Compile candidate profile details and generate executive career statements.
        Input keys: None required (uses self.user_id)
        """
        await self.initialize_run(input_data or {})
        await self.log_info("Compiling full candidate profile from database schemas...")

        try:
            u_id = UUID(self.user_id) if isinstance(self.user_id, str) else self.user_id
            
            # 1. Fetch Candidate Profile and Preferences
            stmt_p = select(CandidateProfile).where(CandidateProfile.user_id == u_id)
            res_p = await self.db.execute(stmt_p)
            profile = res_p.scalars().first()
            if not profile:
                profile = CandidateProfile(user_id=u_id)
                self.db.add(profile)
                await self.db.commit()
                await self.db.refresh(profile)

            stmt_pref = select(Preferences).where(Preferences.user_id == u_id)
            res_pref = await self.db.execute(stmt_pref)
            preferences = res_pref.scalars().first()

            # 2. Fetch history sections
            stmt_edu = select(Education).where(Education.user_id == u_id)
            res_edu = await self.db.execute(stmt_edu)
            edus = res_edu.scalars().all()

            stmt_exp = select(Experience).where(Experience.user_id == u_id)
            res_exp = await self.db.execute(stmt_exp)
            exps = res_exp.scalars().all()

            stmt_sk = select(Skill).where(Skill.user_id == u_id)
            res_sk = await self.db.execute(stmt_sk)
            skills = res_sk.scalars().all()

            stmt_pr = select(Project).where(Project.user_id == u_id)
            res_pr = await self.db.execute(stmt_pr)
            projects = res_pr.scalars().all()

            # 3. Use LLM to infer a natural language career statement
            skills_list = [s.skill_name for s in skills]
            exp_list = [f"{e.role_title} at {e.company_name}" for e in exps]
            
            prompt = (
                f"Candidate Details:\n"
                f"- Name: {profile.current_role or 'Candidate'}\n"
                f"- Skills: {', '.join(skills_list)}\n"
                f"- Experience: {', '.join(exp_list)}\n"
                f"- Address: {profile.address_city}, {profile.address_country}\n"
                f"Create a 3-sentence professional, impactful executive summary/career goal statement "
                f"highlighting their primary capabilities and career trajectory."
            )
            
            system_prompt = "You are a senior professional resume writer and recruitment consultant. Write in first-person, confident tone."
            
            await self.log_info("Asking LLM to synthesize a natural language profile summary...")
            summary = await self.think(prompt, system_prompt, model="phi3:mini")
            
            # 4. Generate profile embedding
            profile_text = f"Candidate Profile. Roles: {', '.join(preferences.preferred_roles if preferences else [])}. Skills: {', '.join(skills_list)}. Experience: {', '.join(exp_list)}."
            profile_embedding = get_embedding(profile_text)

            # 5. Update CandidateProfile record
            profile.profile_summary = summary
            profile.profile_embedding = profile_embedding
            profile.last_embedding_update = datetime.now(timezone.utc)
            self.db.add(profile)
            await self.db.commit()

            # 6. Cache CandidateProfile data in Redis for fast query lookups (TTL 1 Hour)
            if self.redis:
                cache_key = f"user_profile:{self.user_id}"
                cache_data = {
                    "user_id": str(self.user_id),
                    "summary": summary,
                    "skills": skills_list,
                    "preferred_roles": preferences.preferred_roles if preferences else []
                }
                self.redis.set_value(cache_key, cache_data, expire_seconds=3600)

            await self.emit_event("PROFILE_COMPILED", {"score": profile.profile_completeness_score})
            await self.log_info("Profile consolidated and vectorized in Qdrant/PostgreSQL successfully.")
            
            result = AgentResult(success=True, output_data={"summary": summary})
            await self.finalize_run(result)
            return result

        except Exception as e:
            await self.log_error(f"Failed to consolidate candidate profile: {e}")
            result = AgentResult(success=False, error_message=str(e))
            await self.finalize_run(result)
            return result
