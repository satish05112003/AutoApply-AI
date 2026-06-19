import logging
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.crawlers.base_crawler import BaseCrawler
from app.crawlers.registry import crawler_registry

logger = logging.getLogger("autoapply_ai.crawlers.wellfound")

class WellfoundCrawler(BaseCrawler):
    source = "wellfound"

    # Selectors in priority order — Wellfound changes CSS classes frequently
    TITLE_SELECTORS = [
        ".styles_title__J52R_",
        "[data-test='JobListing__title']",
        "h2 a",
        ".job-listing a",
        "a[href*='/jobs/']",
    ]
    COMPANY_SELECTORS = [
        ".styles_name__fS_X8",
        "[data-test='JobListing__company']",
        ".company-name",
        ".startup-name",
    ]
    LOCATION_SELECTORS = [
        ".styles_location__U_q29",
        "[data-test='JobListing__location']",
        ".location",
        ".job-location",
    ]
    CARD_SELECTORS = [
        ".styles_component__y5M6k",
        "[data-test='JobListing']",
        ".job-listing",
        ".startup-job",
        "li.mb-6",
    ]

    async def _try_selector(self, element, selectors: list) -> Optional[Any]:
        """Try multiple selectors and return the first match."""
        for sel in selectors:
            try:
                found = await element.query_selector(sel)
                if found:
                    return found
            except Exception:
                continue
        return None

    async def crawl(self, query: str, location: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        jobs_list = []
        loc = location or "Remote"
        # Build search URL using role keyword
        role_slug = query.lower().replace(" ", "-")
        search_url = f"https://wellfound.com/role/l/{role_slug}"

        logger.info(f"WellfoundCrawler: Navigating to search URL: {search_url}")

        try:
            async with self.browser_pool.acquire_page() as page:
                # Navigate with extended timeout and wait for network idle
                try:
                    await page.goto(search_url, wait_until="networkidle", timeout=25000)
                except Exception as nav_err:
                    logger.warning(f"WellfoundCrawler: Navigation timeout (continuing): {nav_err}")

                # Try multiple card selectors
                cards = []
                for card_sel in self.CARD_SELECTORS:
                    try:
                        cards = await page.query_selector_all(card_sel)
                        if cards:
                            logger.info(f"WellfoundCrawler: Found {len(cards)} job cards with selector '{card_sel}'")
                            break
                    except Exception:
                        continue

                if not cards:
                    logger.warning(f"WellfoundCrawler: No job cards found on {search_url}")
                    return []

                for idx, card in enumerate(cards[:limit]):
                    try:
                        title_el = await self._try_selector(card, self.TITLE_SELECTORS)
                        company_el = await self._try_selector(card, self.COMPANY_SELECTORS)
                        loc_el = await self._try_selector(card, self.LOCATION_SELECTORS)

                        if title_el and company_el:
                            title = self.clean_text(await title_el.inner_text())
                            company = self.clean_text(await company_el.inner_text())
                            loc_str = self.clean_text(await loc_el.inner_text()) if loc_el else loc

                            # Try to get href from title or parent anchor
                            url = await title_el.get_attribute("href")
                            if not url:
                                parent_a = await card.query_selector("a[href*='/jobs/']")
                                if parent_a:
                                    url = await parent_a.get_attribute("href")
                            if not url:
                                url = f"https://wellfound.com/jobs/{idx}"

                            # Make absolute URL
                            if url and url.startswith("/"):
                                url = f"https://wellfound.com{url}"

                            ext_id = url.split("/")[-1].split("?")[0] if "/" in url else str(idx)

                            jobs_list.append({
                                "external_id": f"wf_{ext_id}",
                                "source_url": url,
                                "company_name": company,
                                "role_title": title,
                                "location": loc_str,
                                "job_description": (
                                    f"Startup opportunity for a {title} at {company}. "
                                    f"Location: {loc_str}. "
                                    f"Apply via Wellfound: {url}"
                                ),
                                "posting_date": datetime.now(timezone.utc),
                                "is_remote": "remote" in loc_str.lower() or "remote" in title.lower()
                            })
                    except Exception as e:
                        logger.debug(f"WellfoundCrawler: Error parsing card #{idx}: {e}")

        except Exception as e:
            logger.warning(f"WellfoundCrawler: Browser crawl failed: {e}")

        logger.info(f"WellfoundCrawler: Scraped {len(jobs_list)} real jobs.")
        return jobs_list

# Register to global registry
crawler_registry.register("wellfound", WellfoundCrawler)
