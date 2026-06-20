import logging
import asyncio
import re
import random
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.crawlers.base_crawler import BaseCrawler
from app.crawlers.registry import crawler_registry

logger = logging.getLogger("autoapply_ai.crawlers.naukri")

class NaukriCrawler(BaseCrawler):
    source = "naukri"

    async def crawl(self, query: str, location: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Crawl Naukri job listings using updated selectors and detail page description fetching."""
        jobs_list = []
        loc = location or "India"
        search_query = query.lower().replace(" ", "-")
        search_url = f"https://www.naukri.com/{search_query}-jobs"
        if location:
            search_url += f"-in-{location.lower().replace(' ', '-')}"
            
        logger.info(f"NaukriCrawler: Navigating to search URL: {search_url}")
        
        try:
            async with self.browser_pool.acquire_page() as page:
                # Use standard mobile/desktop user-agent
                await page.set_extra_http_headers({
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                })

                await page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
                await asyncio.sleep(2.0)
                
                # Scroll to load dynamic content
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                await asyncio.sleep(2.0)
                
                # Fetch articles using updated selectors
                articles = await page.query_selector_all(".srp-jobtuple-wrapper")
                if not articles:
                    articles = await page.query_selector_all(".cust-job-tuple")
                if not articles:
                    articles = await page.query_selector_all("article.jobTuple")
                    
                logger.info(f"NaukriCrawler: Found {len(articles)} job cards on page.")
                
                now = datetime.now(timezone.utc)
                
                for art in articles:
                    if len(jobs_list) >= limit:
                        break
                        
                    try:
                        title_el = await art.query_selector("a.title, .title")
                        company_el = await art.query_selector(".subTitle, .comp-name, a.comp-name")
                        loc_el = await art.query_selector(".location, .loc-wrap")
                        exp_el = await art.query_selector(".experience, .exp-wrap")
                        sal_el = await art.query_selector(".salary, .sal-wrap")
                        
                        if title_el and company_el:
                            title = self.clean_text(await title_el.inner_text())
                            company = self.clean_text(await company_el.inner_text())
                            loc_str = self.clean_text(await loc_el.inner_text()) if loc_el else loc
                            
                            # Parse years of experience (e.g. "3-8 Yrs")
                            exp_str = await exp_el.inner_text() if exp_el else ""
                            exp_min = None
                            exp_max = None
                            if exp_str:
                                exp_match = re.search(r'(\d+)\s*-\s*(\d+)\s*Yrs', exp_str, re.IGNORECASE)
                                if exp_match:
                                    exp_min = float(exp_match.group(1))
                                    exp_max = float(exp_match.group(2))
                                else:
                                    # Fallback for single digit (e.g. "2 Yrs")
                                    single_match = re.search(r'(\d+)\s*Yrs', exp_str, re.IGNORECASE)
                                    if single_match:
                                        exp_min = float(single_match.group(1))
                            
                            # ID attribute is typically stored on article or wrapper tag
                            ext_id = await art.get_attribute("data-jobid") or await art.get_attribute("id") or str(now.timestamp())
                            url = await title_el.get_attribute("href") or f"https://www.naukri.com/job-listings-{ext_id}"
                            
                            # Clean Naukri tracking params from URL
                            if url and "?" in url:
                                url = url.split("?")[0]

                            # Determine required skills from title keywords
                            req_skills = []
                            possible_skills = [
                                "python", "javascript", "typescript", "react", "node", "aws", "docker", "kubernetes",
                                "postgres", "sql", "django", "fastapi", "golang", "java", "c++", "embedded", "firmware",
                                "c", "rust", "machine learning", "ml", "ai", "llm", "generative ai", "pytorch"
                            ]
                            title_lower = title.lower()
                            for sk in possible_skills:
                                if sk in title_lower:
                                    req_skills.append(sk.upper())

                            jobs_list.append({
                                "external_id": ext_id,
                                "source_url": url,
                                "company_name": company,
                                "role_title": title,
                                "location": loc_str,
                                "posting_date": now,
                                "experience_min_years": exp_min,
                                "experience_max_years": exp_max,
                                "required_skills": req_skills,
                                "is_remote": "remote" in loc_str.lower() or "remote" in title_lower
                            })
                    except Exception as card_err:
                        logger.debug(f"NaukriCrawler: Error parsing job card: {card_err}")
                
                # Fetch full descriptions in a second step for the first 10 results
                desc_count = 0
                for job in jobs_list:
                    if desc_count >= 10:
                        job["job_description"] = (
                            f"Position for {job['role_title']} at {job['company_name']} in {job['location']}. "
                            f"Retrieved from Naukri. "
                            f"Full details at: {job['source_url']}"
                        )
                        continue

                    await self.log_info(f"NaukriCrawler: Fetching details for {job['role_title']} at {job['company_name']}")
                    desc = await self._fetch_description(page, job["source_url"])
                    
                    if desc:
                        job["job_description"] = desc
                        desc_count += 1
                        await asyncio.sleep(random.uniform(1.5, 3.0))
                    else:
                        job["job_description"] = (
                            f"Position for {job['role_title']} at {job['company_name']} in {job['location']}. "
                            f"Retrieved from Naukri. "
                            f"Full details at: {job['source_url']}"
                        )
                        
        except Exception as e:
            logger.warning(f"NaukriCrawler: Browser crawl failed: {e}")
            
        return jobs_list

    async def _fetch_description(self, page, job_url: str) -> str:
        """Visit the Naukri job URL and extract full description text."""
        try:
            await page.goto(job_url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(1.5)
            
            desc_el = await page.query_selector(".job-desc")
            if not desc_el:
                desc_el = await page.query_selector(".job-description")
            if not desc_el:
                desc_el = await page.query_selector("#job-desc")
                
            if desc_el:
                return (await desc_el.inner_text()).strip()
        except Exception as e:
            logger.debug(f"NaukriCrawler: Failed to fetch description from {job_url}: {e}")
        return ""

# Register to global registry
crawler_registry.register("naukri", NaukriCrawler)
