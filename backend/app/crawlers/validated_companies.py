"""
Validated company lists for each ATS.

These have been verified against live APIs.
Companies that return 404 or have migrated away are EXCLUDED.

Last validated: 2026-06-19

How to re-validate:
    python -m app.crawlers.validated_companies --validate
"""
import logging

logger = logging.getLogger("autoapply_ai.crawlers.companies")

# ── Greenhouse (boards-api.greenhouse.io/v1/boards/{slug}/jobs) ────────────
# Verified: returns 200 with real job postings
GREENHOUSE_COMPANIES = [
    "stripe", "affirm", "chime", "brex", "robinhood", "coinbase", "gemini",
    "cloudflare", "fastly", "twilio", "elastic", "gitlab", "databricks",
    "mongodb", "rubrik", "pinterest", "notion", "loom", "waymo", "scaleai",
]

# Excluded from Greenhouse (404, migrated, or transient failure):
# Pruned on 2026-06-19 to ensure rock-solid stability and zero wasted crawler requests.


# ── Lever (api.lever.co/v0/postings/{slug}) ───────────────────────────────
# Verified: returns 200 with valid flat list or grouped postings
LEVER_COMPANIES = [
    "palantir",
]

# Excluded from Lever (404, migrated, or transient failure):
# Pruned to include only the most reliable profiles.


# ── Ashby (api.ashbyhq.com/posting-api/job-board/{slug}) ──────────────────
# Verified: returns 200 with jobs list
ASHBY_COMPANIES = [
    "warp",
    "replit",
    "tldraw",
    "cursor",
    "vercel",
    "supabase",
    "railway",
    "neon",
    "perplexity",
    "pinecone",
    "weaviate",
    "clerk",
    "resend",
]

# Excluded from Ashby (404 or no active board):
# Pruned on 2026-06-19 for stability.


def get_all_companies() -> dict:
    return {
        "greenhouse": GREENHOUSE_COMPANIES,
        "lever": LEVER_COMPANIES,
        "ashby": ASHBY_COMPANIES,
    }



if __name__ == "__main__":
    import asyncio
    import httpx

    async def validate_all():
        """Live validation of all company handles. Run to re-validate lists."""
        results = {"greenhouse": {"ok": [], "fail": []}, "lever": {"ok": [], "fail": []}, "ashby": {"ok": [], "fail": []}}

        async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}, timeout=10.0) as client:
            # Greenhouse
            for company in GREENHOUSE_COMPANIES:
                url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
                try:
                    r = await client.get(url)
                    if r.status_code == 200:
                        results["greenhouse"]["ok"].append(company)
                    else:
                        results["greenhouse"]["fail"].append(f"{company}:{r.status_code}")
                except Exception as e:
                    results["greenhouse"]["fail"].append(f"{company}:ERR({e})")

            # Lever
            for company in LEVER_COMPANIES:
                url = f"https://api.lever.co/v0/postings/{company}"
                try:
                    r = await client.get(url)
                    if r.status_code == 200:
                        results["lever"]["ok"].append(company)
                    else:
                        results["lever"]["fail"].append(f"{company}:{r.status_code}")
                except Exception as e:
                    results["lever"]["fail"].append(f"{company}:ERR({e})")

            # Ashby
            for company in ASHBY_COMPANIES:
                url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
                try:
                    r = await client.get(url)
                    if r.status_code == 200:
                        results["ashby"]["ok"].append(company)
                    else:
                        results["ashby"]["fail"].append(f"{company}:{r.status_code}")
                except Exception as e:
                    results["ashby"]["fail"].append(f"{company}:ERR({e})")

        for ats, res in results.items():
            print(f"\n{ats.upper()}: {len(res['ok'])} OK, {len(res['fail'])} FAILED")
            if res["fail"]:
                print(f"  Failed: {res['fail']}")

    asyncio.run(validate_all())
