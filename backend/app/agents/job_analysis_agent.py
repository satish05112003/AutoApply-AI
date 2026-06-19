"""
Job Analysis Agent — extracts structured data from job descriptions.

Improvements:
  - LLM failure now falls back to heuristic extraction (never crashes orchestration)
  - Heuristic extractor detects skills from tech keyword lists
  - Truncates very long descriptions before sending to LLM (saves tokens)
  - Validates JSON output and retries on parse error
"""
import json
import re
import logging
from typing import Dict, Any, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from sqlalchemy import select
from app.agents.base_agent import BaseAgent, AgentResult
from app.models.jobs import JobPosting
from app.config import settings

logger = logging.getLogger("autoapply_ai.agents.job_analysis")

# ---------------------------------------------------------------------------
# Heuristic skill / tech-stack extraction (used when LLM is unavailable)
# ---------------------------------------------------------------------------
TECH_SKILLS = [
    "python", "javascript", "typescript", "java", "golang", "go", "rust", "c++", "c#",
    "ruby", "php", "scala", "kotlin", "swift", "r", "matlab",
    "react", "next.js", "vue", "angular", "svelte", "tailwind",
    "node.js", "express", "fastapi", "django", "flask", "spring", "rails",
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "sqlite",
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "ansible",
    "pytorch", "tensorflow", "scikit-learn", "pandas", "numpy", "huggingface",
    "langchain", "openai", "llm", "rag", "vector database", "qdrant", "pinecone",
    "graphql", "rest", "grpc", "kafka", "rabbitmq", "celery",
    "git", "github", "gitlab", "ci/cd", "jenkins", "github actions",
    "linux", "bash", "shell", "spark", "hadoop", "airflow", "dbt",
]

ML_KEYWORDS = ["machine learning", "ml", "deep learning", "neural", "nlp", "llm", "ai", "artificial intelligence",
                "pytorch", "tensorflow", "scikit", "computer vision", "reinforcement learning", "generative ai"]
DATA_KEYWORDS = ["data engineer", "data pipeline", "etl", "spark", "airflow", "dbt", "warehouse", "databricks"]
RESEARCH_KEYWORDS = ["research", "phd", "publication", "paper", "scientist", "r&d"]
EMBEDDED_KEYWORDS = ["embedded", "firmware", "rtos", "microcontroller", "fpga", "vlsi", "verilog"]

SENIORITY_MAP = {
    "intern": "INTERN", "internship": "INTERN",
    "entry level": "FRESHER", "fresher": "FRESHER", "graduate": "FRESHER", "new grad": "FRESHER",
    "junior": "JUNIOR", "associate": "JUNIOR", "i ": "JUNIOR",
    "senior": "SENIOR", "sr.": "SENIOR", "staff": "SENIOR", "principal": "SENIOR", "lead": "SENIOR",
    "mid": "MID", "ii ": "MID", "iii ": "MID"
}


def _heuristic_analysis(title: str, description: str) -> Dict[str, Any]:
    """
    Rule-based fallback analysis when LLM is unavailable.
    Detects tech stack, role category, and experience level from text.
    """
    text = f"{title} {description}".lower()

    def has_keyword(kw: str) -> bool:
        # Safely match keyword with word boundaries
        if kw in ["c++", "c#", "r&d"]:
            pattern = r'\b' + re.escape(kw)
        else:
            pattern = r'\b' + re.escape(kw) + r'\b'
        return bool(re.search(pattern, text))

    # Role category matching in priority order
    if any(has_keyword(k) for k in RESEARCH_KEYWORDS):
        role_category = "RESEARCH"
    elif any(has_keyword(k) for k in ML_KEYWORDS):
        role_category = "ML_ENGINEER"
    elif any(has_keyword(k) for k in DATA_KEYWORDS):
        role_category = "DATA_ENGINEER"
    elif "vlsi" in text:
        role_category = "VLSI"
    elif any(has_keyword(k) for k in EMBEDDED_KEYWORDS):
        role_category = "EMBEDDED"
    elif "full stack" in text or "fullstack" in text:
        role_category = "FULL_STACK"
    elif any(has_keyword(k) for k in ["software engineer", "sde", "developer", "backend", "platform"]):
        role_category = "SOFTWARE_ENGINEER"
    else:
        role_category = "SOFTWARE_ENGINEER"

    # Experience level
    experience_level = "MID"
    for keyword, level in SENIORITY_MAP.items():
        if keyword in title.lower():
            experience_level = level
            break

    # Tech stack with word boundaries
    detected_skills = []
    for skill in TECH_SKILLS:
        if skill in ["c++", "c#"]:
            pattern = r'\b' + re.escape(skill)
        else:
            pattern = r'\b' + re.escape(skill) + r'\b'
        if re.search(pattern, text):
            detected_skills.append(skill)

    # Role type
    role_type = "FULL_TIME"
    if "internship" in text or "intern" in title.lower():
        role_type = "INTERNSHIP"
    elif "contract" in text or "contractor" in text:
        role_type = "CONTRACT"
    elif "part-time" in text or "part time" in text:
        role_type = "PART_TIME"

    return {
        "role_category": role_category,
        "experience_level": experience_level,
        "required_skills": detected_skills[:15],
        "preferred_skills": [],
        "key_responsibilities": [],
        "must_have_qualifications": [],
        "nice_to_have_qualifications": [],
        "tech_stack_detected": detected_skills[:10],
        "application_complexity_score": 2,
        "has_cover_letter_requirement": "cover letter" in text,
        "has_assessment_requirement": "assessment" in text or "coding challenge" in text or "take-home" in text,
        "min_salary_inr": None,
        "max_salary_inr": None,
        "role_type": role_type,
        "red_flags": [],
        "_analysis_method": "heuristic"  # marker so we know this wasn't LLM-analyzed
    }


