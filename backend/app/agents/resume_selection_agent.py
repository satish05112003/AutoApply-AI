import logging
from typing import Dict, Any, List
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy import select
from app.agents.base_agent import BaseAgent, AgentResult
from app.models.profile import Resume
from app.models.jobs import JobPosting

logger = logging.getLogger("autoapply_ai.agents.resume_selection")

class ResumeSelectionAgent(BaseAgent):
    agent_name = "ResumeSelectionAgent"
    run_type = "RESUME_SELECTION"

    async def run(self, input_data: Dict[str, Any]) -> AgentResult:
        """
        Input keys:
            job_id: str
        """
        job_id = input_data["job_id"]
        await self.initialize_run({"job_id": job_id})
        await self.log_info("Selecting the best matching resume using semantic scoring, category matching, and freshness...")

        try:
            u_id = UUID(self.user_id) if isinstance(self.user_id, str) else self.user_id
            job_db_id = UUID(job_id) if isinstance(job_id, str) else job_id

            # 1. Fetch JobPosting details
            stmt_j = select(JobPosting).where(JobPosting.id == job_db_id)
            res_j = await self.db.execute(stmt_j)
            job = res_j.scalars().first()
            if not job:
                raise ValueError("Job posting not found.")

            role_category = "GENERALIST"
            if job.job_description_parsed:
                role_category = job.job_description_parsed.get("role_category", "GENERALIST")

            # 2. Fetch all user Resumes
            stmt_res = select(Resume).where(Resume.user_id == u_id, Resume.is_active == True)
            res_list = await self.db.execute(stmt_res)
            resumes = res_list.scalars().all()

            if not resumes:
                raise ValueError("No active resumes found for user profile.")

            # 3. Score resumes using a multi-factor formula:
            # Score = (Semantic Similarity * 0.6) + (Category Match Bonus * 0.3) + (Freshness * 0.1)
            import numpy as np
            scored_resumes = []
            
            # Map role category to resume type
            role_mappings = {
                "ML_ENGINEER": "AI_ML",
                "DATA_SCIENTIST": "AI_ML",
                "EMBEDDED": "CORE_ENGINEERING",
                "VLSI": "CORE_ENGINEERING",
                "RESEARCH": "RESEARCH"
            }
            target_type = role_mappings.get(role_category, "SOFTWARE")
            
            # Find the newest resume upload date for freshness comparison
            newest_upload = None
            for r in resumes:
                if r.upload_at:
                    # Remove timezone if naive for comparison, else convert to naive utc
                    up_date = r.upload_at.replace(tzinfo=None) if r.upload_at.tzinfo else r.upload_at
                    if not newest_upload or up_date > newest_upload:
                        newest_upload = up_date
            if not newest_upload:
                newest_upload = datetime.utcnow()
            
            for r in resumes:
                # Factor A: Semantic Similarity (60%)
                similarity = 0.70
                if r.embedding and job.job_description_embedding:
                    try:
                        v_res = np.array(r.embedding, dtype=float)
                        v_job = np.array(job.job_description_embedding, dtype=float)
                        similarity = float(np.dot(v_res, v_job) / (np.linalg.norm(v_res) * np.linalg.norm(v_job)))
                    except Exception as emb_err:
                        logger.debug(f"Error computing similarity for resume {r.id}: {emb_err}")
                
                # Factor B: Category Match (30%)
                role_bonus = 0.0
                if r.resume_type == target_type:
                    role_bonus = 1.0
                elif r.resume_type == "SOFTWARE" and target_type in ["AI_ML", "CORE_ENGINEERING"]:
                    role_bonus = 0.5
                elif r.is_primary:
                    role_bonus = 0.3
                    
                # Factor C: Freshness (10%)
                freshness_bonus = 0.0
                if r.upload_at:
                    up_date = r.upload_at.replace(tzinfo=None) if r.upload_at.tzinfo else r.upload_at
                    days_since_upload = (newest_upload - up_date).days
                    freshness_bonus = max(0.0, 1.0 - (days_since_upload / 30.0))  # Decays to 0 over 30 days
                elif r.is_primary:
                    freshness_bonus = 0.5
                    
                total_score = (similarity * 0.6) + (role_bonus * 0.3) + (freshness_bonus * 0.1)
                scored_resumes.append((total_score, similarity, r))
                
            # Sort by total_score descending
            scored_resumes.sort(key=lambda x: x[0], reverse=True)
            best_score, best_similarity, selected_resume = scored_resumes[0]

            await self.log_info(
                f"Selected resume '{selected_resume.resume_name}' (type: {selected_resume.resume_type}) "
                f"for role category '{role_category}'. Cosine similarity: {best_similarity:.2f}, Factor Score: {best_score:.2f}"
            )
            
            result = AgentResult(success=True, output_data={
                "resume_id": str(selected_resume.id),
                "resume_name": selected_resume.resume_name,
                "resume_type": selected_resume.resume_type,
                "similarity_score": best_similarity
            })
            await self.finalize_run(result)
            return result

        except Exception as e:
            await self.log_error(f"Failed selecting resume: {e}")
            result = AgentResult(success=False, error_message=str(e))
            await self.finalize_run(result)
            return result
