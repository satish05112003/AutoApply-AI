import hashlib
import logging
import math
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from uuid import UUID
from sqlalchemy import select, update, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.jobs import JobPosting, JobDiscoveryLog
from app.utils.embedding_utils import get_embedding, get_embeddings_batch
from app.integrations.vector_db_client import qdrant_client

logger = logging.getLogger("autoapply_ai.services.job")

class JobService:
    @staticmethod
    def calculate_freshness_score(source: str, posting_date: Optional[datetime]) -> float:
        """
        Calculate freshness score using the decay formula:
        freshness_score = base_score * e^(-0.1 * hours_since_posting) * source_weight
        """
        if not posting_date:
            posting_date = datetime.now(timezone.utc)
            
        if posting_date.tzinfo is None:
            posting_date = posting_date.replace(tzinfo=timezone.utc)
        hours_since_posting = (datetime.now(timezone.utc) - posting_date).total_seconds() / 3600.0
        
        base_score = 100.0
        time_decay = math.exp(-0.05 * hours_since_posting) # decay of 0.05 per hour is softer than 0.1
        
        # Source weights
        source_weights = {
            "linkedin": 1.00,
            "naukri": 0.95,
            "wellfound": 1.00,
            "unstop": 0.90,
            "internshala": 0.85
        }
        weight = source_weights.get(source.lower(), 0.90)
        
        return min(100.0, base_score * time_decay * weight)

    @staticmethod
    def generate_job_hash(company_name: str, role_title: str, source: str, external_id: str) -> str:
        """Generate a unique SHA256 deduplication hash for a job posting."""
        raw_str = f"{company_name.lower().strip()}|{role_title.lower().strip()}|{source.lower().strip()}|{external_id.strip()}"
        return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

    @staticmethod
    async def ingest_job(db: AsyncSession, job_data: Dict[str, Any]) -> Optional[JobPosting]:
        """Ingest a single job posting, performing deduplication and scoring."""
        company_name = job_data["company_name"]
        role_title = job_data["role_title"]
        source = job_data["source"]
        external_id = job_data["external_id"]
        
        # Check if job was posted within the last 7 days (relaxed from 24h to allow ATS boards with stale timestamps)
        post_date = job_data.get("posting_date")
        if not post_date:
            post_date = datetime.now(timezone.utc)
        if post_date.tzinfo is None:
            post_date = post_date.replace(tzinfo=timezone.utc)
        else:
            post_date = post_date.astimezone(timezone.utc)
            
        now = datetime.now(timezone.utc)
        age = now - post_date
        if age > timedelta(days=7):
            logger.info(f"Job Ingestion: Job is older than 7 days ({age.total_seconds() / 3600:.1f} hours). Skipping: {role_title} at {company_name}")
            return None

        # 1. Deduplicate using source, external_id, source_url
        duplicate_conditions = []
        if external_id:
            duplicate_conditions.append(JobPosting.external_id == external_id)
        if job_data.get("source_url"):
            duplicate_conditions.append(JobPosting.source_url == job_data["source_url"])
            
        if duplicate_conditions:
            stmt = select(JobPosting).where(
                (JobPosting.source == source) & or_(*duplicate_conditions)
            )
            res = await db.execute(stmt)
            if res.scalars().first():
                logger.info(f"Job Ingestion: Duplicate job detected (source/external_id/source_url). Skipping: {role_title} at {company_name}")
                return None

        # Generate unique hash for exact duplicate checks
        job_hash = JobService.generate_job_hash(company_name, role_title, source, external_id)
        hash_stmt = select(JobPosting).where(JobPosting.job_hash == job_hash)
        hash_res = await db.execute(hash_stmt)
        if hash_res.scalars().first():
            logger.info(f"Job Ingestion: Duplicate exact job detected (hash match). Skipping: {role_title} at {company_name}")
            return None

        # 2. Extract embedding for semantic duplicates check in Qdrant
        job_desc = job_data.get("job_description", "")
        embedding = get_embedding(job_desc)
        
        # Semantic duplicate search using Qdrant (cosine similarity > 0.95)
        try:
            similar_jobs = qdrant_client.search_similar(
                collection_name="jobs",
                query_vector=embedding,
                limit=1
            )
            if similar_jobs and similar_jobs[0]["score"] > 0.95:
                # Same role description from same company -> skip
                sim_payload = similar_jobs[0]["payload"]
                if sim_payload.get("company_name", "").lower() == company_name.lower():
                    logger.info(f"Job Ingestion: Semantic duplicate job detected (>0.95 similarity) for company '{company_name}'. Skipping.")
                    return None
        except Exception as e:
            logger.warning(f"Semantic duplicate check failed: {e}")

        # 3. Calculate freshness (post_date already resolved above)
        freshness = JobService.calculate_freshness_score(source, post_date)

        # 4. Insert into database
        new_job = JobPosting(
            external_id=external_id,
            source=source,
            source_url=job_data["source_url"],
            company_name=company_name,
            company_normalized=company_name.lower().strip(),
            role_title=role_title,
            role_normalized=role_title.lower().strip(),
            location=job_data.get("location"),
            is_remote=job_data.get("is_remote", False),
            job_description=job_desc,
            posting_date=post_date,
            freshness_score=freshness,
            job_hash=job_hash,
            job_description_embedding=embedding
        )
        db.add(new_job)
        await db.commit()
        await db.refresh(new_job)

        # 5. Insert vector into Qdrant collection "jobs"
        try:
            qdrant_client.upsert_vector(
                collection_name="jobs",
                point_id=str(new_job.id),
                vector=embedding,
                payload={
                    "job_id": str(new_job.id),
                    "company_name": company_name,
                    "role_title": role_title,
                    "location": job_data.get("location", ""),
                    "source": source
                }
            )
        except Exception as e:
            logger.error(f"Failed upserting job to Qdrant collection: {e}")

        return new_job

    @staticmethod
    async def ingest_jobs_batch(db: AsyncSession, jobs_data: List[Dict[str, Any]]) -> List[JobPosting]:
        """Ingest a list of job postings in batch, performing deduplication and scoring."""
        if not jobs_data:
            return []
            
        source = jobs_data[0]["source"]
        
        # 1. Filter out jobs older than 7 days
        fresh_jobs = []
        now = datetime.now(timezone.utc)
        for jd in jobs_data:
            post_date = jd.get("posting_date")
            if not post_date:
                post_date = now
            if post_date.tzinfo is None:
                post_date = post_date.replace(tzinfo=timezone.utc)
            else:
                post_date = post_date.astimezone(timezone.utc)
                
            age = now - post_date
            if age > timedelta(days=7):
                logger.info(f"Job Ingestion: Job is older than 7 days ({age.total_seconds() / 3600:.1f} hours). Skipping: {jd['role_title']} at {jd['company_name']}")
                continue
            
            # Save resolved post_date back to dict
            jd["_resolved_post_date"] = post_date
            fresh_jobs.append(jd)
            
        if not fresh_jobs:
            return []
            
        # 2. Filter out duplicates WITHIN the batch itself
        unique_jobs_map = {}
        for jd in fresh_jobs:
            company_name = jd["company_name"]
            role_title = jd["role_title"]
            ext_id = jd["external_id"]
            job_hash = JobService.generate_job_hash(company_name, role_title, source, ext_id)
            jd["_job_hash"] = job_hash
            
            # Deduplicate by hash
            unique_jobs_map[job_hash] = jd
            
        unique_jobs_list = list(unique_jobs_map.values())
        
        # 3. Query existing jobs in the database by external_id, source_url, and job_hash in a single query
        external_ids = [jd["external_id"] for jd in unique_jobs_list if jd.get("external_id")]
        source_urls = [jd["source_url"] for jd in unique_jobs_list if jd.get("source_url")]
        job_hashes = [jd["_job_hash"] for jd in unique_jobs_list]
        
        dup_conditions = []
        if external_ids:
            dup_conditions.append(JobPosting.external_id.in_(external_ids))
        if source_urls:
            dup_conditions.append(JobPosting.source_url.in_(source_urls))
        if job_hashes:
            dup_conditions.append(JobPosting.job_hash.in_(job_hashes))
            
        existing_hashes = set()
        existing_external_ids = set()
        existing_source_urls = set()
        
        if dup_conditions:
            stmt = select(JobPosting).where(
                (JobPosting.source == source) & or_(*dup_conditions)
            )
            res = await db.execute(stmt)
            existing_jobs = res.scalars().all()
            for ej in existing_jobs:
                existing_hashes.add(ej.job_hash)
                if ej.external_id:
                    existing_external_ids.add(ej.external_id)
                if ej.source_url:
                    existing_source_urls.add(ej.source_url)
                    
        # Filter out jobs that match database duplicates
        candidate_jobs = []
        for jd in unique_jobs_list:
            h = jd["_job_hash"]
            ext_id = jd["external_id"]
            url = jd.get("source_url")
            
            if h in existing_hashes:
                logger.debug(f"Job Ingestion: Duplicate job by hash. Skipping: {jd['role_title']} at {jd['company_name']}")
                continue
            if ext_id and ext_id in existing_external_ids:
                logger.debug(f"Job Ingestion: Duplicate job by external_id. Skipping: {jd['role_title']} at {jd['company_name']}")
                continue
            if url and url in existing_source_urls:
                logger.debug(f"Job Ingestion: Duplicate job by source_url. Skipping: {jd['role_title']} at {jd['company_name']}")
                continue
                
            candidate_jobs.append(jd)
            
        if not candidate_jobs:
            return []
            
        # 4. Generate embeddings in batch
        descriptions = [jd.get("job_description", "") for jd in candidate_jobs]
        embeddings = get_embeddings_batch(descriptions)
        
        # 5. Semantic duplicate check in Qdrant in batch
        final_jobs_to_insert = []
        for i, jd in enumerate(candidate_jobs):
            emb = embeddings[i]
            jd["_embedding"] = emb
            
            # Semantic duplicate search using Qdrant (cosine similarity > 0.95)
            is_semantic_duplicate = False
            if qdrant_client.is_available:
                try:
                    similar_jobs = qdrant_client.search_similar(
                        collection_name="jobs",
                        query_vector=emb,
                        limit=1
                    )
                    if similar_jobs and similar_jobs[0]["score"] > 0.95:
                        sim_payload = similar_jobs[0]["payload"]
                        if sim_payload.get("company_name", "").lower() == jd["company_name"].lower():
                            logger.info(f"Job Ingestion: Semantic duplicate job detected (>0.95 similarity) for company '{jd['company_name']}'. Skipping.")
                            is_semantic_duplicate = True
                except Exception as e:
                    logger.warning(f"Semantic duplicate check failed: {e}")
                    
            if not is_semantic_duplicate:
                final_jobs_to_insert.append(jd)
                
        if not final_jobs_to_insert:
            return []
            
        # 6. Create JobPosting objects, calculate freshness, and add to DB
        new_jobs = []
        for jd in final_jobs_to_insert:
            freshness = JobService.calculate_freshness_score(source, jd["_resolved_post_date"])
            new_job = JobPosting(
                external_id=jd["external_id"],
                source=source,
                source_url=jd["source_url"],
                company_name=jd["company_name"],
                company_normalized=jd["company_name"].lower().strip(),
                role_title=jd["role_title"],
                role_normalized=jd["role_title"].lower().strip(),
                location=jd.get("location"),
                is_remote=jd.get("is_remote", False),
                job_description=jd.get("job_description", ""),
                posting_date=jd["_resolved_post_date"],
                freshness_score=freshness,
                job_hash=jd["_job_hash"],
                job_description_embedding=jd["_embedding"]
            )
            new_jobs.append(new_job)
            db.add(new_job)
            
        await db.commit()
        
        # Refresh and construct points data for Qdrant batch upsert
        qdrant_points = []
        for nj in new_jobs:
            await db.refresh(nj)
            qdrant_points.append({
                "id": str(nj.id),
                "vector": nj.job_description_embedding,
                "payload": {
                    "job_id": str(nj.id),
                    "company_name": nj.company_name,
                    "role_title": nj.role_title,
                    "location": nj.location or "",
                    "source": source
                }
            })
            
        # 7. Batch upsert vectors to Qdrant
        if qdrant_points and qdrant_client.is_available:
            try:
                qdrant_client.upsert_vectors_batch("jobs", qdrant_points)
            except Exception as e:
                logger.error(f"Failed upserting batch jobs to Qdrant collection: {e}")
                
        return new_jobs

    @staticmethod
    async def get_job_feed(db: AsyncSession, limit: int = 50) -> List[JobPosting]:
        """Fetch active jobs feed sorted by discovered_at descending."""
        stmt = select(JobPosting).where(JobPosting.is_active == True).order_by(JobPosting.discovered_at.desc()).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_job_by_id(db: AsyncSession, job_id: UUID) -> Optional[JobPosting]:
        stmt = select(JobPosting).where(JobPosting.id == job_id)
        result = await db.execute(stmt)
        return result.scalars().first()
