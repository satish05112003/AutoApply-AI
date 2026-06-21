import logging
import asyncio
import re
import random
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.crawlers.base_crawler import BaseCrawler
from app.crawlers.registry import crawler_registry

logger = logging.getLogger("autoapply_ai.crawlers.unstop")

class UnstopCrawler(BaseCrawler):
    source = "unstop"

    async def crawl(self, query: str, location: Optional[str] = None, limit: int = 50, params: Optional[Dict[str, Any]] = None, **kwargs) -> List[Dict[str, Any]]:
        """Crawl Unstop job & internship listings using search pages and detail page description fetching."""
        jobs_list = []
        loc = location or "India"
        search_query = query.replace(" ", "%20")
        
        # Unstop supports jobs, internships, hackathons. We search under /jobs and /internships
        urls_to_crawl = [
            f"https://unstop.com/jobs?search={search_query}",
            f"https://unstop.com/internships?search={search_query}"
        ]
        
        try:
            async with self.browser_pool.acquire_page() as page:
                await page.set_extra_http_headers({
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                })
                
                for search_url in urls_to_crawl:
                    if len(jobs_list) >= limit:
                        break
                        
                    await self.log_info(f"UnstopCrawler: Navigating to search URL: {search_url}")
                    try:
                        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                        await asyncio.sleep(random.uniform(2.5, 4.5))
                        
                        # Scroll to load lazy items
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
                        await asyncio.sleep(2.0)
                    except Exception as page_err:
                        logger.warning(f"UnstopCrawler: Failed to load search page: {page_err}")
                        continue
                        
                    # Extract cards using standard Unstop selectors
                    cards = await page.query_selector_all(".opportunity-card")
                    if not cards:
                        cards = await page.query_selector_all("app-opportunity-card, .opp-card, .listing-card")
                    if not cards:
                        cards = await page.query_selector_all("a[href*='/o/'], a[href*='/opportunity/']")
                        
                    logger.info(f"UnstopCrawler: Found {len(cards)} opportunity cards on {search_url}")
                    
                    now = datetime.now(timezone.utc)
                    
                    for card in cards:
                        if len(jobs_list) >= limit:
                            break
                            
                        try:
                            title_el = await card.query_selector("h2, h3, .opportunity-title, .title, .opp-title")
                            company_el = await card.query_selector(".company-name, .company, .organizer, .opp-org, .org")
                            loc_el = await card.query_selector(".location, .job-location, .loc")
                            
                            # Resolve URL
                            url_href = None
                            if await card.get_attribute("href"):
                                url_href = await card.get_attribute("href")
                            else:
                                link_el = await card.query_selector("a[href*='/o/'], a[href*='/opportunity/']")
                                if link_el:
                                    url_href = await link_el.get_attribute("href")
                                    
                            if title_el and company_el and url_href:
                                title = self.clean_text(await title_el.inner_text())
                                company = self.clean_text(await company_el.inner_text())
                                loc_str = self.clean_text(await loc_el.inner_text()) if loc_el else loc
                                
                                url = url_href
                                if url.startswith("/"):
                                    url = f"https://unstop.com{url}"
                                    
                                # Clean tracking parameters
                                if "?" in url:
                                    url = url.split("?")[0]
                                    
                                # Extract external id
                                ext_id = url.split("/")[-1]
                                if not ext_id:
                                    ext_id = str(now.timestamp())
                                    
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
                                    "external_id": ext_id,
                                    "source_url": url,
                                    "company_name": company,
                                    "role_title": title,
                                    "location": loc_str,
                                    "posting_date": now,
                                    "required_skills": req_skills,
                                    "is_remote": is_remote
                                })
                        except Exception as card_err:
                            logger.debug(f"UnstopCrawler: Error parsing job card: {card_err}")
                
                # Fetch description pages
                desc_count = 0
                for job in jobs_list:
                    if desc_count >= 10:
                        job["job_description"] = (
                            f"Opportunity for {job['role_title']} at {job['company_name']} in {job['location']}. "
                            f"Retrieved from Unstop. "
                            f"Full details at: {job['source_url']}"
                        )
                        continue
                        
                    await self.log_info(f"UnstopCrawler: Fetching details for {job['role_title']} at {job['company_name']}")
                    desc = await self._fetch_description(page, job["source_url"])
                    
                    if desc:
                        job["job_description"] = desc
                        desc_count += 1
                        await asyncio.sleep(random.uniform(2.0, 3.5))
                    else:
                        job["job_description"] = (
                            f"Opportunity for {job['role_title']} at {job['company_name']} in {job['location']}. "
                            f"Retrieved from Unstop. "
                            f"Full details at: {job['source_url']}"
                        )
                        
        except Exception as e:
            logger.warning(f"UnstopCrawler: Browser crawl failed: {e}")
            
        return jobs_list

    async def _fetch_description(self, page, job_url: str) -> str:
        """Visit Unstop opportunity URL and extract description details."""
        try:
            await page.goto(job_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2.0)
            
            desc_el = await page.query_selector(".description-details")
            if not desc_el:
                desc_el = await page.query_selector(".opportunity-details")
            if not desc_el:
                desc_el = await page.query_selector(".job-description")
            if not desc_el:
                desc_el = await page.query_selector(".opp-description")
                
            if desc_el:
                return (await desc_el.inner_text()).strip()
        except Exception as e:
            logger.debug(f"UnstopCrawler: Failed to fetch description from {job_url}: {e}")
        return ""

# Register to global registry
crawler_registry.register("unstop", UnstopCrawler)
