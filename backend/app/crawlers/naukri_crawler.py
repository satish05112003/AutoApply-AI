import logging
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.crawlers.base_crawler import BaseCrawler
from app.crawlers.registry import crawler_registry

logger = logging.getLogger("autoapply_ai.crawlers.naukri")

class NaukriCrawler(BaseCrawler):
    source = "naukri"

    async def crawl(self, query: str, location: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        jobs_list = []
        loc = location or "India"
        search_query = query.lower().replace(" ", "-")
        search_url = f"https://www.naukri.com/{search_query}-jobs"
        if location:
            search_url += f"-in-{location.lower().replace(' ', '-')}"
            
        logger.info(f"NaukriCrawler: Navigating to search URL: {search_url}")
        
        try:
            async with self.browser_pool.acquire_page() as page:
                await page.goto(search_url, wait_until="networkidle", timeout=15000)
                
                # Scroll
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                await asyncio.sleep(1.0)
                
                # Fetch articles
                articles = await page.query_selector_all("article.jobTuple")
                logger.info(f"NaukriCrawler: Scraped {len(articles)} articles.")
                
                for art in articles[:limit]:
                    try:
                        title_el = await art.query_selector(".title")
                        company_el = await art.query_selector(".subTitle")
                        loc_el = await art.query_selector(".location")
                        desc_el = await art.query_selector(".job-description")
                        
                        if title_el and company_el:
                            title = self.clean_text(await title_el.inner_text())
                            company = self.clean_text(await company_el.inner_text())
                            loc_str = self.clean_text(await loc_el.inner_text()) if loc_el else loc
                            desc = self.clean_text(await desc_el.inner_text()) if desc_el else "N/A"
                            
                            # ID attribute is typically stored on article tag
                            ext_id = await art.get_attribute("data-jobid") or str(datetime.now().timestamp())
                            url = await title_el.get_attribute("href") or f"https://www.naukri.com/job-listings-{ext_id}"
                            
                            jobs_list.append({
                                "external_id": ext_id,
                                "source_url": url,
                                "company_name": company,
                                "role_title": title,
                                "location": loc_str,
                                "job_description": desc,
                                "posting_date": datetime.now(timezone.utc),
                                "is_remote": "remote" in loc_str.lower() or "remote" in title.lower()
                            })
                    except Exception as e:
                        logger.warning(f"NaukriCrawler: Error parsing job article: {e}")
        except Exception as e:
            logger.warning(f"NaukriCrawler: Browser crawl failed: {e}")
            
        return jobs_list

# Register to global registry
crawler_registry.register("naukri", NaukriCrawler)
