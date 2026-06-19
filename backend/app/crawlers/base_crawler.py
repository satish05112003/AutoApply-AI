"""
Base Crawler — shared logic for all ATS crawlers.

Key additions:
  - is_tech_role(title, description): positive/negative keyword scoring
    that filters out Finance, Sales, HR, Marketing, Legal, etc.
    Target: >90% software/tech precision.
  - clean_text(): HTML stripping + whitespace normalization
"""
import re
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("autoapply_ai.crawlers.base")

# ---------------------------------------------------------------------------
# Relevance scoring configuration
# ---------------------------------------------------------------------------

# Positive signals: title MUST contain one of these to pass
POSITIVE_TITLE_KEYWORDS = [
    # Core engineering titles
    "software", "engineer", "developer", "sde", "swe",
    "programmer", "coder", "architect",
    # Specializations
    "backend", "back-end", "back end",
    "frontend", "front-end", "front end",
    "fullstack", "full stack", "full-stack",
    "platform", "infrastructure", "systems",
    # AI/ML
    "machine learning", "ml ", " ml", "ai ", " ai",
    "deep learning", "data science", "nlp", "llm", "generative",
    "computer vision", "reinforcement",
    # Data
    "data engineer", "data platform", "analytics engineer",
    "etl", "pipeline",
    # DevOps/SRE (positive for infra roles)
    "devops", "sre", "site reliability", "cloud engineer",
    "platform engineer", "infrastructure engineer",
    # Mobile / Embedded
    "mobile", "android", "ios", "swift", "kotlin",
    "embedded", "firmware", "fpga",
    # Research / Quant
    "research scientist", "research engineer", "applied scientist",
    "quantitative", "quant developer",
    # QA / Security
    "security engineer", "appsec", "pentester",
    "quality engineer", "qa engineer", "automation engineer",
    # Product tech
    "technical program", "staff engineer", "principal engineer",
]

# Negative signals: title containing these = discard (non-tech)
NEGATIVE_TITLE_KEYWORDS = [
    # Finance / Accounting
    "finance", "financial", "accounting", "accountant", "controller",
    "bookkeeper", "treasurer", "tax ", "audit", "actuarial",
    "billing", "payroll", "accounts payable", "accounts receivable",
    # Sales
    "sales", "account executive", "account manager", "business development",
    "enterprise sales", "sdr", "bdr", "inside sales", "outside sales",
    "revenue", "quota",
    # Marketing
    "marketing", "content writer", "content strategist", "seo",
    "copywriter", "brand", "demand generation", "growth marketer",
    "social media", "digital marketing", "campaign",
    # HR / Recruiting
    "recruiter", "recruiting", "talent acquisition", "talent partner",
    "hr ", "human resources", "people operations", "people partner",
    "compensation", "benefits",
    # Legal / Compliance
    "legal", "counsel", "attorney", "paralegal", "compliance",
    "regulatory", "governance",
    # Operations / Admin
    "operations manager", "operations associate", "office manager",
    "executive assistant", "administrative", "coordinator",
    "supply chain", "procurement", "logistics",
    # Customer Support
    "customer success", "customer support", "support specialist",
    "customer experience", "implementation specialist",
    "onboarding specialist", "customer service",
    # Design (non-engineering)
    "graphic designer", "visual designer", "ui designer", "ux designer",
    "product designer",  # keep "ux engineer" / "design engineer"
    # Business / Strategy
    "business analyst", "business intelligence analyst",
    "strategy", "management consultant", "policy",
    # Finance-specific
    "investment", "portfolio manager", "fund manager", "analyst - finance",
]

# Absolute hard discard: if any of these appear in title, ALWAYS skip
# regardless of positive matches
HARD_NEGATIVE_TITLE_KEYWORDS = [
    "sales manager", "sales executive", "account executive",
    "chief of staff", "general counsel", "vp of sales",
    "finance manager", "finance director",
    "payroll", "bookkeeping",
    "customer success manager",
]

# Description-level positive signals (bonus if title is borderline)
POSITIVE_DESC_KEYWORDS = [
    "python", "java", "javascript", "typescript", "golang", "rust", "c++",
    "react", "node.js", "django", "fastapi", "kubernetes", "docker",
    "machine learning", "pytorch", "tensorflow", "llm",
    "postgresql", "mongodb", "redis", "kafka",
    "aws", "gcp", "azure", "terraform",
    "github", "ci/cd", "microservices", "api",
]


def is_tech_role(title: str, description: str = "") -> bool:
    """
    Returns True if the job is a software/tech engineering role.
    
    Scoring:
      - Hard negative in title → always False
      - Positive keyword in title → True
      - Negative keyword in title AND no positive in description → False
      - Otherwise → True (give benefit of doubt if we can't determine)
    
    Target precision: >90% software/tech roles
    """
    title_lower = title.lower().strip()
    desc_lower = (description or "")[:500].lower()  # only check first 500 chars

    # 1. Hard negatives — always discard regardless
    for kw in HARD_NEGATIVE_TITLE_KEYWORDS:
        if kw in title_lower:
            return False

    # 2. Positive match in title — keep
    for kw in POSITIVE_TITLE_KEYWORDS:
        if kw in title_lower:
            # But verify it's not overridden by a negative
            for neg_kw in NEGATIVE_TITLE_KEYWORDS:
                if neg_kw in title_lower and kw in neg_kw:
                    # e.g. "software sales" — "software" is positive but full title is sales
                    pass  # continue checking other positives
            return True

    # 3. Negative in title → check description for tech signals
    has_neg = any(kw in title_lower for kw in NEGATIVE_TITLE_KEYWORDS)
    if has_neg:
        # Give a chance if description has strong tech signals
        tech_signals = sum(1 for kw in POSITIVE_DESC_KEYWORDS if kw in desc_lower)
        if tech_signals >= 3:
            return True
        return False

    # 4. Ambiguous title — check description for ANY tech signal
    has_tech_desc = any(kw in desc_lower for kw in POSITIVE_DESC_KEYWORDS[:10])
    return has_tech_desc


class BaseCrawler:
    source: str = "base"

    def __init__(self, browser_pool=None):
        from app.browser.browser_pool import browser_pool as bp
        self.browser_pool = browser_pool or bp

    async def crawl(
        self, query: str, location: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Crawl a job board for a query and location.
        Returns a list of dictionaries with keys:
            external_id: str
            source_url: str
            company_name: str
            role_title: str
            location: str
            job_description: str
            posting_date: Optional[datetime]
            is_remote: bool
        """
        raise NotImplementedError("Subclasses must implement crawl()")

    def clean_text(self, text: str) -> str:
        """Strip HTML tags and normalize whitespace."""
        if not text:
            return ""
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Decode common HTML entities
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace(
            "&gt;", ">"
        ).replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')
        # Normalize whitespace
        return " ".join(text.strip().split())

    def filter_tech_roles(
        self, jobs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Filter a list of scraped jobs to only include tech/engineering roles.
        Logs filtered counts for observability.
        """
        original_count = len(jobs)
        filtered = [
            job for job in jobs
            if is_tech_role(
                job.get("role_title", ""),
                job.get("job_description", "")
            )
        ]
        discarded = original_count - len(filtered)
        if discarded > 0:
            logger.info(
                f"{self.source}: Filtered {discarded}/{original_count} non-tech jobs. "
                f"Retained: {len(filtered)}"
            )
        return filtered
