import logging
import asyncio
import httpx
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from app.crawlers.base_crawler import BaseCrawler
from app.crawlers.registry import crawler_registry
from app.crawlers.validated_companies import ASHBY_COMPANIES

logger = logging.getLogger("autoapply_ai.crawlers.ashby")

class AshbyCrawler(BaseCrawler):
    source = "ashby"

    # Validated companies — sourced from validated_companies.py
    COMPANIES = ASHBY_COMPANIES

    # Expanded query keywords for fuzzy matching
    QUERY_EXPANSIONS = {
        "software engineer": ["software", "engineer", "developer", "sde", "swe"],
        "machine learning": ["machine learning", "ml", "ai engineer", "deep learning"],
        "data engineer": ["data engineer", "data pipeline", "etl", "data platform"],
        "backend engineer": ["backend", "server side", "api engineer", "platform engineer"],
        "frontend engineer": ["frontend", "front end", "react", "ui engineer"],
        "full stack": ["full stack", "fullstack", "full-stack"],
        "devops": ["devops", "sre", "platform", "infrastructure", "cloud engineer"],
        "python": ["python", "django", "fastapi", "flask"],
    }

    def _matches_query(self, query: str, title: str, description: str) -> bool:
        """Check if any expanded keyword from the query appears in title or description."""
        q_lower = query.lower()
        if q_lower in title.lower() or q_lower in description.lower():
            return True
        for base_query, expansions in self.QUERY_EXPANSIONS.items():
            if q_lower == base_query or q_lower in expansions:
                for term in expansions:
                    if term in title.lower() or term in description.lower():
                        return True
        # Partial word match
        query_words = [w for w in q_lower.split() if len(w) > 3]
        for word in query_words:
            if word in title.lower():
                return True
        return False

    async def crawl(self, query: str, location: Optional[str] = None, limit: int = 100, params: Optional[Dict[str, Any]] = None, **kwargs) -> List[Dict[str, Any]]:
        """
        Scrapes real jobs from Ashby boards for companies in self.COMPANIES
        matching the query/location and posted in the last 7 days.
        """
        logger.info(f"AshbyCrawler: Starting real crawl for query='{query}', location='{location}'")
        jobs_list = []
        now = datetime.now(timezone.utc)

        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=15.0,
            follow_redirects=True
        ) as client:
            tasks = [
                self._fetch_company_jobs(client, company, query, location, now)
                for company in self.COMPANIES
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in results:
                if isinstance(res, list):
                    jobs_list.extend(res)
                elif isinstance(res, Exception):
                    logger.debug(f"AshbyCrawler company crawl task failed: {res}")

        # Apply tech-role relevance filter
        jobs_list = self.filter_tech_roles(jobs_list)
        logger.info(f"AshbyCrawler: {len(jobs_list)} tech jobs after filter (limit={limit})")
        return jobs_list[:limit]

    async def _fetch_company_jobs(
        self, client: httpx.AsyncClient, company: str, query: str,
        location: Optional[str], now: datetime
    ) -> List[Dict[str, Any]]:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
        try:
            response = await client.get(url)
            if response.status_code != 200:
                logger.debug(f"Ashby board for {company} returned status {response.status_code}")
                return []

            data = response.json()
            jobs = data.get("jobs", [])
            matches = []

            for job in jobs:
                title = job.get("title", "")
                # Ashby returns descriptionPlain or descriptionHtml
                description = job.get("descriptionPlain", "") or ""
                if not description:
                    desc_html = job.get("descriptionHtml", "")
                    # Strip HTML tags minimally for matching
                    import re
                    description = re.sub(r"<[^>]+>", " ", desc_html)

                # Check role query matching (fuzzy)
                if not self._matches_query(query, title, description):
                    continue

                # Check location if provided
                location_name = job.get("location", "") or "Remote"
                if location and location.lower() not in ("remote", "anywhere", "worldwide"):
                    if location.lower() not in location_name.lower():
                        continue

                # Parse date — Ashby uses ISO format publishedAt
                # If missing, job is live on the board so include it regardless
                published_at_str = job.get("publishedAt")
                if published_at_str:
                    try:
                        dt = datetime.fromisoformat(
                            published_at_str.replace("Z", "+00:00")
                        ).astimezone(timezone.utc)
                    except Exception:
                        dt = now
                    age = now - dt
                    if age > timedelta(days=30):  # Skip only truly stale postings (>30d)
                        continue
                else:
                    # No publish date means actively open job — always include
                    dt = now

                is_remote = (
                    job.get("isRemote", False)
                    or "remote" in location_name.lower()
                    or "remote" in title.lower()
                )

                # Build job URL
                job_url = job.get("jobUrl") or f"https://jobs.ashbyhq.com/{company}/{job.get('id')}"

                matches.append({
                    "external_id": str(job.get("id")),
                    "source_url": job_url,
                    "company_name": company.capitalize(),
                    "role_title": title,
                    "location": location_name,
                    "job_description": self.clean_text(description),
                    "posting_date": dt,
                    "is_remote": is_remote
                })
            return matches
        except Exception as e:
            logger.debug(f"AshbyCrawler: Failed to fetch jobs for company '{company}': {e}")
            return []

# Register to global registry
crawler_registry.register("ashby", AshbyCrawler)
