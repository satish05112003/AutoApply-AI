import logging
import asyncio
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
        """Crawl LinkedIn public guest jobs search feed."""
        jobs_list = []
        loc = location or "United States"
        search_query = query.replace(" ", "%20")
        search_location = loc.replace(" ", "%20")

        # Public guest API endpoint with 7-day time filter
        search_url = (
            f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
            f"?keywords={search_query}&location={search_location}"
            f"&f_TPR={self.TIME_FILTER}&start=0"
        )

        logger.info(f"LinkedInCrawler: Navigating to guest search URL: {search_url}")

        try:
            async with self.browser_pool.acquire_page() as page:
                # Set a realistic user agent
                await page.set_extra_http_headers({
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                })

                try:
                    await page.goto(search_url, wait_until="networkidle", timeout=25000)
                except Exception as nav_err:
                    logger.warning(f"LinkedInCrawler: Navigation timeout (continuing with DOM): {nav_err}")

                # Try multiple selectors for job cards
                job_cards = await page.query_selector_all(".job-search-card")
                if not job_cards:
                    job_cards = await page.query_selector_all("[data-entity-urn]")
                if not job_cards:
                    job_cards = await page.query_selector_all("li.result-card")

                logger.info(f"LinkedInCrawler: Found {len(job_cards)} job cards on page.")

                now = datetime.now(timezone.utc)

                for card in job_cards:
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
                                logger.debug(
                                    f"LinkedInCrawler: Skipping old job: {title} at {company} "
                                    f"({age.total_seconds() / 3600:.1f}h ago)"
                                )
                                continue

                            desc = (
                                f"Position for {title} at {company} in {loc_str}. "
                                f"Retrieved from LinkedIn. "
                                f"Full description at: {url}"
                            )

                            jobs_list.append({
                                "external_id": ext_id,
                                "source_url": url,
                                "company_name": company,
                                "role_title": title,
                                "location": loc_str,
                                "job_description": desc,
                                "posting_date": dt,
                                "is_remote": (
                                    "remote" in loc_str.lower()
                                    or "remote" in title.lower()
                                )
                            })

                            if len(jobs_list) >= limit:
                                break
                    except Exception as card_err:
                        logger.debug(f"LinkedInCrawler: Error parsing job card: {card_err}")

        except Exception as e:
            logger.error(f"LinkedInCrawler: Browser crawling failed: {e}")

        logger.info(f"LinkedInCrawler: Ingested {len(jobs_list)} real jobs.")
        return jobs_list

# Register to global registry
crawler_registry.register("linkedin", LinkedInCrawler)
