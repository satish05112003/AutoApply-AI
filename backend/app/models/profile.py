import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship
from app.database import Base

class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"
    __table_args__ = {"schema": "profile"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False, unique=True)
    linkedin_url = Column(String(500), nullable=True)
    github_url = Column(String(500), nullable=True)
    portfolio_url = Column(String(500), nullable=True)
    address_city = Column(String(100), nullable=True)
    address_state = Column(String(100), nullable=True)
    address_country = Column(String(100), default="India")
    years_of_experience = Column(Numeric(4, 1), nullable=True)
    current_company = Column(String(255), nullable=True)
    current_role = Column(String(255), nullable=True)
    current_salary_inr = Column(Integer, nullable=True)
    profile_summary = Column(Text, nullable=True)
    profile_embedding = Column(ARRAY(Numeric), nullable=True)
    profile_completeness_score = Column(Integer, default=0)
    last_embedding_update = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="candidate_profile")

class Education(Base):
    __tablename__ = "education"
    __table_args__ = {"schema": "profile"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    institution_name = Column(String(255), nullable=False)
    degree = Column(String(100), nullable=True)
    field_of_study = Column(String(100), nullable=True)
    cgpa = Column(Numeric(4, 2), nullable=True)
    percentage = Column(Numeric(5, 2), nullable=True)
    start_year = Column(Integer, nullable=True)
    end_year = Column(Integer, nullable=True)
    is_current = Column(Boolean, default=False)
    education_type = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="education")

class Experience(Base):
    __tablename__ = "experience"
    __table_args__ = {"schema": "profile"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    company_name = Column(String(255), nullable=False)
    role_title = Column(String(255), nullable=False)
    employment_type = Column(String(50), nullable=True)
    location = Column(String(255), nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    is_current = Column(Boolean, default=False)
    description = Column(Text, nullable=True)
    skills_used = Column(ARRAY(Text), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="experience")

class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("user_id", "skill_name", name="uq_skills_user_skill"),
        {"schema": "profile"}
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    skill_name = Column(String(100), nullable=False)
    category = Column(String(50), nullable=True)
    proficiency_level = Column(String(20), nullable=True)
    years_of_experience = Column(Numeric(4, 1), nullable=True)
    is_primary = Column(Boolean, default=False)
    source = Column(String(50), default="MANUAL")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="skills")

class Project(Base):
    __tablename__ = "projects"
    __table_args__ = {"schema": "profile"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    project_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    tech_stack = Column(ARRAY(Text), nullable=True)
    project_url = Column(String(500), nullable=True)
    github_url = Column(String(500), nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    is_featured = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="projects")

class Achievement(Base):
    __tablename__ = "achievements"
    __table_args__ = {"schema": "profile"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    achievement_type = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    issuer = Column(String(255), nullable=True)
    date_achieved = Column(Date, nullable=True)
    description = Column(Text, nullable=True)
    url = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="achievements")

class Preferences(Base):
    __tablename__ = "preferences"
    __table_args__ = {"schema": "profile"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False, unique=True)
    preferred_roles = Column(ARRAY(Text), default=[])
    preferred_locations = Column(ARRAY(Text), default=[])
    preferred_companies = Column(ARRAY(Text), default=[])
    blacklisted_companies = Column(ARRAY(Text), default=[])
    blacklisted_keywords = Column(ARRAY(Text), default=[])
    min_salary_inr = Column(Integer, nullable=True)
    max_salary_inr = Column(Integer, nullable=True)
    preferred_salary_inr = Column(Integer, nullable=True)
    min_stipend_inr = Column(Integer, nullable=True)
    preferred_stipend_inr = Column(Integer, nullable=True)
    remote_preference = Column(String(20), default="HYBRID")
    work_type_preference = Column(ARRAY(Text), default=["FULL_TIME"])
    experience_level = Column(String(20), default="FRESHER")
    preferred_industries = Column(ARRAY(Text), default=[])
    required_skills = Column(ARRAY(Text), default=[])
    min_match_score = Column(Integer, default=60)
    auto_apply_threshold = Column(Integer, default=75)
    max_applications_per_day = Column(Integer, default=20)
    max_applications_per_hour = Column(Integer, default=10)
    preferred_sources = Column(ARRAY(Text), default=[])
    notice_period_days = Column(Integer, default=0)
    work_authorization = Column(String(50), default="INDIA_CITIZEN")
    gmail_app_password = Column(String(255), nullable=True)
    email_monitoring_enabled = Column(Boolean, default=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="preferences")

class Resume(Base):
    __tablename__ = "resumes"
    __table_args__ = {"schema": "profile"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False)
    resume_name = Column(String(255), nullable=False)
    resume_type = Column(String(50), nullable=False)
    file_key = Column(String(500), nullable=False)
    file_url = Column(String(1000), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    original_filename = Column(String(255), nullable=True)
    parsed_text = Column(Text, nullable=True)
    parsed_json = Column(JSONB, nullable=True)
    skills_extracted = Column(ARRAY(Text), nullable=True)
    embedding = Column(ARRAY(Numeric), nullable=True)
    is_active = Column(Boolean, default=True)
    is_primary = Column(Boolean, default=False)
    use_count = Column(Integer, default=0)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    upload_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    last_parsed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="resumes")
    sections = relationship("ResumeSection", back_populates="resume", cascade="all, delete-orphan")

class ResumeSection(Base):
    __tablename__ = "resume_sections"
    __table_args__ = {"schema": "profile"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resume_id = Column(UUID(as_uuid=True), ForeignKey("profile.resumes.id", ondelete="CASCADE"), nullable=False)
    section_type = Column(String(50), nullable=False)
    section_title = Column(String(255), nullable=True)
    content = Column(Text, nullable=True)
    structured_data = Column(JSONB, nullable=True)
    sequence_order = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationships
    resume = relationship("Resume", back_populates="sections")
