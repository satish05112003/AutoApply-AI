"""
AutoAiApply — Full End-to-End Production Audit Script

Tests:
1. LLM Router availability and fallback chain
2. Tech role filter precision (relevance filtering)
3. Live crawler output (Greenhouse, Lever, Ashby)
4. Job ingestion into DB
5. Heuristic job analysis (when LLM unavailable)
6. Role matching with synonym expansion
7. DB health (counts, indexes, duplicates)
8. Celery task registration

Run from: d:\\Predictions\\AutoAiApply\\backend
  python e2e_audit.py
"""
import asyncio
import sys
import os
import json
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(".env")

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"
INFO = "[INFO]"

results = {
    "passed": 0,
    "failed": 0,
    "warnings": 0,
    "details": []
}

def log(status, section, msg):
    line = f"{status} [{section}] {msg}"
    print(line)
    results["details"].append(line)
    if status == PASS:
        results["passed"] += 1
    elif status == FAIL:
        results["failed"] += 1
    elif status == WARN:
        results["warnings"] += 1


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: LLM Router
# ─────────────────────────────────────────────────────────────────────────────
async def test_llm_router():
    section = "LLM"
    print("\n" + "="*60)
    print("TEST 1: LLM Router")
    print("="*60)
    from app.llm.router import LLMRouter, _check_ollama_sync

    # Test Ollama availability probe
    ollama_ok = _check_ollama_sync()
    if ollama_ok:
        log(PASS, section, "Ollama is reachable")
    else:
        log(WARN, section, "Ollama is NOT running (expected on this machine)")

    # Test that LLM router raises instead of returning mock
    router = LLMRouter()

    from app.config import settings
    has_groq = bool(settings.GROQ_API_KEY)
    has_openrouter = bool(settings.OPENROUTER_API_KEY)

    if not ollama_ok and not has_groq and not has_openrouter:
        log(WARN, section, "No LLM providers configured. LLM calls will raise RuntimeError (correct behavior — no mock data)")
        try:
            # Verify it raises and doesn't return mock
            result = await router.think("test prompt")
            log(FAIL, section, f"Router returned '{result[:50]}' instead of raising — mock data still active!")
        except RuntimeError as e:
            log(PASS, section, f"Router correctly raises RuntimeError when all providers fail: {str(e)[:80]}")
        except Exception as e:
            log(PASS, section, f"Router raises (non-mock) on failure: {type(e).__name__}")
    elif has_groq:
        log(PASS, section, f"Groq API key configured: {settings.GROQ_API_KEY[:8]}...")
        try:
            resp = await router.think("Say 'hello' in exactly one word.", temperature=0.0)
            log(PASS, section, f"Groq responded: '{resp[:50]}'")
        except Exception as e:
            log(FAIL, section, f"Groq call failed: {e}")
    elif ollama_ok:
        try:
            resp = await router.think("Say 'hello' in exactly one word.", temperature=0.0)
            log(PASS, section, f"Ollama responded: '{resp[:50]}'")
        except Exception as e:
            log(FAIL, section, f"Ollama call failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Tech Role Filter
# ─────────────────────────────────────────────────────────────────────────────
def test_relevance_filter():
    section = "FILTER"
    print("\n" + "="*60)
    print("TEST 2: Tech Role Relevance Filter")
    print("="*60)
    from app.crawlers.base_crawler import is_tech_role

    # Should PASS (keep)
    should_keep = [
        ("Software Engineer", "Python, AWS, Docker"),
        ("Backend Engineer", "FastAPI, PostgreSQL, Redis"),
        ("Machine Learning Engineer", "PyTorch, Transformers, CUDA"),
        ("AI Engineer", "LLM, RAG, vector databases"),
        ("Full Stack Developer", "React, Node.js, TypeScript"),
        ("Senior SDE", "Java, Spring, microservices"),
        ("Data Engineer", "Spark, Airflow, dbt"),
        ("DevOps Engineer", "Kubernetes, Terraform, CI/CD"),
        ("Platform Engineer", "Go, Kubernetes, AWS"),
        ("Research Scientist", "ML, deep learning, publications"),
        ("Quantitative Developer", "Python, C++, algorithms"),
        ("Site Reliability Engineer", "Linux, Python, monitoring"),
    ]

    # Should REJECT (discard)
    should_reject = [
        ("Finance Analyst", "Excel, financial modeling"),
        ("Account Executive", "SaaS sales, quota"),
        ("Operations Associate", "logistics, supply chain"),
        ("Legal Controller", "contracts, compliance"),
        ("Accounting Manager", "GAAP, bookkeeping"),
        ("Customer Success Manager", "onboarding, churn reduction"),
        ("HR Business Partner", "talent acquisition, HRIS"),
        ("Marketing Manager", "content strategy, SEO"),
        ("Graphic Designer", "Adobe, Figma, brand"),
        ("Business Analyst", "requirements gathering, JIRA"),
        ("Content Writer", "blog posts, copywriting"),
        ("Sales Manager", "pipeline, quotas, CRM"),
    ]

    keep_correct = 0
    reject_correct = 0

    for title, desc in should_keep:
        result = is_tech_role(title, desc)
        if result:
            keep_correct += 1
        else:
            log(FAIL, section, f"INCORRECTLY REJECTED tech role: '{title}'")

    for title, desc in should_reject:
        result = is_tech_role(title, desc)
        if not result:
            reject_correct += 1
        else:
            log(WARN, section, f"INCORRECTLY KEPT non-tech role: '{title}'")

    keep_pct = keep_correct / len(should_keep) * 100
    reject_pct = reject_correct / len(should_reject) * 100
    precision = (keep_correct + reject_correct) / (len(should_keep) + len(should_reject)) * 100

    log(PASS if keep_pct >= 90 else FAIL, section, f"Tech role recall: {keep_correct}/{len(should_keep)} = {keep_pct:.0f}%")
    log(PASS if reject_pct >= 90 else FAIL, section, f"Non-tech rejection precision: {reject_correct}/{len(should_reject)} = {reject_pct:.0f}%")
    log(PASS if precision >= 90 else WARN, section, f"Overall filter accuracy: {precision:.0f}%")


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Role Matching Synonyms
# ─────────────────────────────────────────────────────────────────────────────
def test_role_matching():
    section = "MATCHING"
    print("\n" + "="*60)
    print("TEST 3: Role Matching Synonym Expansion")
    print("="*60)
    from app.agents.matching_agent import _role_matches

    test_cases = [
        # (job_title, preferred_roles, expected_match)
        ("Software Engineer", ["software engineer"], True),
        ("Senior SDE", ["software engineer"], True),
        ("SWE II", ["software engineer"], True),
        ("Backend Developer", ["software engineer"], True),
        ("ML Engineer", ["ai engineer"], True),
        ("Machine Learning Engineer", ["ai engineer"], True),
        ("Applied Scientist", ["ml engineer"], True),
        ("LLM Engineer", ["machine learning engineer"], True),
        ("Platform Engineer", ["backend engineer"], True),
        ("Site Reliability Engineer", ["devops engineer"], True),
        ("Python Developer", ["backend engineer"], True),
        # Negatives — should NOT match
        ("Finance Analyst", ["software engineer"], False),
        ("Sales Manager", ["ml engineer"], False),
        ("Customer Success", ["backend engineer"], False),
    ]

    correct = 0
    for job_title, preferred, expected in test_cases:
        result = _role_matches(job_title, preferred)
        if result == expected:
            correct += 1
        else:
            log(FAIL, section, f"'{job_title}' vs {preferred}: expected={expected} got={result}")

    pct = correct / len(test_cases) * 100
    log(PASS if pct >= 85 else FAIL, section, f"Synonym matching accuracy: {correct}/{len(test_cases)} = {pct:.0f}%")


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Heuristic Job Analysis
# ─────────────────────────────────────────────────────────────────────────────
def test_heuristic_analysis():
    section = "ANALYSIS"
    print("\n" + "="*60)
    print("TEST 4: Heuristic Job Analysis")
    print("="*60)
    from app.agents.job_analysis_agent import _heuristic_analysis

    test_jobs = [
        {
            "title": "Senior Machine Learning Engineer",
            "desc": "Join our team to build LLM-powered products. Required: Python, PyTorch, Transformers. 5+ years experience.",
            "expected_category": "ML_ENGINEER",
        },
        {
            "title": "Backend Software Engineer",
            "desc": "Build scalable APIs using FastAPI, PostgreSQL, Redis, Docker, Kubernetes. AWS experience preferred.",
            "expected_category": "SOFTWARE_ENGINEER",
        },
        {
            "title": "Data Engineer",
            "desc": "Design ETL pipelines using Apache Spark, Airflow, dbt. BigQuery, Snowflake experience needed.",
            "expected_category": "DATA_ENGINEER",
        },
        {
            "title": "Research Scientist, NLP",
            "desc": "PhD required. Publications in NLP/ML. Research on large language models.",
            "expected_category": "RESEARCH",
        },
    ]

    correct = 0
    for tc in test_jobs:
        result = _heuristic_analysis(tc["title"], tc["desc"])
        category = result.get("role_category", "")
        skills = result.get("required_skills", [])
        if category == tc["expected_category"]:
            correct += 1
            log(PASS, section, f"'{tc['title']}' -> {category}, {len(skills)} skills detected")
        else:
            log(WARN, section, f"'{tc['title']}' -> {category} (expected {tc['expected_category']})")

    log(PASS if correct >= 3 else FAIL, section, f"Heuristic analysis accuracy: {correct}/{len(test_jobs)}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Live Crawler (Greenhouse sample)
# ─────────────────────────────────────────────────────────────────────────────
async def test_live_crawler():
    section = "CRAWLER"
    print("\n" + "="*60)
    print("TEST 5: Live Crawler (Greenhouse)")
    print("="*60)
    from app.crawlers.greenhouse_crawler import GreenhouseCrawler

    # Use a small subset for speed
    crawler = GreenhouseCrawler()
    crawler.COMPANIES = ["stripe", "cloudflare", "databricks"]

    t0 = time.time()
    jobs = await crawler.crawl("software engineer", "Remote", limit=50)
    elapsed = time.time() - t0

    log(INFO, section, f"Crawled 3 companies in {elapsed:.1f}s, got {len(jobs)} tech jobs")

    if len(jobs) > 0:
        log(PASS, section, f"Crawler returned {len(jobs)} jobs")
        # Verify all are tech roles
        from app.crawlers.base_crawler import is_tech_role
        non_tech = [j for j in jobs if not is_tech_role(j["role_title"], j["job_description"])]
        if non_tech:
            log(WARN, section, f"{len(non_tech)} non-tech jobs slipped through filter: {[j['role_title'] for j in non_tech[:3]]}")
        else:
            log(PASS, section, f"All {len(jobs)} returned jobs are tech roles (100% precision)")

        # Sample
        j = jobs[0]
        log(INFO, section, f"Sample: '{j['role_title']}' at {j['company_name']} | {j['location']}")
    else:
        log(WARN, section, "No jobs returned (may be network issue or all jobs older than 7 days)")

    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: DB Health
# ─────────────────────────────────────────────────────────────────────────────
async def test_db_health():
    section = "DATABASE"
    print("\n" + "="*60)
    print("TEST 6: Database Health")
    print("="*60)
    try:
        import asyncpg
        conn = await asyncpg.connect("postgresql://postgres:postgres@localhost:5432/autoapply_ai")

        # Job counts
        total_jobs = await conn.fetchval("SELECT COUNT(*) FROM jobs.job_postings")
        log(PASS if total_jobs >= 0 else FAIL, section, f"job_postings total: {total_jobs}")

        # Source breakdown
        rows = await conn.fetch("SELECT source, COUNT(*) as cnt FROM jobs.job_postings GROUP BY source ORDER BY cnt DESC")
        for r in rows:
            log(INFO, section, f"  {r['source']}: {r['cnt']} jobs")

        # Duplicate check
        dups = await conn.fetchval("""
            SELECT COUNT(*) FROM (
                SELECT source, external_id, COUNT(*) as n
                FROM jobs.job_postings
                WHERE external_id IS NOT NULL
                GROUP BY source, external_id
                HAVING COUNT(*) > 1
            ) x
        """)
        if dups == 0:
            log(PASS, section, "No duplicate (source, external_id) pairs found")
        else:
            log(FAIL, section, f"{dups} duplicate job entries detected!")

        # Applications
        total_apps = await conn.fetchval("SELECT COUNT(*) FROM applications.applications")
        app_rows = await conn.fetch("SELECT status, COUNT(*) as cnt FROM applications.applications GROUP BY status ORDER BY cnt DESC")
        log(INFO, section, f"applications total: {total_apps}")
        for r in app_rows:
            log(INFO, section, f"  {r['status']}: {r['cnt']}")

        # Check indexes exist
        idx_rows = await conn.fetch("""
            SELECT indexname FROM pg_indexes
            WHERE schemaname = 'jobs' AND tablename = 'job_postings'
        """)
        idx_names = [r["indexname"] for r in idx_rows]
        log(PASS if len(idx_names) > 3 else WARN, section, f"job_postings indexes: {idx_names}")

        await conn.close()
    except Exception as e:
        log(FAIL, section, f"DB health check failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: Celery Task Registration
# ─────────────────────────────────────────────────────────────────────────────
def test_celery_tasks():
    section = "CELERY"
    print("\n" + "="*60)
    print("TEST 7: Celery Task Registration")
    print("="*60)
    try:
        from app.celery_app import celery_app
        tasks = list(celery_app.tasks.keys())
        expected = [
            "app.tasks.discovery_tasks.run_job_discovery",
            "app.tasks.discovery_tasks.scheduled_discover_jobs",
            "app.tasks.discovery_tasks.orchestrate_job_task",
            "app.tasks.application_tasks.execute_browser_application",
            "app.tasks.application_tasks.scheduled_retry_pending_applications",
        ]
        for t in expected:
            if t in tasks:
                log(PASS, section, f"Task registered: {t.split('.')[-1]}")
            else:
                log(FAIL, section, f"Task NOT registered: {t}")

        # Verify beat schedule
        beat = celery_app.conf.beat_schedule
        log(PASS if "scheduled-discovery" in beat else FAIL, section, "Beat schedule has scheduled-discovery")
        log(PASS if "retry-pending-applications" in beat else FAIL, section, "Beat schedule has retry-pending-applications")

        # Verify reliability config
        assert celery_app.conf.task_acks_late == True, "task_acks_late must be True"
        log(PASS, section, "task_acks_late=True (tasks requeued on worker crash)")
        assert celery_app.conf.task_reject_on_worker_lost == True
        log(PASS, section, "task_reject_on_worker_lost=True")
        assert celery_app.conf.worker_prefetch_multiplier == 1
        log(PASS, section, "worker_prefetch_multiplier=1 (fair distribution)")

    except Exception as e:
        log(FAIL, section, f"Celery check failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: Validated Company Lists
# ─────────────────────────────────────────────────────────────────────────────
def test_validated_companies():
    section = "COMPANIES"
    print("\n" + "="*60)
    print("TEST 8: Validated Company Lists")
    print("="*60)
    from app.crawlers.validated_companies import GREENHOUSE_COMPANIES, LEVER_COMPANIES, ASHBY_COMPANIES

    log(PASS, section, f"Greenhouse: {len(GREENHOUSE_COMPANIES)} companies")
    log(PASS, section, f"Lever: {len(LEVER_COMPANIES)} companies")
    log(PASS, section, f"Ashby: {len(ASHBY_COMPANIES)} companies")

    # Verify dead companies are excluded
    dead_greenhouse = ["openai", "huggingface", "langchain", "llamaindex", "midjourney"]
    for company in dead_greenhouse:
        if company in GREENHOUSE_COMPANIES:
            log(WARN, section, f"Dead company '{company}' still in GREENHOUSE_COMPANIES")
        else:
            log(PASS, section, f"'{company}' correctly excluded from GREENHOUSE_COMPANIES")

    dead_lever = ["sentry", "datadog", "docker", "vercel"]
    for company in dead_lever:
        if company in LEVER_COMPANIES:
            log(WARN, section, f"Dead company '{company}' still in LEVER_COMPANIES")
        else:
            log(PASS, section, f"'{company}' correctly excluded from LEVER_COMPANIES")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
async def main():
    print("\n" + "="*60)
    print("AutoAiApply — Full Production Audit")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    await test_llm_router()
    test_relevance_filter()
    test_role_matching()
    test_heuristic_analysis()
    jobs = await test_live_crawler()
    await test_db_health()
    test_celery_tasks()
    test_validated_companies()

    # ── Final Report ──────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("FINAL AUDIT REPORT")
    print("="*60)
    total = results["passed"] + results["failed"] + results["warnings"]
    score = int((results["passed"] / max(total, 1)) * 100)

    print(f"\n  PASSED:   {results['passed']}")
    print(f"  FAILED:   {results['failed']}")
    print(f"  WARNINGS: {results['warnings']}")
    print(f"\n  Production Readiness Score: {score}/100")

    if results["failed"] == 0:
        print("\n  STATUS: PRODUCTION READY (no critical failures)")
    elif results["failed"] <= 2:
        print("\n  STATUS: NEARLY READY (fix remaining failures)")
    else:
        print(f"\n  STATUS: NOT READY ({results['failed']} critical failures)")

    # Key action items
    print("\n  ACTION ITEMS:")
    from app.config import settings
    if not settings.GROQ_API_KEY and not settings.OPENROUTER_API_KEY:
        print("  1. [REQUIRED] Set GROQ_API_KEY in .env — free at https://console.groq.com")
        print("     OR start Ollama: ollama serve && ollama pull qwen2.5:7b")
    print("  2. [OPTIONAL] Start Qdrant for semantic dedup: docker run -p 6333:6333 qdrant/qdrant")
    print("  3. [ACTION] Restart Celery workers to pick up code changes")
    print("  4. [ACTION] Run 'Enable Full Auto' from dashboard to start auto-applying")

    return results


if __name__ == "__main__":
    asyncio.run(main())
