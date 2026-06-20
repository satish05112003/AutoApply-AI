import json
import logging
import traceback
from datetime import datetime
from typing import Dict, Any, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from sqlalchemy import select
from app.config import settings
from app.agents.base_agent import BaseAgent, AgentResult
from app.models.profile import Resume, ResumeSection, Education, Experience, Skill as ProfileSkill, Project, Achievement
from app.utils.resume_parser import extract_text_from_pdf, parse_resume_deterministic
from app.utils.embedding_utils import get_embedding
from app.integrations.vector_db_client import qdrant_client
from app.services.storage_service import StorageService

logger = logging.getLogger("autoapply_ai.agents.resume")

# Structured schemas for LLM outputs
class ResumeStructure(BaseModel):
    full_name: str
    email: str
    phone: str
    summary: str
    education: List[Dict[str, Any]] = Field(default=[])
    experience: List[Dict[str, Any]] = Field(default=[])
    skills: List[str] = Field(default=[])
    projects: List[Dict[str, Any]] = Field(default=[])
    achievements: List[str] = Field(default=[])
    resume_type: str = "GENERALIST" # SOFTWARE, AI_ML, CORE_ENGINEERING, RESEARCH, GENERALIST

class ResumeAgent(BaseAgent):
    agent_name = "ResumeAgent"
    run_type = "RESUME_PARSING"

    async def run(self, input_data: Dict[str, Any]) -> AgentResult:
        """
        Input keys:
            pdf_bytes: bytes
            filename: str
            user_id: str
            resume_name: str
            is_primary: bool
        """
        pdf_bytes = input_data["pdf_bytes"]
        filename = input_data["filename"]
        resume_name = input_data["resume_name"]
        is_primary = input_data.get("is_primary", False)
        
        await self.initialize_run({"filename": filename, "resume_name": resume_name, "is_primary": is_primary})
        await self.log_info(f"Starting resume parsing workflow for: {filename}")

        try:
            # ── Pre-parse validation ─────────────────────────────────────────
            if not pdf_bytes:
                raise ValueError("PDF bytes are empty — no data was received.")
            if len(pdf_bytes) < 512:
                raise ValueError(f"PDF file is suspiciously small ({len(pdf_bytes)} bytes). Upload may be corrupt.")
            await self.log_info(f"Pre-parse validation passed. File size: {len(pdf_bytes):,} bytes.")
            await self.log_info(f"LLM provider: {settings.OLLAMA_BASE_URL} | model: {settings.OLLAMA_DEFAULT_MODEL}")
            await self.log_info(f"Embedding model: {settings.EMBEDDING_MODEL}")
            await self.log_info(f"Storage type: {settings.STORAGE_TYPE}")

            # 1. Parse text from PDF
            await self.log_info("Extracting raw text from PDF document...")
            raw_text = extract_text_from_pdf(pdf_bytes)
            if not raw_text or len(raw_text) < 100:
                raise ValueError("Extracted text is too short or empty. The PDF may be image-only or encrypted.")

            await self.log_info(f"Extracted {len(raw_text)} characters. Starting structure parsing...")

            # 2. Upload raw PDF to storage service
            u_id = UUID(self.user_id) if isinstance(self.user_id, str) else self.user_id
            resume_db_id = UUID(input_data.get("resume_id")) if input_data.get("resume_id") else None
            
            # Create resume record in DB first if not passed
            if not resume_db_id:
                new_resume = Resume(
                    user_id=u_id,
                    resume_name=resume_name,
                    resume_type="PENDING",
                    file_key=f"resumes/{self.user_id}/temp_{filename}",
                    is_primary=is_primary,
                )
                self.db.add(new_resume)
                await self.db.commit()
                await self.db.refresh(new_resume)
                resume_db_id = new_resume.id

            file_key = f"resumes/{self.user_id}/{resume_db_id}.pdf"
            file_url = await StorageService.upload_file(file_key, pdf_bytes)

            # 3. Call LLM for parsing structured JSON
            system_prompt = (
                "You are an expert ATS (Applicant Tracking System) parse assistant. "
                "Your job is to read candidate raw resume text and extract all details in JSON format strictly matching the schema. "
                "Structure fields for education: [institution_name, degree, field_of_study, cgpa, percentage, start_year, end_year, is_current]. "
                "Structure fields for experience: [company_name, role_title, start_date (YYYY-MM-DD), end_date (YYYY-MM-DD), is_current, description, skills_used (array)]. "
                "Structure fields for projects: [project_name, description, tech_stack (array), project_url, github_url, start_date, end_date]. "
                "Classify resume_type into: [SOFTWARE, AI_ML, CORE_ENGINEERING, RESEARCH, GENERALIST]. "
                "Output ONLY a raw valid JSON object. No Markdown code fences, no explanations."
            )
            
            prompt = f"Resume text to parse:\n\n{raw_text}"
            analysis_status = "success"
            warning = None

            try:
                # self.think() always returns a str — LLM router handles fallback internally
                llm_response = await self.think(
                    prompt,
                    system_prompt,
                    model=settings.OLLAMA_DEFAULT_MODEL,
                    response_model=ResumeStructure
                )

                # Strip LLM code fence markers if present
                clean_json = llm_response.strip().replace("```json", "").replace("```", "").strip()
                await self.log_info(f"LLM response length: {len(clean_json)} chars")
                parsed_data = json.loads(clean_json)

                # ── Hybrid Extraction Merging ────────────────────────────────────
                deterministic_data = parse_resume_deterministic(raw_text)
                
                merged_data = {}
                def is_empty_val(v):
                    if v is None:
                        return True
                    if isinstance(v, str) and (v.strip() == "" or v.strip().upper() in ["N/A", "NONE", "NULL"]):
                        return True
                    if isinstance(v, list) and len(v) == 0:
                        return True
                    return False

                # Merge scalars (full_name, email, phone, summary, linkedin_url, github_url, resume_type)
                for key in ["full_name", "email", "phone", "summary", "linkedin_url", "github_url", "resume_type"]:
                    llm_val = parsed_data.get(key)
                    det_val = deterministic_data.get(key)
                    if is_empty_val(llm_val) and not is_empty_val(det_val):
                        merged_data[key] = det_val
                    else:
                        merged_data[key] = llm_val if llm_val is not None else det_val

                # Merge arrays (skills, education, experience, projects, achievements)
                for key in ["skills", "education", "experience", "projects", "achievements"]:
                    llm_val = parsed_data.get(key, [])
                    det_val = deterministic_data.get(key, [])
                    
                    llm_empty = False
                    if not llm_val:
                        llm_empty = True
                    elif isinstance(llm_val, list):
                        if all(isinstance(x, str) and is_empty_val(x) for x in llm_val):
                            llm_empty = True
                        elif all(isinstance(x, dict) and all(is_empty_val(val) for val in x.values()) for x in llm_val):
                            llm_empty = True
                    
                    if llm_empty and det_val:
                        merged_data[key] = det_val
                    else:
                        merged_data[key] = llm_val
                
                # Recompute summary and resume_type strictly from the merged fields of the current resume
                from app.utils.resume_parser import generate_professional_summary, detect_resume_type
                merged_data["summary"] = generate_professional_summary(
                    merged_data.get("skills", []),
                    merged_data.get("experience", []),
                    merged_data.get("projects", [])
                )
                merged_data["resume_type"] = detect_resume_type(
                    merged_data.get("skills", []),
                    merged_data.get("projects", [])
                )
                
                parsed_data = merged_data

            except Exception as e:
                analysis_status = "failed"
                warning = "AI analysis temporarily unavailable. Resume stored successfully."
                await self.log_info(f"AI parsing failed, falling back to rule-based parser. Detail: {e}")
                logger.warning(f"AI parsing failed, falling back to rule-based parser: {e}", exc_info=True)
                parsed_data = parse_resume_deterministic(raw_text)

            # ── Debug Logging ────────────────────────────────────────────────
            print("RAW_TEXT_START")
            print(raw_text[:2000])
            print("RAW_TEXT_END")
            logger.info("RAW_TEXT_START")
            logger.info(raw_text[:2000])
            logger.info("RAW_TEXT_END")

            print("EXTRACTED_JSON")
            print(json.dumps(parsed_data, indent=2))
            logger.info(f"EXTRACTED_JSON: {json.dumps(parsed_data, indent=2)}")

            # 4. Generate text embedding
            await self.log_info("Generating semantic embedding for text matching...")
            embedding = get_embedding(raw_text)

            # 5. Save details back to Database
            stmt = select(Resume).where(Resume.id == resume_db_id)
            result = await self.db.execute(stmt)
            resume = result.scalars().first()
            
            if resume:
                resume.resume_type = parsed_data.get("resume_type", "GENERALIST")
                resume.file_key = file_key
                resume.file_url = file_url
                resume.file_size_bytes = len(pdf_bytes)
                resume.original_filename = filename
                resume.parsed_text = raw_text
                resume.parsed_json = parsed_data
                resume.skills_extracted = parsed_data.get("skills", [])
                resume.embedding = embedding
                resume.last_parsed_at = datetime.utcnow()  # noqa: DTZ003
                self.db.add(resume)
                await self.db.commit()

            # Create individual resume sections
            for sec_type in ["education", "experience", "skills", "projects", "achievements"]:
                sec_content = parsed_data.get(sec_type, [])
                if sec_content:
                    sec_record = ResumeSection(
                        resume_id=resume_db_id,
                        section_type=sec_type.upper(),
                        section_title=sec_type.capitalize(),
                        content=str(sec_content),
                        structured_data={"items": sec_content}
                    )
                    self.db.add(sec_record)
            await self.db.commit()

            # 6. Bootstrap profile tables to save candidate manual entry effort
            await self.log_info("Bootstrapping candidate profile collections from parsed resume data...")
            await self._bootstrap_profile(u_id, parsed_data)

            # 7. Sync to Qdrant collection "resumes"
            await self.log_info("Registering resume vector to Qdrant index...")
            qdrant_client.upsert_vector(
                collection_name="resumes",
                point_id=str(resume_db_id),
                vector=embedding,
                payload={
                    "user_id": str(self.user_id),
                    "resume_id": str(resume_db_id),
                    "resume_type": parsed_data.get("resume_type", "GENERALIST"),
                    "skills": parsed_data.get("skills", [])
                }
            )

            # 8. Emit notification event
            await self.emit_event("RESUME_PARSED", {"resume_id": str(resume_db_id), "type": parsed_data.get("resume_type")})
            await self.log_info("Resume parsed and synced successfully.")
            
            result = AgentResult(
                success=True,
                output_data={
                    "resume_id": str(resume_db_id),
                    "type": parsed_data.get("resume_type"),
                    "analysis_status": analysis_status,
                    "warning": warning
                }
            )
            await self.finalize_run(result)
            return result

        except Exception as e:
            tb = traceback.format_exc()
            await self.log_error(f"Resume parsing failed: {type(e).__name__}: {e}\n{tb}")
            logger.error("Full resume parsing traceback:", exc_info=True)
            result = AgentResult(
                success=False,
                error_message=f"Resume parsing failed: {type(e).__name__}: {e}"
            )
            await self.finalize_run(result)
            return result

    async def _bootstrap_profile(self, user_id: UUID, parsed_data: Dict[str, Any]) -> None:
        """Autofill profile sections from parsed resume details in a true upsert, non-destructive manner."""
        try:
            from app.models.profile import CandidateProfile
            from app.models.auth import User
            from datetime import date
            import re
            
            # Helper logic
            def normalize(s: Any) -> str:
                if not s or not isinstance(s, str):
                    return ""
                return re.sub(r'[\s\W_]+', '', s).strip().lower()

            def is_db_field_empty(val) -> bool:
                if val is None:
                    return True
                if isinstance(val, str) and (val.strip() == "" or val.strip().upper() in ["N/A", "NONE", "NULL"]):
                    return True
                return False

            def parse_achievement_string(ach_str: str) -> dict:
                from datetime import datetime
                year_match = re.search(r'\b(19\d{2}|20\d{2})\b', ach_str)
                year = int(year_match.group(1)) if year_match else datetime.now().year
                
                title = ach_str
                description = ach_str
                
                if "JEE Mains" in ach_str or "JEE" in ach_str:
                    title = "JEE Mains 2022" if "2022" in ach_str else "JEE Mains"
                    description = ach_str
                elif "Foundation for Excellence" in ach_str:
                    title = "Foundation for Excellence Scholarship"
                    description = ach_str
                elif "Zama" in ach_str:
                    title = "Zama Volunteer"
                    description = ach_str
                else:
                    words = ach_str.split()
                    if len(words) > 4:
                        title = " ".join(words[:4])
                    else:
                        title = ach_str
                return {"title": title, "description": description, "year": year}

            # Fetch existing records from DB to merge
            existing_edu_res = await self.db.execute(select(Education).where(Education.user_id == user_id))
            existing_edu_list = list(existing_edu_res.scalars().all())

            existing_exp_res = await self.db.execute(select(Experience).where(Experience.user_id == user_id))
            existing_exp_list = list(existing_exp_res.scalars().all())

            existing_proj_res = await self.db.execute(select(Project).where(Project.user_id == user_id))
            existing_proj_list = list(existing_proj_res.scalars().all())

            existing_ach_res = await self.db.execute(select(Achievement).where(Achievement.user_id == user_id))
            existing_ach_list = list(existing_ach_res.scalars().all())

            # Now fetch the remaining skills (Do NOT delete anything)
            existing_skills_res = await self.db.execute(select(ProfileSkill).where(ProfileSkill.user_id == user_id))
            existing_skills_list = list(existing_skills_res.scalars().all())
            existing_skill_names = {normalize(s.skill_name) for s in existing_skills_list if s.skill_name}

            # Setup stats logs counters
            edu_counts = {"found": 0, "updated": 0, "inserted": 0, "skipped": 0}
            exp_counts = {"found": 0, "updated": 0, "inserted": 0, "skipped": 0}
            proj_counts = {"found": 0, "updated": 0, "inserted": 0, "skipped": 0}
            skill_counts = {"found": 0, "inserted": 0, "skipped": 0}
            ach_counts = {"found": 0, "inserted": 0, "skipped": 0}

            # 0. Populate CandidateProfile (summary, social urls, years of experience)
            stmt = select(CandidateProfile).where(CandidateProfile.user_id == user_id)
            res = await self.db.execute(stmt)
            profile = res.scalars().first()
            if not profile:
                profile = CandidateProfile(user_id=user_id)
                self.db.add(profile)
                await self.db.flush()
                
            if parsed_data.get("summary") and parsed_data["summary"] != "N/A":
                profile.profile_summary = parsed_data["summary"]
            if parsed_data.get("linkedin_url") and parsed_data["linkedin_url"] != "N/A":
                profile.linkedin_url = parsed_data["linkedin_url"]
            if parsed_data.get("github_url") and parsed_data["github_url"] != "N/A":
                profile.github_url = parsed_data["github_url"]
                
            # Calculate years of experience from experience history
            total_months = 0
            for exp in parsed_data.get("experience", []):
                start_yr = exp.get("start_year")
                start_mth = exp.get("start_month") or 1
                end_yr = exp.get("end_year")
                end_mth = exp.get("end_month") or 1
                is_curr = exp.get("is_current", False)
                
                if start_yr:
                    if is_curr:
                        import datetime
                        now = datetime.datetime.now()
                        end_yr = now.year
                        end_mth = now.month
                    
                    if end_yr:
                        months = (end_yr - start_yr) * 12 + (end_mth - start_mth)
                        if months > 0:
                            total_months += months
            
            years_of_exp = round(total_months / 12.0, 1)
            profile.years_of_experience = max(0.0, years_of_exp)
            self.db.add(profile)
            
            # Update user's full name and phone in the auth.users table
            if parsed_data.get("full_name") and parsed_data["full_name"] != "N/A":
                user_stmt = select(User).where(User.id == user_id)
                user_res = await self.db.execute(user_stmt)
                user_record = user_res.scalars().first()
                if user_record:
                    user_record.full_name = parsed_data["full_name"]
                    if parsed_data.get("phone") and parsed_data["phone"] != "N/A":
                        user_record.phone = parsed_data["phone"]
                    self.db.add(user_record)
            
            # 1. Merge Education
            for edu_item in parsed_data.get("education", []):
                inst_norm = normalize(edu_item.get("institution_name"))
                deg_norm = normalize(edu_item.get("degree"))
                
                match_edu = None
                for existing_edu in existing_edu_list:
                    if normalize(existing_edu.institution_name) == inst_norm and normalize(existing_edu.degree) == deg_norm:
                        match_edu = existing_edu
                        break
                        
                if match_edu:
                    edu_counts["found"] += 1
                    updated_any = False
                    
                    if is_db_field_empty(match_edu.field_of_study) and edu_item.get("field_of_study"):
                        match_edu.field_of_study = edu_item.get("field_of_study")
                        updated_any = True
                    if match_edu.cgpa is None and edu_item.get("cgpa") is not None:
                        match_edu.cgpa = edu_item.get("cgpa")
                        updated_any = True
                    if match_edu.percentage is None and edu_item.get("percentage") is not None:
                        match_edu.percentage = edu_item.get("percentage")
                        updated_any = True
                    if match_edu.start_year is None and edu_item.get("start_year") is not None:
                        match_edu.start_year = edu_item.get("start_year")
                        updated_any = True
                    if match_edu.end_year is None and edu_item.get("end_year") is not None:
                        match_edu.end_year = edu_item.get("end_year")
                        updated_any = True
                    if match_edu.is_current is None and edu_item.get("is_current") is not None:
                        match_edu.is_current = edu_item.get("is_current", False)
                        updated_any = True
                        
                    if updated_any:
                        edu_counts["updated"] += 1
                        self.db.add(match_edu)
                    else:
                        edu_counts["skipped"] += 1
                else:
                    edu_rec = Education(
                        user_id=user_id,
                        institution_name=edu_item.get("institution_name", "Unknown College"),
                        degree=edu_item.get("degree"),
                        field_of_study=edu_item.get("field_of_study"),
                        cgpa=edu_item.get("cgpa"),
                        percentage=edu_item.get("percentage"),
                        start_year=edu_item.get("start_year"),
                        end_year=edu_item.get("end_year"),
                        is_current=edu_item.get("is_current", False)
                    )
                    self.db.add(edu_rec)
                    edu_counts["inserted"] += 1

            # 2. Merge Experience
            for exp_item in parsed_data.get("experience", []):
                comp_norm = normalize(exp_item.get("company_name"))
                role_norm = normalize(exp_item.get("role_title"))
                
                match_exp = None
                for existing_exp in existing_exp_list:
                    if normalize(existing_exp.company_name) == comp_norm and normalize(existing_exp.role_title) == role_norm:
                        match_exp = existing_exp
                        break
                        
                if match_exp:
                    exp_counts["found"] += 1
                    updated_any = False
                    
                    if is_db_field_empty(match_exp.description) and exp_item.get("description"):
                        match_exp.description = exp_item.get("description")
                        updated_any = True
                    if is_db_field_empty(match_exp.employment_type) and exp_item.get("employment_type"):
                        match_exp.employment_type = exp_item.get("employment_type")
                        updated_any = True
                    if is_db_field_empty(match_exp.location) and exp_item.get("location"):
                        match_exp.location = exp_item.get("location")
                        updated_any = True
                        
                    parsed_skills = exp_item.get("skills_used", [])
                    if parsed_skills:
                        current_skills = list(match_exp.skills_used or [])
                        added_skills = False
                        for s in parsed_skills:
                            if s not in current_skills:
                                current_skills.append(s)
                                added_skills = True
                        if added_skills:
                            match_exp.skills_used = current_skills
                            updated_any = True
                            
                    if exp_item.get("is_current") is not None and match_exp.is_current != exp_item.get("is_current"):
                        match_exp.is_current = exp_item.get("is_current", False)
                        updated_any = True
                        
                    if updated_any:
                        exp_counts["updated"] += 1
                        self.db.add(match_exp)
                    else:
                        exp_counts["skipped"] += 1
                else:
                    # Parse start/end dates if available
                    start_date_obj = None
                    end_date_obj = None
                    if exp_item.get("start_year"):
                        start_date_obj = date(exp_item.get("start_year"), exp_item.get("start_month") or 1, 1)
                    if exp_item.get("end_year"):
                        end_date_obj = date(exp_item.get("end_year"), exp_item.get("end_month") or 1, 1)
                        
                    exp_rec = Experience(
                        user_id=user_id,
                        company_name=exp_item.get("company_name", "Unknown Company"),
                        role_title=exp_item.get("role_title", "Software Developer"),
                        employment_type=exp_item.get("employment_type"),
                        location=exp_item.get("location"),
                        start_date=start_date_obj,
                        end_date=end_date_obj,
                        description=exp_item.get("description"),
                        skills_used=exp_item.get("skills_used", []),
                        is_current=exp_item.get("is_current", False)
                    )
                    self.db.add(exp_rec)
                    exp_counts["inserted"] += 1

            # 3. Populate Skills
            from app.utils.resume_parser import get_skill_category, normalize_skill_name, CATEGORY_DISPLAY_MAP
            for skill_name in parsed_data.get("skills", []):
                display_name = normalize_skill_name(skill_name)
                skill_norm = normalize(display_name)
                if skill_norm:
                    if skill_norm in existing_skill_names:
                        skill_counts["found"] += 1
                        skill_counts["skipped"] += 1
                    else:
                        cat_key = get_skill_category(display_name)
                        cat = CATEGORY_DISPLAY_MAP.get(cat_key, "Other")
                        skill_rec = ProfileSkill(
                            user_id=user_id,
                            skill_name=display_name,
                            category=cat,
                            proficiency_level="INTERMEDIATE",
                            source="RESUME_PARSING"
                        )
                        self.db.add(skill_rec)
                        existing_skill_names.add(skill_norm)
                        skill_counts["inserted"] += 1

            # 4. Merge Projects
            for proj_item in parsed_data.get("projects", []):
                proj_norm = normalize(proj_item.get("project_name"))
                
                match_proj = None
                for existing_proj in existing_proj_list:
                    if normalize(existing_proj.project_name) == proj_norm:
                        match_proj = existing_proj
                        break
                        
                if match_proj:
                    proj_counts["found"] += 1
                    updated_any = False
                    
                    # Merge descriptions (combining distinct text lines)
                    existing_desc = match_proj.description or ""
                    parsed_desc = proj_item.get("description") or ""
                    
                    lines_existing = [l.strip() for l in existing_desc.split("\n") if l.strip()]
                    lines_parsed = [l.strip() for l in parsed_desc.split("\n") if l.strip()]
                    
                    merged_lines = list(lines_existing)
                    added_desc = False
                    for l in lines_parsed:
                        if l not in merged_lines:
                            merged_lines.append(l)
                            added_desc = True
                            
                    if added_desc:
                        match_proj.description = "\n".join(merged_lines)
                        updated_any = True
                        
                    # Merge technologies
                    parsed_stack = proj_item.get("tech_stack", [])
                    if parsed_stack:
                        current_stack = list(match_proj.tech_stack or [])
                        added_tech = False
                        for t in parsed_stack:
                            if normalize(t) not in {normalize(x) for x in current_stack}:
                                current_stack.append(t)
                                added_tech = True
                        if added_tech:
                            match_proj.tech_stack = current_stack
                            updated_any = True
                            
                    # Fill missing URLs
                    if is_db_field_empty(match_proj.project_url) and proj_item.get("project_url"):
                        match_proj.project_url = proj_item.get("project_url")
                        updated_any = True
                    if is_db_field_empty(match_proj.github_url) and proj_item.get("github_url"):
                        match_proj.github_url = proj_item.get("github_url")
                        updated_any = True
                        
                    if updated_any:
                        proj_counts["updated"] += 1
                        self.db.add(match_proj)
                    else:
                        proj_counts["skipped"] += 1
                else:
                    proj_rec = Project(
                        user_id=user_id,
                        project_name=proj_item.get("project_name", "Personal Project"),
                        description=proj_item.get("description"),
                        tech_stack=proj_item.get("tech_stack", []),
                        project_url=proj_item.get("project_url"),
                        github_url=proj_item.get("github_url")
                    )
                    self.db.add(proj_rec)
                    proj_counts["inserted"] += 1

            # 5. Merge Achievements
            for ach_title in parsed_data.get("achievements", []):
                ach_parsed = parse_achievement_string(ach_title)
                ach_norm = normalize(ach_parsed["title"])
                
                match_ach = None
                for existing_ach in existing_ach_list:
                    if normalize(existing_ach.title) == ach_norm:
                        match_ach = existing_ach
                        break
                        
                if match_ach:
                    ach_counts["found"] += 1
                    ach_counts["skipped"] += 1
                else:
                    ach_rec = Achievement(
                        user_id=user_id,
                        achievement_type="AWARD",
                        title=ach_parsed["title"],
                        description=ach_parsed["description"],
                        date_achieved=date(ach_parsed["year"], 1, 1)
                    )
                    self.db.add(ach_rec)
                    ach_counts["inserted"] += 1

            # Save everything
            await self.db.commit()
            
            # Print detailed stats logs for Phase 1
            logger.info(f"Education merge stats: found={edu_counts['found']}, updated={edu_counts['updated']}, inserted={edu_counts['inserted']}, skipped={edu_counts['skipped']}")
            logger.info(f"Experience merge stats: found={exp_counts['found']}, updated={exp_counts['updated']}, inserted={exp_counts['inserted']}, skipped={exp_counts['skipped']}")
            logger.info(f"Projects merge stats: found={proj_counts['found']}, updated={proj_counts['updated']}, inserted={proj_counts['inserted']}, skipped={proj_counts['skipped']}")
            logger.info(f"Skills merge stats: found={skill_counts['found']}, inserted={skill_counts['inserted']}, skipped={skill_counts['skipped']}")
            logger.info(f"Achievements merge stats: found={ach_counts['found']}, inserted={ach_counts['inserted']}, skipped={ach_counts['skipped']}")
            
            await self.log_info(f"Education merge stats: found={edu_counts['found']}, updated={edu_counts['updated']}, inserted={edu_counts['inserted']}, skipped={edu_counts['skipped']}")
            await self.log_info(f"Experience merge stats: found={exp_counts['found']}, updated={exp_counts['updated']}, inserted={exp_counts['inserted']}, skipped={exp_counts['skipped']}")
            await self.log_info(f"Projects merge stats: found={proj_counts['found']}, updated={proj_counts['updated']}, inserted={proj_counts['inserted']}, skipped={proj_counts['skipped']}")
            await self.log_info(f"Skills merge stats: found={skill_counts['found']}, inserted={skill_counts['inserted']}, skipped={skill_counts['skipped']}")
            await self.log_info(f"Achievements merge stats: found={ach_counts['found']}, inserted={ach_counts['inserted']}, skipped={ach_counts['skipped']}")

            # Trigger Candidate completeness update
            from app.services.profile_service import ProfileService
            await ProfileService.update_completeness_score(self.db, user_id)
        except Exception as e:
            logger.error(f"Skipping profile bootstrap details: {e}", exc_info=True)
            await self.db.rollback()