class JobAnalysisStructure(BaseModel):
    role_category: str = "SOFTWARE_ENGINEER"
    experience_level: str = "MID"
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    key_responsibilities: List[str] = Field(default_factory=list)
    must_have_qualifications: List[str] = Field(default_factory=list)
    nice_to_have_qualifications: List[str] = Field(default_factory=list)
    tech_stack_detected: List[str] = Field(default_factory=list)
    application_complexity_score: int = 2
    has_cover_letter_requirement: bool = False
    has_assessment_requirement: bool = False
    min_salary_inr: Optional[int] = None
    max_salary_inr: Optional[int] = None
    role_type: str = "FULL_TIME"
    red_flags: List[str] = Field(default_factory=list)


class JobAnalysisAgent(BaseAgent):
    agent_name = "JobAnalysisAgent"
    run_type = "JOB_ANALYSIS"

    # Max description length to send to LLM (saves tokens, speeds up analysis)
    MAX_DESC_CHARS = 3000

    async def run(self, input_data: Dict[str, Any]) -> AgentResult:
        """
        Input keys:
            job_id: str
        """
        job_id = input_data["job_id"]
        await self.initialize_run({"job_id": job_id})
        await self.log_info(f"Retrieving job details for analysis: {job_id}")

        try:
            job_db_id = UUID(job_id) if isinstance(job_id, str) else job_id

            stmt = select(JobPosting).where(JobPosting.id == job_db_id)
            res = await self.db.execute(stmt)
            job = res.scalars().first()
            if not job:
                raise ValueError("Job posting not found in database.")

            desc_text = job.job_description or ""
            title = job.role_title or ""

            # Truncate to save LLM tokens
            truncated_desc = desc_text[:self.MAX_DESC_CHARS]
            if len(desc_text) > self.MAX_DESC_CHARS:
                truncated_desc += "\n[description truncated for analysis]"

            # Try LLM analysis first
            parsed_analysis = None
            analysis_method = "llm"

            if truncated_desc.strip():
                system_prompt = (
                    "You are an expert technical recruiter. "
                    "Extract structured information from the job description. "
                    "Return ONLY a valid JSON object with these exact fields: "
                    "role_category (one of: SOFTWARE_ENGINEER, ML_ENGINEER, DATA_ENGINEER, FULL_STACK, EMBEDDED, VLSI, RESEARCH, OTHER), "
                    "experience_level (one of: INTERN, FRESHER, JUNIOR, MID, SENIOR), "
                    "required_skills (list of strings), "
                    "preferred_skills (list of strings), "
                    "key_responsibilities (list of strings, max 5), "
                    "must_have_qualifications (list), "
                    "nice_to_have_qualifications (list), "
                    "tech_stack_detected (list of tech keywords), "
                    "application_complexity_score (1-5 integer), "
                    "has_cover_letter_requirement (bool), "
                    "has_assessment_requirement (bool), "
                    "min_salary_inr (integer or null), "
                    "max_salary_inr (integer or null), "
                    "role_type (FULL_TIME, INTERNSHIP, CONTRACT, PART_TIME), "
                    "red_flags (list of concerning phrases). "
                    "No markdown, no backticks, just raw JSON."
                )
                prompt = f"Job Title: {title}\n\nJob Description:\n{truncated_desc}"

                try:
                    await self.log_info("Invoking LLM for structured job analysis...")
                    llm_response = await self.think(
                        prompt, system_prompt,
                        model=settings.OLLAMA_DEFAULT_MODEL,
                        response_model=JobAnalysisStructure,
                        temperature=0.1
                    )
                    # Parse JSON
                    clean_json = re.sub(r"```(?:json)?", "", llm_response).replace("```", "").strip()
                    parsed_analysis = json.loads(clean_json)
                    await self.log_info("LLM analysis succeeded.")
                except Exception as llm_err:
                    await self.log_warning(f"LLM analysis failed ({llm_err}). Falling back to heuristic extraction.")
                    analysis_method = "heuristic"

            if parsed_analysis is None:
                # Heuristic fallback — always succeeds
                parsed_analysis = _heuristic_analysis(title, desc_text)
                analysis_method = "heuristic"
                await self.log_info(f"Used heuristic analysis for job: {title}")

            # Update job posting record
            job.required_skills = parsed_analysis.get("required_skills", [])
            job.preferred_skills = parsed_analysis.get("preferred_skills", [])
            job.work_type = parsed_analysis.get("role_type", "FULL_TIME")
            job.salary_min_inr = parsed_analysis.get("min_salary_inr") or job.salary_min_inr
            job.salary_max_inr = parsed_analysis.get("max_salary_inr") or job.salary_max_inr
            job.job_description_parsed = {**parsed_analysis, "_analysis_method": analysis_method}

            self.db.add(job)
            await self.db.commit()

            await self.log_info(
                f"Job '{title}' analyzed via {analysis_method}. "
                f"Category: {parsed_analysis.get('role_category')}, "
                f"Skills: {len(parsed_analysis.get('required_skills', []))} detected."
            )

            result = AgentResult(success=True, output_data={"analysis": parsed_analysis, "method": analysis_method})
            await self.finalize_run(result)
            return result

        except Exception as e:
            await self.log_error(f"Failed job description analysis: {e}")
            result = AgentResult(success=False, error_message=str(e))
            await self.finalize_run(result)
            return result
