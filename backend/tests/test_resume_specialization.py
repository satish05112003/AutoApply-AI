import pytest
from app.utils.resume_parser import detect_resume_type

def test_detect_resume_type_embedded():
    skills = ["Arduino", "Microcontroller", "Firmware", "Sensors", "Bluetooth"]
    projects = [
        {
            "project_name": "Smart Home IoT", 
            "description": "Built an IoT node with Bluetooth communication and temperature sensors", 
            "tech_stack": ["C", "C++"]
        }
    ]
    assert detect_resume_type(skills, projects) == "EMBEDDED_SYSTEMS"

def test_detect_resume_type_ai_ml():
    skills = ["Python", "TensorFlow", "PyTorch", "Deep Learning"]
    projects = [
        {
            "project_name": "Price Predictor", 
            "description": "Trained predictive analytics XGBoost models", 
            "tech_stack": ["Scikit-learn", "Pandas"]
        }
    ]
    assert detect_resume_type(skills, projects) == "AI_ML"

def test_detect_resume_type_web3():
    skills = ["Solidity", "Smart Contracts", "Web3", "Ethereum"]
    projects = [
        {
            "project_name": "DeFi Swap", 
            "description": "Developed EVM compatible automated market maker and smart contract routing", 
            "tech_stack": ["Viem", "Wagmi", "Base"]
        }
    ]
    assert detect_resume_type(skills, projects) == "WEB3"

def test_detect_resume_type_full_stack():
    skills = ["React", "Next.js", "TypeScript", "Backend", "Frontend"]
    projects = [
        {
            "project_name": "SaaS Platform", 
            "description": "Built a web app with next.js, react frontend, and fastapi backend.", 
            "tech_stack": ["Tailwind", "Docker", "MERN"]
        }
    ]
    assert detect_resume_type(skills, projects) == "FULL_STACK"

def test_detect_resume_type_generalist():
    skills = ["Git", "VS Code", "Windows"]
    projects = [
        {
            "project_name": "Simple Helper", 
            "description": "Wrote some helper files for local automation", 
            "tech_stack": []
        }
    ]
    assert detect_resume_type(skills, projects) == "GENERALIST"
