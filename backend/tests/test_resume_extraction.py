"""
Integration tests for the structured resume extraction flow using Nagalla Satish's resume.
"""

import os
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.main import app


def _get_satish_resume_bytes() -> bytes:
    """Retrieve Satish's resume from storage, or generate it dynamically if missing."""
    resume_path = r"d:\Predictions\AutoAiApply\backend\app\storage\resumes\dacfa2f5-0854-44e5-9e82-521e6eca3ff9\f7812f6d-4e58-471b-8044-ed59004dd300.pdf"
    
    if os.path.exists(resume_path):
        with open(resume_path, "rb") as f:
            return f.read()
            
    # Fallback: Generate it dynamically
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=595, height=1500)
    page.insert_text((50, 50), """
    NAGALLA SATISH
    Kakinada,Andhra Pradesh
     +916302394400
    R satishnagalla0@gmail.com
     satish nagalla
     satish05112003
    EDUCATION
    National Institute of Technology Agartala
    2022  2026
    B-TECH - Electronics and Communication Engineering
    Tripura, India
    Sri Sai Aditya Junior College
    2020  2022
    Intermediate - MPC
    Kakinada,India
    PROJECTS
    Polymarket AI Trading Agent W | Python, WebSocket, XGBoost, LightGBM, TG Bot
    2026
     Built a real-time BTC trading engine for Polymarket using live Binance WebSocket price data and short-term
    market prediction models.
     Developed a backend system with live orderbook tracking, WebSocket communication, risk management, and
    replay/backtesting features using Python and aiohttp.
     Used XGBoost, LightGBM, Random Forest, and Logistic Regression models to predict BTC price movement
    in 5-minute markets, achieving AUC scores up to 0.9501.
     Implemented automated trade execution, live data processing, and real-time monitoring with dashboard and
    safety controls.
    AI-Based Hate Speech and Abusive Language Detection W | Chrome Extension, NLTK
    2025
     Developed a real-time hate speech detection system for social media platforms such as Twitter, YouTube and
    Instagram. Implemented text preprocessing, TF-IDF vectorization, and machine learning models to classify
    content as Hate, Offensive, or Neutral with high accuracy. Integrated the model with a FastAPI backend and a
    Chrome Extension for real-time detection and inline labeling of comments and posts.
     Live site here
    EVM Wallet Reputation & Risk Analyzer W | Next.js, Tailwind CSS, Wagmi, Viem, Base RPC
    2025
     Built and deployed Base Pulse, a read-only on-chain analytics mini app that analyzes EVM wallet activity on
    the Base chain. Generates wallet reputation scores and detects strong compromise risk patterns using
    transaction history and behavior signals. Deployed as a Mini App on Farcaster and Base App with a
    fast, clean UI for public use.
     Live site here
    INTERNSHIP
    TechnoHacksW
    JULY 2024  AUGUST 2024
    Machine Learning Intern
    Remote
     Completed a Machine Learning internship at TechnoHacks EduTech, gaining hands-on experience in data
    preprocessing, model building, and predictive analysis using Python and machine learning algorithms.
    TECHNICAL SKILLS
    Languages: C,C++,Python
    Developer Tools: VS Code, Matlab, HFSS, Docker, Jupyter Notebook, Railway, Cursor, Claude Code,
    Antigravity, OpenClaw, Zed
    Technologies:Git, GitHub APIs, REST APIs, WebSockets, Machine Learning, XGBoost, LightGBM,
    Scikit-learn, Pandas, NumPy, Web3, EVM
    CS Fundamentals: Data Structures,Algorithms, OOPs, Computer Networks
    Web Development: HTML, CSS, JavaScript, React.js, Next.js, Tailwind CSS, REST APIs, Wagmi, Viem
    ACHIEVEMENTS
     Secured top 3.7 percentile in JEE Mains 2022
     Selected to receive a scholarship from the Foundation for Excellence for academic performance
     Selected as a volunteer for Zama, a privacy-focused Web3 company that raised $150M at a $1.2B valuation
    EXTRACURRICULAR AND HOBBIES
    Extracurricular: Volunteered in college events, Content creator, Member of the Art Club in school.
    Hobbies: Vibe Coding, Tech Content Writing, Photography, Gym/Fitness.
    """)
    return doc.write()


