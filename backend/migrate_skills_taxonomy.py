import asyncio
import sys
from collections import defaultdict
from sqlalchemy import select, delete, text
from app.database import SessionLocal, engine
from app.models.profile import Skill
from app.utils.resume_parser import get_skill_category, normalize_skill_name, CATEGORY_DISPLAY_MAP

async def run_migration():
    print("Starting Skills Taxonomy Reclassification & Normalization Pass...")
    async with SessionLocal() as session:
        # 1. Fetch all skills
        stmt = select(Skill)
        result = await session.execute(stmt)
        all_skills = list(result.scalars().all())
        print(f"Loaded {len(all_skills)} total skills from database.")
        
        # 2. Group by user_id to resolve unique constraint conflicts during normalization
        user_skills = defaultdict(list)
        for s in all_skills:
            user_skills[s.user_id].append(s)
            
        total_deleted = 0
        total_updated = 0
        
        for user_id, skill_list in user_skills.items():
            seen_normalized = {}
            for s in skill_list:
                new_name = normalize_skill_name(s.skill_name)
                norm_key = new_name.lower()
                
                cat_code = get_skill_category(new_name)
                new_category = CATEGORY_DISPLAY_MAP.get(cat_code, "Other")
                
                if norm_key in seen_normalized:
                    # Duplicate detected! Merge s into existing_s and mark s for deletion
                    existing_s = seen_normalized[norm_key]
                    
                    # Merge Years of Experience
                    if s.years_of_experience and existing_s.years_of_experience:
                        existing_s.years_of_experience = max(s.years_of_experience, existing_s.years_of_experience)
                    elif s.years_of_experience:
                        existing_s.years_of_experience = s.years_of_experience
                        
                    # Merge Proficiency Level
                    levels = {"ADVANCED": 3, "INTERMEDIATE": 2, "BEGINNER": 1, "UNKNOWN": 0, None: 0}
                    curr_lvl = levels.get(existing_s.proficiency_level or "UNKNOWN")
                    new_lvl = levels.get(s.proficiency_level or "UNKNOWN")
                    if new_lvl > curr_lvl:
                        existing_s.proficiency_level = s.proficiency_level
                        
                    # Merge is_primary
                    existing_s.is_primary = existing_s.is_primary or s.is_primary
                    
                    # Ensure name and category are standard
                    existing_s.skill_name = new_name
                    existing_s.category = new_category
                    
                    # Delete the duplicate record
                    await session.delete(s)
                    total_deleted += 1
                else:
                    seen_normalized[norm_key] = s
                    if s.skill_name != new_name or s.category != new_category:
                        s.skill_name = new_name
                        s.category = new_category
                        session.add(s)
                        total_updated += 1
                        
        # 3. Commit transactions
        await session.commit()
        print(f"Migration completed. Updates: {total_updated}, Deletes (duplicates merged): {total_deleted}")
        
        # 4. Print verification stats
        verify_stmt = text("SELECT category, COUNT(*) FROM profile.skills GROUP BY category ORDER BY count DESC;")
        verify_res = await session.execute(verify_stmt)
        print("\nSQL Verification Results (profile.skills grouped by category):")
        for row in verify_res.fetchall():
            print(f"Category: {row[0]:<30} | Count: {row[1]}")
            
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(run_migration())
