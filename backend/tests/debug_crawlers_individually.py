import asyncio
import sys
import traceback
from app.crawlers.registry import crawler_registry
# Ensure crawlers are imported and registered
import app.crawlers.linkedin_crawler
import app.crawlers.wellfound_crawler
import app.crawlers.ashby_crawler
import app.crawlers.greenhouse_crawler
import app.crawlers.lever_crawler

async def test_crawler(name, query, location):
    print(f"\n--- Testing Crawler: {name.upper()} ---")
    crawler = crawler_registry.get_crawler(name)
    if not crawler:
        print(f"  [ERROR] Crawler '{name}' not found in registry!")
        return

    print(f"  Initiating crawl for query='{query}', location='{location}'...")
    try:
        # Run crawl
        jobs = await crawler.crawl(query, location)
        
        print(f"  [OK] Crawl finished. Total jobs fetched: {len(jobs)}")
        if jobs:
            print("  Sample Jobs:")
            for idx, job in enumerate(jobs[:3]):
                print(f"    {idx+1}. Title: {job.get('role_title')}")
                print(f"       Company: {job.get('company_name')}")
                print(f"       Location: {job.get('location')}")
                print(f"       URL: {job.get('source_url')}")
                print(f"       External ID: {job.get('external_id')}")
        else:
            print("  [WARN] Crawl returned zero jobs.")
    except Exception as e:
        print(f"  [FAIL] Crawler raised an exception:")
        traceback.print_exc()

async def main():
    print("=" * 60)
    print("AutoApply AI: Individual Crawler Verification Tool")
    print("=" * 60)
    
    # We will test each crawler with a standard Software Engineer query
    query = "Software Engineer"
    location = "Remote"
    
    crawlers_to_test = ["greenhouse", "lever", "ashby", "wellfound", "linkedin"]
    
    for c in crawlers_to_test:
        await test_crawler(c, query, location)
    
    # Close browser pool if initialized
    from app.browser.browser_pool import browser_pool
    await browser_pool.close_all()
    print("=" * 60)

if __name__ == "__main__":
    # Run async main
    asyncio.run(main())
