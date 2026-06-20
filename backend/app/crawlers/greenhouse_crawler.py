"""
Greenhouse Crawler — real job ingestion from boards-api.greenhouse.io

Changes:
  - Uses GREENHOUSE_COMPANIES from validated_companies.py (dead boards removed)
  - Applies is_tech_role() filter BEFORE returning jobs
  - Query matching now uses TECH_ROLE_QUERIES expansion table
  - Age window: 7 days (Greenhouse updated_at is not reliable as posting date)
  - Concurrent fetches with asyncio.gather() + return_exceptions=True
"""
import logging
import asyncio
import httpx
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from app.crawlers.base_crawler import BaseCrawler
from app.crawlers.registry import crawler_registry
from app.crawlers.validated_companies import GREENHOUSE_COMPANIES

logger = logging.getLogger("autoapply_ai.crawlers.greenhouse")

# Role query → title keyword expansions
TECH_ROLE_QUERIES: Dict[str, List[str]] = {
    "software engineer": ["software", "engineer", "developer", "sde", "swe", "programmer"],
    "machine learning": ["machine learning", "ml engineer", "ai engineer", "deep learning", "llm"],
    "data engineer": ["data engineer", "data pipeline", "analytics engineer", "etl"],
    "backend engineer": ["backend", "server-side", "api engineer", "platform engineer"],
    "frontend engineer": ["frontend", "front-end", "react engineer", "ui engineer"],
    "full stack": ["full stack", "fullstack", "full-stack"],
    "devops": ["devops", "sre", "site reliability", "platform engineer", "infrastructure engineer"],
    "python developer": ["python", "django", "fastapi"],
    "generative ai": ["generative ai", "gen ai", "llm", "large language"],
    "applied scientist": ["applied scientist", "research scientist", "research engineer"],
}


class GreenhouseCrawler(BaseCrawler):
    source = "greenhouse"
    COMPANIES = GREENHOUSE_COMPANIES

    def _matches_query(self, query: str, title: str, content: str) -> bool:
        """Fuzzy query matching with tech-role keyword expansion."""
        q_lower = query.lower()
        title_lower = title.lower()
        content_lower = (content or "")[:300].lower()

        # Direct match
        if q_lower in title_lower:
            return True

        # Expansion table match
        for base_query, expansions in TECH_ROLE_QUERIES.items():
            if q_lower in (base_query,) + tuple(expansions):
                if any(exp in title_lower for exp in expansions):
                    return True

        # Single meaningful word match in title (min 5 chars to avoid false hits)
        query_words = [w for w in q_lower.split() if len(w) >= 5]
        for word in query_words:
            if word in title_lower:
                return True

        return False

    async def crawl(
        self, query: str, location: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        logger.info(f"GreenhouseCrawler: crawl query='{query}' location='{location}'")
        jobs_list: List[Dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
            timeout=httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=2.0),
            follow_redirects=True,
        ) as client:
            tasks = [
                self._fetch_company_jobs(client, company, query, location, now)
                for company in self.COMPANIES
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, list):
                    jobs_list.extend(res)

        # Apply tech-role relevance filter
        jobs_list = self.filter_tech_roles(jobs_list)
        logger.info(f"GreenhouseCrawler: {len(jobs_list)} tech jobs after filter (limit={limit})")
        return jobs_list[:limit]

    async def _fetch_company_jobs(
        self,
        client: httpx.AsyncClient,
        company: str,
        query: str,
        location: Optional[str],
        now: datetime,
    ) -> List[Dict[str, Any]]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"
        try:
            response = await client.get(url)
            if response.status_code != 200:
                return []

            data = response.json()
            jobs = data.get("jobs", [])
            board_company = data.get("company", {}).get("name", company.capitalize())
            matches: List[Dict[str, Any]] = []

            for job in jobs:
                title = job.get("title", "")
                content = job.get("content", "")

                # Query relevance check
                if not self._matches_query(query, title, content):
                    continue

                # Location filter (skip if location is remote/worldwide)
                loc_data = job.get("location") or {}
                location_name = (
                    loc_data.get("name", "") if isinstance(loc_data, dict) else str(loc_data)
                )
                if location and location.lower() not in ("remote", "anywhere", "worldwide"):
                    if location.lower() not in location_name.lower():
                        continue

                # Age filter: last 7 days
                updated_at_str = job.get("updated_at")
                if updated_at_str:
                    try:
                        dt = datetime.fromisoformat(
                            updated_at_str.replace("Z", "+00:00")
                        ).astimezone(timezone.utc)
                    except Exception:
                        dt = now
                else:
                    dt = now

                if (now - dt) > timedelta(days=7):
                    continue

                is_remote = (
                    "remote" in location_name.lower()
                    or "remote" in title.lower()
                    or not location_name
                )

                matches.append({
                    "external_id": str(job.get("id")),
                    "source_url": f"https://boards.greenhouse.io/{company}/jobs/{job.get('id')}",
                    "company_name": board_company,
                    "role_title": title,
                    "location": location_name or "Remote",
                    "job_description": self.clean_text(content),
                    "posting_date": dt,
                    "is_remote": is_remote,
                })
            return matches
        except Exception as e:
            logger.debug(f"GreenhouseCrawler: {company}: {e}")
            return []


crawler_registry.register("greenhouse", GreenhouseCrawler)
