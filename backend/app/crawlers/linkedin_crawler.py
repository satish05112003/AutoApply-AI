import logging
import asyncio
import random
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from app.crawlers.base_crawler import BaseCrawler
from app.crawlers.registry import crawler_registry

logger = logging.getLogger("autoapply_ai.crawlers.linkedin")

class LinkedInCrawler(BaseCrawler):
    source = "linkedin"

    # Time filter param: r86400 = last 24h, r604800 = last 7 days
    TIME_FILTER = "r604800"  # 7 days

    async def crawl(self, query: str, location: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Crawl LinkedIn public guest jobs search feed with pagination and delays."""
        jobs_list = []
        loc = location or "United States"
        search_query = query.replace(" ", "%20")
        search_location = loc.replace(" ", "%20")

        logger.info(f"LinkedInCrawler: Starting crawl for query={query}, location={loc}")

        try:
            async with self.browser_pool.acquire_page() as page:
                # Set a realistic user agent and headers
                await page.set_extra_http_headers({
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                })

                # Crawl multiple pages: start = 0, 25, 50
                for start in [0, 25, 50]:
                    if len(jobs_list) >= limit:
                        break

                    search_url = (
                        f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                        f"?keywords={search_query}&location={search_location}"
                        f"&f_TPR={self.TIME_FILTER}&start={start}"
                    )
                    
                    await self.log_info(f"LinkedInCrawler: Fetching page start={start} URL: {search_url}")
                    
                    try:
                        await page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
                        await asyncio.sleep(random.uniform(2.0, 5.0))  # Anti-scraping random delay
                    except Exception as nav_err:
                        logger.warning(f"LinkedInCrawler: Page navigation error on start={start}: {nav_err}")
                        continue

                    # Try multiple selectors for job cards
                    job_cards = await page.query_selector_all(".job-search-card")
                    if not job_cards:
                        job_cards = await page.query_selector_all("[data-entity-urn]")
                    if not job_cards:
                        job_cards = await page.query_selector_all("li.result-card")

                    logger.info(f"LinkedInCrawler: Found {len(job_cards)} job cards on page start={start}.")
                    if not job_cards:
                        break  # No more jobs found

                    now = datetime.now(timezone.utc)

                    for card in job_cards:
                        if len(jobs_list) >= limit:
                            break

                        try:
                            title_el = await card.query_selector(".base-search-card__title")
                            company_el = await card.query_selector(".base-search-card__subtitle")
                            loc_el = await card.query_selector(".job-search-card__location")
                            link_el = await card.query_selector("a.base-card__full-link")
                            if not link_el:
                                link_el = await card.query_selector("a[href*='/jobs/view/']")
                            time_el = await card.query_selector("time")

                            if title_el and company_el and link_el:
                                title = self.clean_text(await title_el.inner_text())
                                company = self.clean_text(await company_el.inner_text())
                                loc_str = self.clean_text(await loc_el.inner_text()) if loc_el else loc
                                url = await link_el.get_attribute("href")

                                # Clean LinkedIn tracking parameters
                                if url and "?" in url:
                                    url = url.split("?")[0]

                                urn = await card.get_attribute("data-entity-urn")
                                ext_id = (
                                    urn.split(":")[-1] if urn
                                    else (url.split("-")[-1] if url else str(now.timestamp()))
                                )

                                # Parse publishing date
                                datetime_attr = await time_el.get_attribute("datetime") if time_el else None
                                time_text = (await time_el.inner_text()) if time_el else ""

                                dt = now
                                if datetime_attr:
                                    try:
                                        dt = datetime.fromisoformat(datetime_attr).replace(tzinfo=timezone.utc)
                                    except Exception:
                                        pass
                                elif time_text:
                                    time_text_lower = time_text.lower()
                                    if "hour" in time_text_lower or "minute" in time_text_lower:
                                        try:
                                            nums = [s for s in time_text_lower.split() if s.isdigit()]
                                            hours = int(nums[0]) if nums else 0
                                            dt = now - timedelta(hours=hours)
                                        except Exception:
                                            pass
                                    elif "day" in time_text_lower:
                                        try:
                                            nums = [s for s in time_text_lower.split() if s.isdigit()]
                                            days = int(nums[0]) if nums else 1
                                            dt = now - timedelta(days=days)
                                        except Exception:
                                            pass
                                    elif "week" in time_text_lower:
                                        try:
                                            nums = [s for s in time_text_lower.split() if s.isdigit()]
                                            weeks = int(nums[0]) if nums else 1
                                            dt = now - timedelta(weeks=weeks)
                                        except Exception:
                                            pass

                                # Filter: keep jobs posted within last 7 days
                                age = now - dt
                                if age > timedelta(days=7):
                                    continue

                                # Determine experience min years from title
                                title_lower = title.lower()
                                exp_min = None
                                if any(w in title_lower for w in ["junior", "jr", "entry", "associate", "intern", "fresher"]):
                                    exp_min = 0
                                elif any(w in title_lower for w in ["senior", "sr", "lead"]):
                                    exp_min = 5
                                elif any(w in title_lower for w in ["principal", "staff", "architect"]):
                                    exp_min = 8
                                elif any(w in title_lower for w in ["manager", "director", "head", "vp"]):
                                    exp_min = 10

                                # Determine required skills from title keywords
                                req_skills = []
                                possible_skills = [
                                    "python", "javascript", "typescript", "react", "node", "aws", "docker", "kubernetes",
                                    "postgres", "sql", "django", "fastapi", "golang", "java", "c++", "embedded", "firmware",
                                    "c", "rust", "machine learning", "ml", "ai", "llm", "generative ai", "pytorch"
                                ]
                                for sk in possible_skills:
                                    if sk in title_lower:
                                        req_skills.append(sk.upper())

                                jobs_list.append({
                                    "external_id": ext_id,
                                    "source_url": url,
                                    "company_name": company,
                                    "role_title": title,
                                    "location": loc_str,
                                    "posting_date": dt,
                                    "experience_min_years": exp_min,
                                    "required_skills": req_skills,
                                    "is_remote": (
                                        "remote" in loc_str.lower()
                                        or "remote" in title_lower
                                    )
                                })
                        except Exception as card_err:
                            logger.debug(f"LinkedInCrawler: Error parsing job card: {card_err}")

                # Fetch full descriptions in a second step for the first 15 results
                # to prevent aggressive blocking from LinkedIn
                desc_count = 0
                for job in jobs_list:
                    if desc_count >= 15:
                        # Rest get fallback descriptions to keep the crawl fast and avoid blocks
                        job["job_description"] = (
                            f"Position for {job['role_title']} at {job['company_name']} in {job['location']}. "
                            f"Retrieved from LinkedIn. "
                            f"Full details at: {job['source_url']}"
                        )
                        continue

                    await self.log_info(f"LinkedInCrawler: Fetching details for {job['role_title']} at {job['company_name']}")
                    desc = await self._fetch_description(page, job["source_url"])
                    
                    if desc:
                        job["job_description"] = desc
                        desc_count += 1
                        # Short delay between details page requests
                        await asyncio.sleep(random.uniform(1.5, 3.0))
                    else:
                        # Fallback
                        job["job_description"] = (
                            f"Position for {job['role_title']} at {job['company_name']} in {job['location']}. "
                            f"Retrieved from LinkedIn. "
                            f"Full details at: {job['source_url']}"
                        )

        except Exception as e:
            logger.error(f"LinkedInCrawler: Browser crawling failed: {e}")

        logger.info(f"LinkedInCrawler: Crawl complete. Ingested {len(jobs_list)} real jobs.")
        return jobs_list

    async def _fetch_description(self, page, job_url: str) -> str:
        """Visit the job URL and extract full description text."""
        try:
            await page.goto(job_url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(1.5)
            
            # Detect auth wall
            if "authwall" in page.url or "login" in page.url:
                logger.warning(f"LinkedInCrawler: Hit authwall on details page: {page.url}")
                return ""
                
            # Click "Show more" button if it exists
            try:
                show_more = await page.query_selector("button.show-more-less-html__button")
                if show_more and await show_more.is_visible():
                    await show_more.click()
                    await asyncio.sleep(0.5)
            except Exception:
                pass
                
            desc_el = await page.query_selector(".show-more-less-html__markup")
            if not desc_el:
                desc_el = await page.query_selector(".description__text")
            if not desc_el:
                desc_el = await page.query_selector("section.description")
                
            if desc_el:
                return (await desc_el.inner_text()).strip()
        except Exception as e:
            logger.debug(f"LinkedInCrawler: Failed to fetch description from {job_url}: {e}")
        return ""

# Register to global registry
crawler_registry.register("linkedin", LinkedInCrawler)