def _sync_cleanup(user_uuid: str) -> None:
    """Delete test user data and resume data from database."""
    from app.config import settings

    sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(sync_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(
            text("DELETE FROM profile.resume_sections WHERE resume_id IN (SELECT id FROM profile.resumes WHERE user_id = :uid)"),
            {"uid": user_uuid}
        )
        conn.execute(text("DELETE FROM profile.resumes WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.education WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.experience WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.skills WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.projects WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.achievements WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM auth.sessions WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.preferences WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM profile.candidate_profiles WHERE user_id = :uid"), {"uid": user_uuid})
        conn.execute(text("DELETE FROM auth.users WHERE id = :uid"), {"uid": user_uuid})
    engine.dispose()


def test_resume_extraction_pipeline():
    """Verify that uploading a real resume parses all candidate details correctly instead of returning N/As."""
    unique_id = uuid.uuid4().hex[:6]
    test_email = f"extraction_test_{unique_id}@autoapply.ai"
    test_password = "SecurePassword123!"
    test_name = f"Extraction Tester {unique_id}"

    user_uuid = None
    pdf_bytes = _get_satish_resume_bytes()

    with TestClient(app, raise_server_exceptions=True) as client:
        # 1. Register candidate user
        reg_res = client.post(
            "/api/v1/auth/register",
            json={"email": test_email, "password": test_password, "full_name": test_name},
        )
        assert reg_res.status_code == 201, f"Registration failed: {reg_res.text}"
        user_uuid = reg_res.json()["id"]

        # 2. Login
        login_res = client.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": test_password},
        )
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        access_token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # 3. Upload Satish's Resume PDF
        upload_res = client.post(
            "/api/v1/resumes/upload",
            headers=headers,
            files={"file": ("satish_resume.pdf", pdf_bytes, "application/pdf")},
            data={"resume_name": "Nagalla Satish Resume", "is_primary": "true"},
        )
        assert upload_res.status_code == 200, f"Upload failed: {upload_res.text}"
        
        resume_data = upload_res.json()
        resume_id = resume_data["id"]
        parsed_json = resume_data["parsed_json"]
        
        # 4. Verify Structured Extraction Fields
        extracted = parsed_json
        assert extracted["full_name"] == "NAGALLA SATISH"
        assert extracted["email"] == "satishnagalla0@gmail.com"
        assert len(extracted["projects"]) == 3
        assert len(extracted["experience"]) == 1
        assert len(extracted["skills"]) > 15
        assert len(extracted["summary"]) > 120
        assert not extracted["projects"][0]["project_name"].startswith("•")
        assert "2026" not in extracted["projects"][0]["tech_stack"][0]
        assert extracted["education"][0]["start_year"] == 2022
        assert extracted["education"][0]["end_year"] == 2026

        # Additional specific matches
        skills_upper = [s.upper() for s in extracted["skills"]]
        assert "PYTHON" in skills_upper
        assert "FASTAPI" in skills_upper
        assert "XGBOOST" in skills_upper
        assert "NEXT.JS" in skills_upper

        project_names = [p["project_name"].upper() for p in extracted["projects"]]
        assert any("POLYMARKET" in p for p in project_names)
        assert any("HATE SPEECH" in p for p in project_names)
        assert any("WALLET REPUTATION" in p for p in project_names)

        education_names = [e["institution_name"].upper() for e in extracted["education"]]
        assert any("NATIONAL INSTITUTE OF TECHNOLOGY" in e or "NIT" in e for e in education_names)

        experience_names = [exp["company_name"].upper() for exp in extracted["experience"]]
        assert any("TECHNOHACKS" in exp for exp in experience_names)

        achievements_upper = [a.upper() for a in extracted["achievements"]]
        assert any("JEE MAINS" in a for a in achievements_upper)
        assert any("ZAMA" in a for a in achievements_upper)

        # 5. Verify the candidate's profile is updated in candidate_profiles and auth.users tables
        me_res = client.get("/api/v1/auth/me", headers=headers)
        assert me_res.status_code == 200
        # The user's name should have bootstrapped from resume
        assert me_res.json()["full_name"].upper() == "NAGALLA SATISH"

        # 6. Delete Resume
        del_res = client.delete(f"/api/v1/resumes/{resume_id}", headers=headers)
        assert del_res.status_code == 200

    # 7. Cleanup
    if user_uuid:
        _sync_cleanup(user_uuid)
