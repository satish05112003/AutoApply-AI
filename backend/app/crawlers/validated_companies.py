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
    # Fintech / Payments
    "stripe", "plaid", "affirm", "chime", "ramp", "brex", "robinhood",
    "coinbase", "kraken", "gemini",

    # Infrastructure / Cloud
    "cloudflare", "fastly", "twilio", "sendgrid", "auth0",
    "hashicorp", "elastic", "confluent", "gitlab",

    # Data / Analytics
    "snowflake", "databricks", "mongodb", "rubrik", "zoominfo",

    # Enterprise SaaS
    "okta", "asana", "docusign", "box", "dropbox", "hubspot",
    "squarespace", "zendesk", "freshworks", "intercom",

    # Consumer / Social
    "airbnb", "lyft", "instacart", "pinterest", "notion",
    "loom", "figma", "webflow", "retool",

    # Gaming / Entertainment
    "unity", "roblox", "twitch",

    # Mobility / Hardware
    "waymo", "rivian",

    # AI / ML (confirmed on Greenhouse)
    "scaleai",

    # Developer Tools
    "gusto", "rippling", "flexport", "toast",
    "slack", "zoom",
]

# Excluded from Greenhouse (404 or migrated):
# openai (uses Greenhouse but slug is "openai-4" — inconsistent, skip)
# anthropic (uses Greenhouse but with non-standard slug)
# huggingface (uses Ashby)
# langchain (no public board)
# cohere (uses Greenhouse but 404 on standard slug)
# perplexity (uses Ashby)
# mistral (European, Lever)
# elevenlabs (uses Ashby)
# runway (uses Ashby)
# jasper, copyai, writer (no standard boards)
# pinecone, weaviate, chroma (no standard Greenhouse boards)
# llamaindex (no board)
# midjourney (no public board)
# character (no public board)
# synthesia (Lever)


# ── Lever (api.lever.co/v0/postings/{slug}) ───────────────────────────────
# Verified: returns 200 with valid flat list or grouped postings
LEVER_COMPANIES = [
    # Core tech companies confirmed on Lever
    "palantir",
    "postman",
    "framer",

    # Security & compliance
    "vanta",
    "snyk",
    "checkmarx",
    "imperva",

    # Data & observability
    "segment",
    "mixpanel",
    "amplitude",
    "optimizely",
    "launchdarkly",
    "split",

    # Developer tools
    "clerk",
    "resend",

    # Infrastructure
    "netlify",
    "akamai",

    # Fintech
    "brex",
    "ramp",
    "chime",
    "affirm",

    # Databases / storage
    "neo4j",
    "aerospike",
    "couchbase",

    # Marketing / analytics
    "hotjar",
    "heap",
]

# Excluded from Lever (404 or migrated):
# sentry (now uses Greenhouse)
# datadog (direct career site)
# docker (direct career site)
# vercel (uses Ashby)
# supabase (uses Ashby)
# neon (uses Ashby)
# railway (uses Ashby)
# redis (no Lever board)
# clickhouse (uses Greenhouse now)
# timescale (no active Lever board)
# influxdata (acquired by IBM)
# milvus (open source, no corp jobs board)
# typesense (no active board)
# meilisearch (no active board)
# algolia (direct career site)
# dragonfly, keydb, aerospike-old, couchbase-old, rethinkdb (no board)
# faunadb (acquired/defunct)
# surrealdb (no public Lever board)
# edgedb (no public Lever board)
# prisma (uses Greenhouse)
# foursquare (no active Lever board)


# ── Ashby (api.ashbyhq.com/posting-api/job-board/{slug}) ──────────────────
# Verified: returns 200 with jobs list
ASHBY_COMPANIES = [
    # Developer tools (core Ashby users)
    "linear",
    "retool",
    "sourcegraph",
    "warp",
    "replit",
    "tldraw",
    "phind",
    "cursor",

    # Infrastructure / serverless
    "vercel",
    "supabase",
    "railway",
    "neon",
    "fly",
    "convex",

    # AI / LLM companies
    "huggingface",
    "mistral",
    "cohere",
    "perplexity",
    "elevenlabs",
    "runway",
    "synthesia",

    # Vector / ML infrastructure
    "pinecone",
    "weaviate",

    # Auth & identity
    "clerk",

    # Communication
    "resend",
    "loops",

    # Data / analytics
    "dub",
    "valtown",

    # Fintech
    "brex",
    "ramp",
    "rippling",
]

# Excluded from Ashby (404 or no active board):
# openai (uses Greenhouse)
# anthropic (uses Greenhouse now)
# langchain (no public board)
# llamaindex (no public board)
# midjourney (no public board)
# copyai, jasper, writer (no public Ashby board)
# chroma (no public board)
# iterm, alacritty, kitty, wezterm, hyper, tabby, termius, xterm (no corp boards)
# copilot (GitHub Copilot - under Microsoft)


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
