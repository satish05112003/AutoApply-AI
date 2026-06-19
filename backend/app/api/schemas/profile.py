from datetime import date, datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field

# --- Education ---
class EducationBase(BaseModel):
    institution_name: str = Field(..., min_length=2, max_length=255)
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    cgpa: Optional[float] = None
    percentage: Optional[float] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    is_current: Optional[bool] = False
    education_type: Optional[str] = None # HIGH_SCHOOL, BTECH, MTECH, PHD, etc.

class EducationCreate(EducationBase):
    pass

class EducationResponse(EducationBase):
    id: UUID
    user_id: UUID

    class Config:
        from_attributes = True

# --- Experience ---
class ExperienceBase(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=255)
    role_title: str = Field(..., min_length=2, max_length=255)
    employment_type: Optional[str] = None # FULL_TIME, INTERNSHIP, etc.
    location: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_current: Optional[bool] = False
    description: Optional[str] = None
    skills_used: Optional[List[str]] = []

class ExperienceCreate(ExperienceBase):
    pass

class ExperienceResponse(ExperienceBase):
    id: UUID
    user_id: UUID

    class Config:
        from_attributes = True

# --- Skills ---
class SkillCreate(BaseModel):
    skill_name: str = Field(..., min_length=1, max_length=100)
    category: Optional[str] = None
    proficiency_level: Optional[str] = None # BEGINNER, INTERMEDIATE, ADVANCED
    years_of_experience: Optional[float] = None
    is_primary: Optional[bool] = False

class SkillResponse(SkillCreate):
    id: UUID
    user_id: UUID
    source: str
    created_at: datetime

    class Config:
        from_attributes = True

# --- Projects ---
class ProjectBase(BaseModel):
    project_name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    tech_stack: Optional[List[str]] = []
    project_url: Optional[str] = None
    github_url: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_featured: Optional[bool] = False

class ProjectCreate(ProjectBase):
    pass

class ProjectResponse(ProjectBase):
    id: UUID
    user_id: UUID

    class Config:
        from_attributes = True

# --- Achievements ---
class AchievementCreate(BaseModel):
    achievement_type: str = Field(..., min_length=2, max_length=50)
    title: str = Field(..., min_length=2, max_length=255)
    issuer: Optional[str] = None
    date_achieved: Optional[date] = None
    description: Optional[str] = None
    url: Optional[str] = None

class AchievementResponse(AchievementCreate):
    id: UUID
    user_id: UUID

    class Config:
        from_attributes = True

# --- Preferences ---
class PreferencesBase(BaseModel):
    preferred_roles: Optional[List[str]] = []
    preferred_locations: Optional[List[str]] = []
    preferred_companies: Optional[List[str]] = []
    blacklisted_companies: Optional[List[str]] = []
    blacklisted_keywords: Optional[List[str]] = []
    min_salary_inr: Optional[int] = None
    max_salary_inr: Optional[int] = None
    preferred_salary_inr: Optional[int] = None
    min_stipend_inr: Optional[int] = None
    preferred_stipend_inr: Optional[int] = None
    remote_preference: Optional[str] = "HYBRID" # REMOTE, ONSITE, HYBRID
    work_type_preference: Optional[List[str]] = ["FULL_TIME"]
    experience_level: Optional[str] = "FRESHER" # FRESHER, JUNIOR, MID, SENIOR
    preferred_industries: Optional[List[str]] = []
    required_skills: Optional[List[str]] = []
    min_match_score: Optional[int] = 60
    auto_apply_threshold: Optional[int] = 75
    max_applications_per_day: Optional[int] = 20
    max_applications_per_hour: Optional[int] = 10
    preferred_sources: Optional[List[str]] = []
    notice_period_days: Optional[int] = 0
    work_authorization: Optional[str] = "INDIA_CITIZEN"
    gmail_app_password: Optional[str] = None
    email_monitoring_enabled: Optional[bool] = False

class PreferencesUpdate(PreferencesBase):
    pass

class PreferencesResponse(PreferencesBase):
    id: UUID
    user_id: UUID
    updated_at: datetime

    class Config:
        from_attributes = True

# --- Candidate Profile ---
class CandidateProfileUpdate(BaseModel):
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    address_city: Optional[str] = None
    address_state: Optional[str] = None
    address_country: Optional[str] = "India"
    years_of_experience: Optional[float] = None
    current_company: Optional[str] = None
    current_role: Optional[str] = None
    current_salary_inr: Optional[int] = None
    profile_summary: Optional[str] = None

class CandidateProfileResponse(BaseModel):
    id: UUID
    user_id: UUID
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    address_city: Optional[str] = None
    address_state: Optional[str] = None
    address_country: str
    years_of_experience: Optional[float] = None
    current_company: Optional[str] = None
    current_role: Optional[str] = None
    current_salary_inr: Optional[int] = None
    profile_summary: Optional[str] = None
    profile_completeness_score: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ProfileCompletenessResponse(BaseModel):
    score: int
    missing_sections: List[str]

# --- Resume ---
class ResumeResponse(BaseModel):
    id: UUID
    user_id: UUID
    resume_name: str
    resume_type: str
    file_key: str
    file_url: Optional[str] = None
    file_size_bytes: Optional[int] = None
    original_filename: Optional[str] = None
    parsed_text: Optional[str] = None
    parsed_json: Optional[dict] = None
    skills_extracted: Optional[List[str]] = []
    is_active: bool
    is_primary: bool
    use_count: int
    last_used_at: Optional[datetime] = None
    upload_at: datetime
    last_parsed_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# --- Update Schemas (Optional Fields) ---
class EducationUpdate(BaseModel):
    institution_name: Optional[str] = Field(None, min_length=2, max_length=255)
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    cgpa: Optional[float] = None
    percentage: Optional[float] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    is_current: Optional[bool] = None
    education_type: Optional[str] = None

class ExperienceUpdate(BaseModel):
    company_name: Optional[str] = Field(None, min_length=2, max_length=255)
    role_title: Optional[str] = Field(None, min_length=2, max_length=255)
    employment_type: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_current: Optional[bool] = None
    description: Optional[str] = None
    skills_used: Optional[List[str]] = []

class SkillUpdate(BaseModel):
    skill_name: Optional[str] = Field(None, min_length=1, max_length=100)
    category: Optional[str] = None
    proficiency_level: Optional[str] = None
    years_of_experience: Optional[float] = None
    is_primary: Optional[bool] = None

class ProjectUpdate(BaseModel):
    project_name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = None
    tech_stack: Optional[List[str]] = []
    project_url: Optional[str] = None
    github_url: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_featured: Optional[bool] = None

class AchievementUpdate(BaseModel):
    achievement_type: Optional[str] = Field(None, min_length=2, max_length=50)
    title: Optional[str] = Field(None, min_length=2, max_length=255)
    issuer: Optional[str] = None
    date_achieved: Optional[date] = None
    description: Optional[str] = None
    url: Optional[str] = None

