import logging
import asyncio
import re
import random
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.crawlers.base_crawler import BaseCrawler
from app.crawlers.registry import crawler_registry

logger = logging.getLogger("autoapply_ai.crawlers.indeed")

class IndeedCrawler(BaseCrawler):
    source = "indeed"

    async def crawl(self, query: str, location: Optional[str] = None, limit: int = 50, params: Optional[Dict[str, Any]] = None, **kwargs) -> List[Dict[str, Any]]:
        """Crawl Indeed job listings using standard search pages and detail page description fetching."""
        jobs_list = []
        loc = location or "United States"
        search_query = query.replace(" ", "+")
        search_location = loc.replace(" ", "+")
        
        # Build Indeed search URL
        # fromage=7 indicates past 7 days
        search_url = f"https://www.indeed.com/jobs?q={search_query}&l={search_location}&fromage=7"
        
        # If specific params are provided, apply them
        params = params or {}
        if "explvl" in params:
            search_url += f"&explvl={params['explvl']}"
        if "sc" in params:
            search_url += f"&sc={params['sc']}"
            
        logger.info(f"IndeedCrawler: Navigating to search URL: {search_url}")
        
        try:
            async with self.browser_pool.acquire_page() as page:
                await page.set_extra_http_headers({
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                })

                # Indeed often has cloudflare / anti-bot. We use a longer timeout and dynamic loading
                await page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(random.uniform(3.0, 5.5))
                
                # Scroll a bit to trigger dynamic rendering
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
                await asyncio.sleep(2.0)
                
                # Fetch job cards using multiple fallback selectors
                job_cards = await page.query_selector_all(".job_seen_beacon")
                if not job_cards:
                    job_cards = await page.query_selector_all("td.resultContent")
                if not job_cards:
                    job_cards = await page.query_selector_all(".result")
                    
                logger.info(f"IndeedCrawler: Found {len(job_cards)} job cards on page.")
                
                now = datetime.now(timezone.utc)
                
                for card in job_cards:
                    if len(jobs_list) >= limit:
                        break
                        
                    try:
                        title_el = await card.query_selector("a.jcs-JobTitle, h2.jobTitle a, a[href*='/rc/clk']")
                        company_el = await card.query_selector("[data-testid='company-name'], span.companyName, .companyName")
                        loc_el = await card.query_selector("[data-testid='text-location'], div.companyLocation, .companyLocation")
                        
                        if title_el and company_el:
                            title = self.clean_text(await title_el.inner_text())
                            company = self.clean_text(await company_el.inner_text())
                            loc_str = self.clean_text(await loc_el.inner_text()) if loc_el else loc
                            
                            # Indeed job key (jk ID) is usually stored on title href or parent element
                            jk = await title_el.get_attribute("data-jk") or await card.get_attribute("data-jk")
                            url_href = await title_el.get_attribute("href")
                            
                            if not jk and url_href:
                                jk_match = re.search(r'jk=([a-f0-9]+)', url_href)
                                if jk_match:
                                    jk = jk_match.group(1)
                                    
                            if not jk:
                                jk = str(now.timestamp())
                                
                            url = f"https://www.indeed.com/viewjob?jk={jk}" if jk else (
                                f"https://www.indeed.com{url_href}" if url_href and url_href.startswith("/") else url_href
                            )
                            
                            # Parse remote state
                            is_remote = "remote" in loc_str.lower() or "work from home" in loc_str.lower() or "remote" in title.lower()
                            
                            # Match skills
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
                                "external_id": jk,
                                "source_url": url,
                                "company_name": company,
                                "role_title": title,
                                "location": loc_str,
                                "posting_date": now,
                                "required_skills": req_skills,
                                "is_remote": is_remote
                            })
                    except Exception as card_err:
                        logger.debug(f"IndeedCrawler: Error parsing job card: {card_err}")
                
                # Fetch full descriptions for top 10 jobs
                desc_count = 0
                for job in jobs_list:
                    if desc_count >= 10:
                        job["job_description"] = (
                            f"Position for {job['role_title']} at {job['company_name']} in {job['location']}. "
                            f"Retrieved from Indeed. "
                            f"Full details at: {job['source_url']}"
                        )
                        continue
                        
                    await self.log_info(f"IndeedCrawler: Fetching details for {job['role_title']} at {job['company_name']}")
                    desc = await self._fetch_description(page, job["source_url"])
                    
                    if desc:
                        job["job_description"] = desc
                        desc_count += 1
                        await asyncio.sleep(random.uniform(2.0, 4.0))
                    else:
                        job["job_description"] = (
                            f"Position for {job['role_title']} at {job['company_name']} in {job['location']}. "
                            f"Retrieved from Indeed. "
                            f"Full details at: {job['source_url']}"
                        )
                        
        except Exception as e:
            logger.warning(f"IndeedCrawler: Browser crawl failed: {e}")
            
        return jobs_list

    async def _fetch_description(self, page, job_url: str) -> str:
        """Visit Indeed job URL and extract description text."""
        try:
            await page.goto(job_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2.0)
            
            desc_el = await page.query_selector("#jobDescriptionText")
            if not desc_el:
                desc_el = await page.query_selector(".jobsearch-JobComponent-description")
            if not desc_el:
                desc_el = await page.query_selector(".jobsearch-jobDescriptionText")
                
            if desc_el:
                return (await desc_el.inner_text()).strip()
        except Exception as e:
            logger.debug(f"IndeedCrawler: Failed to fetch description from {job_url}: {e}")
        return ""

# Register to global registry
crawler_registry.register("indeed", IndeedCrawler)
