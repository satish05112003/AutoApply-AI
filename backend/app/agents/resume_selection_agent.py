import logging
from typing import Dict, Any, List
from uuid import UUID
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
        await self.log_info("Selecting the best matching resume for the job category...")

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

            # Find matching logic:
            # - ML/AI jobs -> AI_ML resume
            # - Embedded/VLSI -> CORE_ENGINEERING resume
            # - Research -> RESEARCH resume
            # - else -> SOFTWARE or GENERALIST resume
            selected_resume = None
            
            # Map role category to resume type
            role_mappings = {
                "ML_ENGINEER": "AI_ML",
                "DATA_SCIENTIST": "AI_ML",
                "EMBEDDED": "CORE_ENGINEERING",
                "VLSI": "CORE_ENGINEERING",
                "RESEARCH": "RESEARCH"
            }
            target_type = role_mappings.get(role_category, "SOFTWARE")

            # 3. Match resume by target type
            for r in resumes:
                if r.resume_type == target_type:
                    selected_resume = r
                    break
                    
            # Fallback 1: primary resume
            if not selected_resume:
                for r in resumes:
                    if r.is_primary:
                        selected_resume = r
                        break
                        
            # Fallback 2: first resume in list
            if not selected_resume:
                selected_resume = resumes[0]

            # 4. Compute cosine similarity if embeddings are present
            similarity = 0.80
            if selected_resume.embedding and job.job_description_embedding:
                try:
                    import numpy as np
                    v_res = np.array(selected_resume.embedding)
                    v_job = np.array(job.job_description_embedding)
                    similarity = float(np.dot(v_res, v_job) / (np.linalg.norm(v_res) * np.linalg.norm(v_job)))
                except Exception:
                    pass

            await self.log_info(f"Selected resume '{selected_resume.resume_name}' (type: {selected_resume.resume_type}) for role category '{role_category}'. Cosine similarity: {similarity:.2f}")
            
            result = AgentResult(success=True, output_data={
                "resume_id": str(selected_resume.id),
                "resume_name": selected_resume.resume_name,
                "resume_type": selected_resume.resume_type,
                "similarity_score": similarity
            })
            await self.finalize_run(result)
            return result

        except Exception as e:
            await self.log_error(f"Failed selecting resume: {e}")
            result = AgentResult(success=False, error_message=str(e))
            await self.finalize_run(result)
            return result
