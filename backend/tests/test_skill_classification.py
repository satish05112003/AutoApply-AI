import pytest
from app.utils.resume_parser import get_skill_category

def test_skill_classification_pytorch():
    assert get_skill_category("PyTorch") == "AI_ML"

def test_skill_classification_embedded_c():
    assert get_skill_category("Embedded C") == "EMBEDDED_SYSTEMS"

def test_skill_classification_arm_processor():
    assert get_skill_category("ARM Processor") == "EMBEDDED_SYSTEMS"

def test_skill_classification_operating_systems():
    assert get_skill_category("Operating Systems") == "CORE_CS"

def test_skill_classification_computer_networks():
    assert get_skill_category("Computer Networks") == "CORE_CS"

def test_skill_classification_blockchain():
    assert get_skill_category("Blockchain") == "BLOCKCHAIN"

def test_skill_classification_aws():
    assert get_skill_category("AWS") == "CLOUD"

def test_skill_classification_fastapi():
    assert get_skill_category("FastAPI") == "FRAMEWORKS"

def test_skill_classification_mongodb():
    assert get_skill_category("MongoDB") == "DATABASES"

def test_skill_classification_python():
    assert get_skill_category("Python") == "PROGRAMMING_LANGUAGES"

def test_skill_classification_unknown():
    assert get_skill_category("UnknownSkill") == "OTHER"

def test_skill_classification_normalization():
    # Trim whitespace, check aliases and casing
    assert get_skill_category("  python  ") == "PROGRAMMING_LANGUAGES"
    assert get_skill_category("postgres") == "DATABASES"
    assert get_skill_category("js") == "PROGRAMMING_LANGUAGES"
    assert get_skill_category("ml") == "AI_ML"
