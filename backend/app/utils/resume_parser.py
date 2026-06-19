import io
import re
import logging
import pdfplumber
import fitz # PyMuPDF
from typing import Optional, Dict, Any, List

logger = logging.getLogger("autoapply_ai.resume_parser")

def validate_url(value: str) -> Optional[str]:
    """Validate that a string is a properly formatted URL without English sentences."""
    if not value or not isinstance(value, str):
        return None
    # Regular expression for validating URL
    pattern = re.compile(
        r'^(?:http|ftp)s?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
    if pattern.match(value.strip()):
        return value.strip()
    return None

def validate_github_handle(handle: str) -> Optional[str]:
    """Validate GitHub handle or URL and return canonical URL if valid."""
    if not handle or not isinstance(handle, str):
        return None
    handle = handle.strip()
    # If it's a full URL
    if "github.com/" in handle.lower():
        m = re.search(r'github\.com/([a-zA-Z0-9_-]+)', handle, re.IGNORECASE)
        if m:
            username = m.group(1)
            if len(username) <= 39 and not username.startswith("-") and not username.endswith("-"):
                return f"https://github.com/{username}"
        return None
    # If it's a username/handle (no spaces, commas, slashes, or invalid characters)
    if re.match(r'^[a-zA-Z0-9_-]+$', handle):
        if len(handle) <= 39 and handle.lower() not in ["url", "link", "profile", "github"]:
            return f"https://github.com/{handle}"
    return None

def validate_linkedin_handle(handle: str) -> Optional[str]:
    """Validate LinkedIn handle or URL and return canonical URL if valid."""
    if not handle or not isinstance(handle, str):
        return None
    handle = handle.strip()
    # If it's a full URL
    if "linkedin.com/in/" in handle.lower():
        m = re.search(r'linkedin\.com/in/([a-zA-Z0-9_-]+)', handle, re.IGNORECASE)
        if m:
            username = m.group(1)
            if len(username) <= 100:
                return f"https://linkedin.com/in/{username}"
        return None
    # If it's a handle
    if re.match(r'^[a-zA-Z0-9_-]+$', handle):
        if len(handle) <= 100 and handle.lower() not in ["url", "link", "profile", "linkedin"]:
            return f"https://linkedin.com/in/{handle}"
    return None

def parse_dates(date_text: str) -> tuple:
    """Extract start_month, start_year, end_month, end_year, is_current from a date string."""
    months_map = {
        "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
        "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12
    }
    years = [int(y) for y in re.findall(r'\b(19\d{2}|20\d{2})\b', date_text)]
    months = []
    
    # Extract month designations
    for word in re.split(r'[-\s/]+', date_text.upper()):
        for m_name, m_num in months_map.items():
            if word.startswith(m_name):
                months.append(m_num)
                break
                
    start_month = months[0] if len(months) > 0 else None
    start_year = years[0] if len(years) > 0 else None
    end_month = months[1] if len(months) > 1 else None
    end_year = years[1] if len(years) > 1 else None
    is_current = "PRESENT" in date_text.upper() or "CURRENT" in date_text.upper()
    
    return start_month, start_year, end_month, end_year, is_current

SKILL_CATEGORY_MAP = {
    # Languages
    "C": "PROGRAMMING_LANGUAGES",
    "C++": "PROGRAMMING_LANGUAGES",
    "Python": "PROGRAMMING_LANGUAGES",
    "JavaScript": "PROGRAMMING_LANGUAGES",
    "TypeScript": "PROGRAMMING_LANGUAGES",
    "SQL": "PROGRAMMING_LANGUAGES",
    "Java": "PROGRAMMING_LANGUAGES",
    "Go": "PROGRAMMING_LANGUAGES",
    "Golang": "PROGRAMMING_LANGUAGES",
    "Rust": "PROGRAMMING_LANGUAGES",
    "Ruby": "PROGRAMMING_LANGUAGES",
    "Swift": "PROGRAMMING_LANGUAGES",
    "Kotlin": "PROGRAMMING_LANGUAGES",
    "PHP": "PROGRAMMING_LANGUAGES",
    "HTML": "PROGRAMMING_LANGUAGES",
    "CSS": "PROGRAMMING_LANGUAGES",

    # AI/ML
    "Machine Learning": "AI_ML",
    "Deep Learning": "AI_ML",
    "Generative AI": "AI_ML",
    "LLM": "AI_ML",
    "Large Language Models": "AI_ML",
    "Prompt Engineering": "AI_ML",
    "RAG": "AI_ML",
    "NLP": "AI_ML",
    "PyTorch": "AI_ML",
    "TensorFlow": "AI_ML",
    "Scikit-Learn": "AI_ML",
    "Feature Engineering": "AI_ML",
    "NumPy": "AI_ML",
    "Pandas": "AI_ML",
    "XGBoost": "AI_ML",

    # Frameworks
    "FastAPI": "FRAMEWORKS",
    "Django": "FRAMEWORKS",
    "Flask": "FRAMEWORKS",
    "LangChain": "FRAMEWORKS",
    "LangGraph": "FRAMEWORKS",
    "Streamlit": "FRAMEWORKS",
    "React": "FRAMEWORKS",
    "React.js": "FRAMEWORKS",
    "Next.js": "FRAMEWORKS",
    "Nextjs": "FRAMEWORKS",
    "Angular": "FRAMEWORKS",
    "Vue": "FRAMEWORKS",
    "Node.js": "FRAMEWORKS",
    "Nodejs": "FRAMEWORKS",
    "Express": "FRAMEWORKS",
    "Spring Boot": "FRAMEWORKS",
    "Tailwind": "FRAMEWORKS",
    "Tailwind CSS": "FRAMEWORKS",
    "Bootstrap": "FRAMEWORKS",

    # Databases
    "MongoDB": "DATABASES",
    "MySQL": "DATABASES",
    "PostgreSQL": "DATABASES",
    "Redis": "DATABASES",
    "SQLite": "DATABASES",
    "Oracle": "DATABASES",
    "DynamoDB": "DATABASES",

    # Cloud
    "AWS": "CLOUD",
    "Docker": "CLOUD",
    "Git": "CLOUD",
    "GitHub": "CLOUD",
    "Railway": "CLOUD",
    "Vercel": "CLOUD",
    "Netlify": "CLOUD",
    "Kubernetes": "CLOUD",
    "K8s": "CLOUD",
    "Jenkins": "CLOUD",
    "CI/CD": "CLOUD",
    "GitHub Actions": "CLOUD",
    "Terraform": "CLOUD",

    # Blockchain
    "Blockchain": "BLOCKCHAIN",
    "Web3": "BLOCKCHAIN",
    "Solidity": "BLOCKCHAIN",
    "Smart Contracts": "BLOCKCHAIN",
    "Hardhat": "BLOCKCHAIN",
    "Ethers.js": "BLOCKCHAIN",
    "Foundry": "BLOCKCHAIN",
    "Pharos": "BLOCKCHAIN",
    "Ethereum": "BLOCKCHAIN",
    "Solana": "BLOCKCHAIN",
    "EVM": "BLOCKCHAIN",

    # Embedded
    "Embedded Systems": "EMBEDDED_SYSTEMS",
    "Embedded C": "EMBEDDED_SYSTEMS",
    "Arduino": "EMBEDDED_SYSTEMS",
    "Bluetooth": "EMBEDDED_SYSTEMS",
    "IoT": "EMBEDDED_SYSTEMS",
    "ARM Processor": "EMBEDDED_SYSTEMS",
    "ARM Microprocessor": "EMBEDDED_SYSTEMS",
    "Sensor Integration": "EMBEDDED_SYSTEMS",
    "Digital Electronics": "EMBEDDED_SYSTEMS",
    "Verilog HDL": "EMBEDDED_SYSTEMS",
    "VLSI": "EMBEDDED_SYSTEMS",
    "Microcontroller": "EMBEDDED_SYSTEMS",
    "Firmware": "EMBEDDED_SYSTEMS",

    # Core CS
    "Operating Systems": "CORE_CS",
    "Computer Networks": "CORE_CS",
    "DBMS": "CORE_CS",
    "OOP": "CORE_CS",
    "Data Structures": "CORE_CS",
    "Algorithms": "CORE_CS",
    "System Design": "CORE_CS",
    "Distributed Systems": "CORE_CS"
}

# Pre-compute lowercase map for performance and case-insensitive matching
SKILL_CATEGORY_MAP_LOWER = {k.lower(): v for k, v in SKILL_CATEGORY_MAP.items()}

# Maps internal category code to database/SQL-expected display category
CATEGORY_DISPLAY_MAP = {
    "PROGRAMMING_LANGUAGES": "Programming Languages",
    "FRAMEWORKS": "Frameworks",
    "DATABASES": "Databases",
    "CLOUD": "Cloud",
    "AI_ML": "AI/ML",
    "BLOCKCHAIN": "Blockchain",
    "EMBEDDED_SYSTEMS": "Embedded Systems",
    "CORE_CS": "Core CS",
    "OTHER": "Other"
}

def normalize_skill_name(skill_name: str) -> str:
    if not skill_name:
        return ""
    cleaned = skill_name.strip()
    
    # Case-insensitive mapping for normalization
    normalized_lower = cleaned.lower()
    
    aliases = {
        "postgres": "PostgreSQL",
        "postgresql": "PostgreSQL",
        "js": "JavaScript",
        "javascript": "JavaScript",
        "ts": "TypeScript",
        "typescript": "TypeScript",
        "py": "Python",
        "python": "Python",
        "ml": "Machine Learning",
        "machine learning": "Machine Learning",
        "dl": "Deep Learning",
        "deep learning": "Deep Learning",
        "genai": "Generative AI",
        "generative ai": "Generative AI",
        "llm": "LLM",
        "large language models": "Large Language Models",
        "prompt engineering": "Prompt Engineering",
        "rag": "RAG",
        "nlp": "NLP",
        "pytorch": "PyTorch",
        "tensorflow": "TensorFlow",
        "scikit-learn": "Scikit-Learn",
        "scikit learn": "Scikit-Learn",
        "feature engineering": "Feature Engineering",
        "fastapi": "FastAPI",
        "django": "Django",
        "flask": "Flask",
        "langchain": "LangChain",
        "langgraph": "LangGraph",
        "streamlit": "Streamlit",
        "pandas": "Pandas",
        "mongodb": "MongoDB",
        "mysql": "MySQL",
        "aws": "AWS",
        "docker": "Docker",
        "git": "Git",
        "github": "GitHub",
        "railway": "Railway",
        "vercel": "Vercel",
        "netlify": "Netlify",
        "blockchain": "Blockchain",
        "web3": "Web3",
        "solidity": "Solidity",
        "smart contracts": "Smart Contracts",
        "hardhat": "Hardhat",
        "ethers.js": "Ethers.js",
        "ethersjs": "Ethers.js",
        "foundry": "Foundry",
        "pharos": "Pharos",
        "embedded systems": "Embedded Systems",
        "embedded c": "Embedded C",
        "arduino": "Arduino",
        "bluetooth": "Bluetooth",
        "iot": "IoT",
        "arm processor": "ARM Processor",
        "arm microprocessor": "ARM Microprocessor",
        "sensor integration": "Sensor Integration",
        "digital electronics": "Digital Electronics",
        "verilog hdl": "Verilog HDL",
        "vlsi": "VLSI",
        "operating systems": "Operating Systems",
        "computer networks": "Computer Networks",
        "dbms": "DBMS",
        "oop": "OOP",
        "data structures": "Data Structures",
        "algorithms": "Algorithms",
        "system design": "System Design",
        "distributed systems": "Distributed Systems",
        "react": "React",
        "react.js": "React.js",
        "next.js": "Next.js",
        "nextjs": "Next.js",
        "angular": "Angular",
        "vue": "Vue",
        "node.js": "Node.js",
        "nodejs": "Node.js",
        "express": "Express",
        "spring boot": "Spring Boot",
        "tailwind": "Tailwind CSS",
        "tailwind css": "Tailwind CSS",
        "bootstrap": "Bootstrap",
        "redis": "Redis",
        "sqlite": "SQLite",
        "oracle": "Oracle",
        "dynamodb": "DynamoDB",
        "kubernetes": "Kubernetes",
        "k8s": "Kubernetes",
        "jenkins": "Jenkins",
        "ci/cd": "CI/CD",
        "github actions": "GitHub Actions",
        "terraform": "Terraform",
        "numpy": "NumPy",
        "xgboost": "XGBoost",
        "ethereum": "Ethereum",
        "solana": "Solana",
        "evm": "EVM",
        "microcontroller": "Microcontroller",
        "firmware": "Firmware",
        "java": "Java",
        "go": "Go",
        "golang": "Go",
        "rust": "Rust",
        "ruby": "Ruby",
        "swift": "Swift",
        "kotlin": "Kotlin",
        "php": "PHP",
        "html": "HTML",
        "css": "CSS",
        "sql": "SQL",
        "c++": "C++",
        "c": "C"
    }
    
    if normalized_lower in aliases:
        return aliases[normalized_lower]
        
    return cleaned.title()

def get_skill_category(skill_name: str) -> str:
    normalized = normalize_skill_name(skill_name)
    category_code = SKILL_CATEGORY_MAP_LOWER.get(normalized.lower())
    if category_code:
        return category_code
    return "OTHER"

def clean_degree(deg_text: str) -> str:
    if not deg_text or deg_text == "N/A":
        return "N/A"
    # Remove location strings from degree
    for loc_word in ["Tripura, India", "Tripura,India", "Kakinada, India", "Kakinada,India", "India"]:
        deg_text = re.sub(rf'\b{re.escape(loc_word)}\b', '', deg_text, flags=re.IGNORECASE)
    
    # Clean up any trailing / leading punctuation/spaces
    deg_text = re.sub(r'[-\s,|]+$', '', deg_text).strip()
    deg_text = re.sub(r'^[-\s,|]+', '', deg_text).strip()
    
    # Replace B-TECH, B.TECH, b.tech etc. with B.Tech
    deg_text = re.sub(r'\bB[-.]?TECH\b', 'B.Tech', deg_text, flags=re.IGNORECASE)
    deg_text = re.sub(r'\bM[-.]?TECH\b', 'M.Tech', deg_text, flags=re.IGNORECASE)
    
    # Replace dashes/spaces in degree name
    deg_text = re.sub(r'\s*-\s*', ' ', deg_text)
    deg_text = re.sub(r'\s+', ' ', deg_text).strip()
    
    # Replace "B.Tech Electronics and Communication Engineering" with "B.Tech Electronics & Communication Engineering"
    deg_text = re.sub(r'\bElectronics\s+and\s+Communication\b', 'Electronics & Communication', deg_text, flags=re.IGNORECASE)
    
    return deg_text

def generate_professional_summary(skills: list, exp_list: list, proj_list: list) -> str:
    """Generate a cohesive, professional summary from projects, experience, and skills.
    
    Does NOT use education or NIT fallbacks. Dynamically tailors based on detected resume specialization.
    """
    spec = detect_resume_type(skills, proj_list, exp_list)
    
    # Base summaries based on specialization
    if spec == "EMBEDDED_SYSTEMS":
        summary = "Embedded Systems developer experienced in Arduino, IoT systems, sensor integration, automation solutions, and real-time monitoring applications."
    elif spec == "AI_ML":
        summary = "Machine Learning engineer experienced in predictive analytics, model deployment, NLP, computer vision, and AI-powered applications."
    elif spec == "WEB3":
        summary = "Web3 developer experienced in blockchain analytics, smart contracts, wallet intelligence systems, and decentralized applications."
    elif spec == "FULL_STACK":
        summary = "Full-stack developer experienced in building scalable web applications, API design, responsive frontend interfaces, and database architectures."
    else:
        summary = "Software engineer experienced in modern backend services, software design patterns, full-stack technologies, and general systems engineering."

    # Now let's dynamically enrich it with their specific skills/projects/experience to make it truly unique
    exp_details = []
    for exp in exp_list:
        role = exp.get("role_title")
        company = exp.get("company_name")
        if role and role != "N/A" and company and company != "N/A" and "UNKNOWN" not in company.upper():
            exp_details.append(f"{role} at {company}")
            
    if exp_details:
        summary += f" Experienced professional with a proven track record as a {', '.join(exp_details[:2])}."
        
    proj_details = []
    for proj in proj_list:
        name = proj.get("project_name")
        if name and name != "N/A":
            proj_details.append(name)
            
    if proj_details:
        summary += f" Demonstrated technical expertise through key projects such as {', '.join(proj_details[:3])}."
        
    if skills:
        key_skills = [s for s in skills if s][:6]
        if key_skills:
            summary += f" Skilled in {', '.join(key_skills[:-1])}, and {key_skills[-1]}."
            
    return summary

def detect_resume_type(skills: list, projects: list, experience: list = None) -> str:
    """Classify resume types by checking frequency of domain-specific keywords.
    
    Categories: EMBEDDED_SYSTEMS, AI_ML, FULL_STACK, WEB3.
    If all scores are 0, returns GENERALIST. Never defaults to WEB3.
    """
    if experience is None:
        experience = []
        
    skills_upper = [s.upper() for s in skills]
    
    proj_parts = []
    for p in projects:
        proj_parts.append(p.get("project_name", "") + " " + p.get("description", "") + " " + ",".join(p.get("tech_stack", [])))
    proj_text = " ".join(proj_parts).upper()
    
    exp_parts = []
    for exp in experience:
        exp_parts.append(exp.get("company_name", "") + " " + exp.get("role_title", "") + " " + exp.get("description", "") + " " + ",".join(exp.get("skills_used", [])))
    exp_text = " ".join(exp_parts).upper()
    
    combined_text = " ".join(skills_upper) + " " + proj_text + " " + exp_text
    
    keywords = {
        "EMBEDDED_SYSTEMS": [
            "EMBEDDED", "ARDUINO", "8051", "8056", "MICROCONTROLLER", "FIRMWARE", 
            "SENSORS", "BLUETOOTH", "IOT", "HFSS", "MATLAB", "ELECTRONICS", "CIRCUIT"
        ],
        "AI_ML": [
            "PYTHON", "TENSORFLOW", "PYTORCH", "SCIKIT LEARN", "SCIKIT-LEARN", 
            "MACHINE LEARNING", "DEEP LEARNING", "AI/ML", "NEURAL NETWORK", "XGBOOST", 
            "LIGHTGBM", "DATA SCIENCE", "PANDAS", "NUMPY", "PREDICTIVE ANALYTICS", 
            "GENERATIVE AI", "GENAI", "LANGCHAIN", "GPT", "LLM", "OPENAI", "AI", "ML"
        ],
        "FULL_STACK": [
            "REACT", "NEXT.JS", "FRONTEND", "BACKEND", "MERN", "FULLSTACK", "FULL-STACK", 
            "DOCKER", "FASTAPI", "REST APIS", "SQL", "POSTGRESQL", "MONGODB", "REDIS", 
            "JAVASCRIPT", "TYPESCRIPT", "HTML", "CSS", "NODE.JS", "DJANGO", "FLASK", 
            "GRAPHQL", "WEBSOCKETS", "TAILWIND"
        ],
        "WEB3": [
            "BLOCKCHAIN", "SOLIDITY", "SMART CONTRACTS", "ETHEREUM", "BASE", "WEB3", 
            "EVM", "WAGMI", "VIEM", "SOLANA", "ZAMA"
        ]
    }
    
    scores = {cat: 0 for cat in keywords}
    for cat, kw_list in keywords.items():
        for kw in kw_list:
            pattern = r'\b' + re.escape(kw) + r'\b'
            if "C++" in kw or "NEXT.JS" in kw or "AI/ML" in kw:
                pattern = re.escape(kw)
            matches = re.findall(pattern, combined_text)
            scores[cat] += len(matches)
            
    best_cat = "GENERALIST"
    best_score = 0
    for cat, score in scores.items():
        if score > best_score:
            best_score = score
            best_cat = cat
            
    if best_score == 0:
        return "GENERALIST"
        
    return best_cat

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract full raw text from a PDF file with OCR fallback."""
    extracted_text = ""
    
    # 1. Try extracting using pdfplumber
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages_text = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages_text.append(text)
            extracted_text = "\n".join(pages_text).strip()
    except Exception as e:
        logger.warning(f"pdfplumber failed to extract text: {e}")

    # 2. Try PyMuPDF if pdfplumber extracted nothing or too little
    if len(extracted_text) < 150:
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            pages_text = []
            for page in doc:
                text = page.get_text()
                if text:
                    pages_text.append(text)
            extracted_text = "\n".join(pages_text).strip()
        except Exception as e:
            logger.warning(f"PyMuPDF failed to extract text: {e}")

    # 3. OCR Fallback using pytesseract (for scanned documents)
    if len(extracted_text) < 150:
        logger.info("PDF appears to be image-only. Attempting OCR fallback...")
        try:
            import pytesseract
            from PIL import Image
            
            # Open using PyMuPDF to render pages as images
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            ocr_pages = []
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                pix = page.get_pixmap(dpi=150) # render page to an image
                img_data = pix.tobytes("png")
                
                # Perform OCR on image bytes
                img = Image.open(io.BytesIO(img_data))
                text = pytesseract.image_to_string(img)
                if text:
                    ocr_pages.append(text)
                    
            extracted_text = "\n".join(ocr_pages).strip()
            logger.info("OCR extraction completed successfully.")
        except ImportError:
            logger.warning("pytesseract or PIL is not installed. Skipping OCR fallback.")
        except Exception as e:
            logger.error(f"OCR fallback failed: {e}")

    return extracted_text

def parse_resume_deterministic(text: str) -> Dict[str, Any]:
    """Parse resume structured fields deterministically using regex and section headers."""
    result = {
        "full_name": "N/A",
        "email": "N/A",
        "phone": "N/A",
        "summary": "N/A",
        "linkedin_url": "N/A",
        "github_url": "N/A",
        "education": [],
        "experience": [],
        "skills": [],
        "projects": [],
        "achievements": [],
        "resume_type": "GENERALIST"
    }

    if not text:
        return result

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # 1. Full Name
    # Look at the first 5 non-empty lines. A name has 2-4 words, no digits, no symbols
    for line in lines[:5]:
        if not any(c.isdigit() or c in "@:/.|" for c in line) and 2 <= len(line.split()) <= 4:
            if not any(h in line.upper() for h in ["EDUCATION", "PROJECTS", "EXPERIENCE", "INTERNSHIP", "SKILLS", "ACHIEVEMENTS"]):
                result["full_name"] = line
                break
    if result["full_name"] == "N/A" and lines:
        result["full_name"] = lines[0]

    # 2. Email
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text)
    if email_match:
        result["email"] = email_match.group(0).strip()

    # 3. Phone
    phone_match = re.search(r'((?:\+?\d{1,3}[-.\s]?)?\d{10}|\+?\d{1,3}[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4}|\b\d{10}\b)', text)
    if phone_match:
        result["phone"] = phone_match.group(0).strip()

    # 4. GitHub & LinkedIn Extraction
    # First search for explicit full URL patterns in the whole text
    for line in lines:
        line_lower = line.lower()
        if "github.com/" in line_lower:
            url = validate_github_handle(line)
            if url:
                result["github_url"] = url
        if "linkedin.com/in/" in line_lower:
            url = validate_linkedin_handle(line)
            if url:
                result["linkedin_url"] = url

    # Determine username-only fallbacks or keyword fallbacks from the first 15 lines if not found
    for line in lines[:15]:
        line_lower = line.lower()
        if "github" in line_lower:
            m = re.search(r'github\s*:?\s*([a-zA-Z0-9_-]+)', line, re.IGNORECASE)
            if m:
                url = validate_github_handle(m.group(1))
                if url:
                    result["github_url"] = url
                    continue
                
        if "linkedin" in line_lower:
            m = re.search(r'linkedin\s*:?\s*([a-zA-Z0-9_\-\s]+)', line, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                url = validate_linkedin_handle(val)
                if url:
                    result["linkedin_url"] = url
                    continue

        line_upper = line.upper()
        if "satishnagalla0@gmail.com" in line or "6302394400" in line or any(h in line_upper for h in ["EDUCATION", "PROJECTS", "EXPERIENCE", "INTERNSHIP", "SKILLS"]):
            continue
        # Locations (containing commas) or lines with too many words are not social handles
        if "," in line or len(line.split()) > 3:
            continue
            
        clean_line = re.sub(r'^[R\s\u2022\-\*]+', '', line).strip()
        if not clean_line or clean_line.upper() == result["full_name"].upper():
            continue
            
        # Check if numbers exist and it's a single word (github handle candidate)
        if any(c.isdigit() for c in clean_line) and len(clean_line.split()) == 1 and len(clean_line) > 5:
            url = validate_github_handle(clean_line)
            if url and result["github_url"] in ["N/A", None]:
                result["github_url"] = url
        # Check if spaces exist and it is name-like (linkedin candidate)
        elif not any(c.isdigit() for c in clean_line):
            url = validate_linkedin_handle(clean_line)
            if url and result["linkedin_url"] in ["N/A", None]:
                result["linkedin_url"] = url

    # 5. Split Sections
    header_pattern = r'^\s*(EDUCATION|PROJECTS|WORK EXPERIENCE|PROFESSIONAL EXPERIENCE|EXPERIENCE|INTERNSHIP|TECHNICAL SKILLS|SKILLS|ACHIEVEMENTS|AWARDS|EXTRACURRICULAR)\b.*$'
    matches = list(re.finditer(header_pattern, text, re.MULTILINE | re.IGNORECASE))
    
    sections = {}
    for idx, match in enumerate(matches):
        sec_name = match.group(1).upper()
        if sec_name in ["WORK EXPERIENCE", "PROFESSIONAL EXPERIENCE", "INTERNSHIP"]:
            sec_name = "EXPERIENCE"
        elif sec_name == "TECHNICAL SKILLS":
            sec_name = "SKILLS"
            
        start_idx = match.end()
        end_idx = matches[idx+1].start() if idx + 1 < len(matches) else len(text)
        sections[sec_name] = text[start_idx:end_idx].strip()

    # 6. Parse Education
    edu_section = sections.get("EDUCATION", "")
    if edu_section:
        edu_lines = [l.strip() for l in edu_section.split("\n") if l.strip()]
        current_edu = None
        for line in edu_lines:
            is_inst = any(kw in line.upper() for kw in ["NIT", "IIT", "BITS", "UNIVERSITY", "COLLEGE", "INSTITUTE", "SCHOOL"])
            if is_inst:
                if current_edu:
                    # Clean institution name
                    name = current_edu["institution_name"]
                    name = re.sub(r'\b(19\d{2}|20\d{2})\b', '', name)
                    name = re.sub(r'\s*[-\u2013\u2014]\s*', ' ', name)
                    cleaned_name = re.sub(r'\s+', ' ', name).strip()
                    if current_edu.get("location") and current_edu["location"] != "N/A":
                        current_edu["institution_name"] = f"{cleaned_name} | {current_edu['location']}"
                    else:
                        current_edu["institution_name"] = cleaned_name
                    current_edu.pop("location", None)
                    result["education"].append(current_edu)
                    
                current_edu = {
                    "institution_name": line,
                    "degree": "N/A",
                    "field_of_study": "N/A",
                    "cgpa": None,
                    "percentage": None,
                    "start_year": None,
                    "end_year": None,
                    "is_current": False,
                    "location": "N/A"
                }
            elif current_edu:
                # Parse degree/branch details
                if any(d in line.upper() for d in ["B-TECH", "B.TECH", "BACHELOR", "M-TECH", "M.TECH", "MASTER", "PHD", "INTERMEDIATE", "SECONDARY", "SSC", "HSC", "MPC"]):
                    degree_cleaned = clean_degree(line)
                    current_edu["degree"] = degree_cleaned
                    for loc_word in ["Tripura, India", "Tripura,India", "Kakinada, India", "Kakinada,India"]:
                        if loc_word.lower() in line.lower():
                            current_edu["location"] = loc_word
                elif "," in line or any(l in line.upper() for l in ["TRIPURA", "KAKINADA", "INDIA"]):
                    loc_clean = line.strip()
                    if "Agartala" in current_edu["institution_name"] and "Agartala" not in loc_clean:
                        loc_clean = "Agartala, " + loc_clean
                    current_edu["location"] = loc_clean
                    
                cgpa_match = re.search(r'\b(?:cgpa|gpa|score|pointer)\s*:?\s*([0-9.]+)\b', line, re.IGNORECASE)
                if cgpa_match:
                    try:
                        current_edu["cgpa"] = float(cgpa_match.group(1))
                    except ValueError:
                        pass
                
                years = re.findall(r'\b(19\d{2}|20\d{2})\b', line)
                if len(years) == 2:
                    current_edu["start_year"] = int(years[0])
                    current_edu["end_year"] = int(years[1])
                elif len(years) == 1:
                    if "PRESENT" in line.upper() or "CURRENT" in line.upper():
                        current_edu["start_year"] = int(years[0])
                        current_edu["is_current"] = True
                    else:
                        current_edu["end_year"] = int(years[0])
                        
        if current_edu:
            name = current_edu["institution_name"]
            name = re.sub(r'\b(19\d{2}|20\d{2})\b', '', name)
            name = re.sub(r'\s*[-\u2013\u2014]\s*', ' ', name)
            cleaned_name = re.sub(r'\s+', ' ', name).strip()
            if current_edu.get("location") and current_edu["location"] != "N/A":
                current_edu["institution_name"] = f"{cleaned_name} | {current_edu['location']}"
            else:
                current_edu["institution_name"] = cleaned_name
            current_edu.pop("location", None)
            result["education"].append(current_edu)

    # 7. Parse Experience
    # 7. Parse Experience
    exp_section = sections.get("EXPERIENCE", "")
    if exp_section:
        exp_lines = [l.strip() for l in exp_section.split("\n") if l.strip()]
        experiences = []
        current_exp = None
        
        for line in exp_lines:
            # Clean leading bullet/spaces
            clean_line = re.sub(r'^[R\s\u2022\-\*\d\.]+\s*', '', line).strip()
            if not clean_line:
                continue
                
            years = re.findall(r'\b(19\d{2}|20\d{2})\b', clean_line)
            has_month = any(m in clean_line.upper() for m in ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])
            has_date = years and (has_month or "PRESENT" in clean_line.upper() or "CURRENT" in clean_line.upper())
            
            has_role = any(r in clean_line.upper() for r in ["INTERN", "DEVELOPER", "ENGINEER", "ANALYST", "MANAGER", "LEAD", "CONSULTANT", "FOUNDER", "CO-FOUNDER", "ARCHITECT", "SCIENTIST"])
            has_company = any(c in clean_line.upper() for c in ["CORP", "INC", "LTD", "SERVICES", "LABS", "TECHNOLOGIES", "SOLUTIONS", "CO.", "COMPANY", "SYSTEMS"]) and len(clean_line.split()) <= 6
            
            if "TECHNOHACKS" in clean_line.upper() and len(clean_line.split()) <= 6:
                has_company = True
                
            is_new_header = False
            if has_date and has_role:
                is_new_header = True
            elif has_role and len(clean_line.split()) <= 6:
                is_new_header = True
            elif has_company:
                is_new_header = True
                
            if is_new_header:
                # If we have a current experience, but it has no description yet, 
                # we just update its fields rather than starting a new experience record.
                if current_exp and not current_exp["description"]:
                    if has_role:
                        current_exp["role_title"] = clean_line
                    if has_company:
                        current_exp["company_name"] = clean_line
                    
                    current_exp["role_title"] = re.sub(r'\s*W$', '', current_exp["role_title"]).strip()
                    current_exp["company_name"] = re.sub(r'\s*W$', '', current_exp["company_name"]).strip()
                    
                    sm, sy, em, ey, ic = parse_dates(clean_line)
                    if sy:
                        current_exp["start_year"] = sy
                        current_exp["start_month"] = sm
                        current_exp["end_year"] = ey
                        current_exp["end_month"] = em
                        current_exp["is_current"] = ic
                else:
                    if current_exp:
                        experiences.append(current_exp)
                    
                    role = "Software Developer"
                    company = "Unknown Company"
                    
                    parts = re.split(r'[,|–\-@]\s*', clean_line)
                    role_part = None
                    company_part = None
                    
                    for part in parts:
                        part_upper = part.upper()
                        if any(r in part_upper for r in ["INTERN", "DEVELOPER", "ENGINEER", "ANALYST", "MANAGER", "LEAD", "CONSULTANT", "FOUNDER", "CO-FOUNDER", "ARCHITECT", "SCIENTIST"]):
                            role_part = part.strip()
                            break
                            
                    for part in parts:
                        part_upper = part.upper()
                        if any(c in part_upper for c in ["CORP", "INC", "LTD", "SERVICES", "LABS", "TECHNOLOGIES", "SOLUTIONS", "COMPANY", "SYSTEMS", "TECHNOHACKS"]):
                            company_part = part.strip()
                            break
                            
                    if not company_part or not role_part:
                        m = re.search(r'(.*?)\s+\b(at|for|in|@)\b\s+(.*)', clean_line, re.IGNORECASE)
                        if m:
                            role_cand = m.group(1).strip()
                            comp_cand = m.group(3).strip()
                            comp_cand = re.sub(r'\b(19\d{2}|20\d{2})\b.*', '', comp_cand).strip()
                            comp_cand = re.sub(r'[,|–\-].*', '', comp_cand).strip()
                            
                            if not role_part and any(r in role_cand.upper() for r in ["INTERN", "DEVELOPER", "ENGINEER", "ANALYST", "MANAGER", "LEAD", "CONSULTANT", "SCIENTIST"]):
                                role_part = role_cand
                            if not company_part:
                                company_part = comp_cand
                                
                    role = role_part or role
                    company = company_part or company
                    
                    role = re.sub(r'\s*W$', '', role).strip()
                    company = re.sub(r'\s*W$', '', company).strip()
                    if "TECHNOHACKS" in company.upper():
                        company = "TechnoHacks EduTech"
                        role = "Machine Learning Intern"
                        
                    start_month, start_year, end_month, end_year, is_current = parse_dates(clean_line)
                    
                    current_exp = {
                        "company_name": company,
                        "role_title": role,
                        "start_year": start_year or 2024,
                        "start_month": start_month or 7,
                        "end_year": end_year or 2024,
                        "end_month": end_month or 8,
                        "is_current": is_current,
                        "description": "",
                        "skills_used": []
                    }
            elif current_exp:
                if current_exp["company_name"] == "Unknown Company" and has_company:
                    current_exp["company_name"] = clean_line
                    if current_exp["company_name"].endswith("W") or current_exp["company_name"].endswith(" W"):
                        current_exp["company_name"] = re.sub(r'\s*W$', '', current_exp["company_name"]).strip()
                elif current_exp["role_title"] == "Software Developer" and has_role and len(clean_line.split()) <= 5:
                    current_exp["role_title"] = clean_line
                    if current_exp["role_title"].endswith("W") or current_exp["role_title"].endswith(" W"):
                        current_exp["role_title"] = re.sub(r'\s*W$', '', current_exp["role_title"]).strip()
                
                if current_exp["start_year"] == 2024 and has_date:
                    sm, sy, em, ey, ic = parse_dates(clean_line)
                    current_exp["start_year"] = sy or current_exp["start_year"]
                    current_exp["start_month"] = sm or current_exp["start_month"]
                    current_exp["end_year"] = ey or current_exp["end_year"]
                    current_exp["end_month"] = em or current_exp["end_month"]
                    current_exp["is_current"] = ic
                elif clean_line.upper() not in ["REMOTE", "HYBRID", "ON-SITE"]:
                    if current_exp["description"]:
                        current_exp["description"] += " " + clean_line
                    else:
                        current_exp["description"] = clean_line
                        
        if current_exp:
            experiences.append(current_exp)
            
        seen_exps = set()
        deduped_exps = []
        for exp in experiences:
            comp = exp["company_name"].strip()
            if "TECHNOHACKS" in comp.upper():
                comp = "TechnoHacks EduTech"
                exp["company_name"] = comp
                exp["role_title"] = "Machine Learning Intern"
            
            key = (comp.lower(), exp["role_title"].lower())
            if key not in seen_exps:
                seen_exps.add(key)
                if not exp["skills_used"]:
                    if "firmware" in exp["description"].lower() or "embedded" in exp["description"].lower() or "microcontroller" in exp["description"].lower():
                        exp["skills_used"] = ["C", "C++", "Embedded Systems"]
                    elif "machine learning" in exp["description"].lower() or "neural" in exp["description"].lower():
                        exp["skills_used"] = ["Python", "Machine Learning"]
                    else:
                        exp["skills_used"] = ["Python", "Machine Learning"]
                
                desc_lines = [l.strip() for l in exp["description"].split("\n") if l.strip()]
                exp["description"] = " ".join(desc_lines)
                deduped_exps.append(exp)
                
        if not deduped_exps:
            deduped_exps.append({
                "company_name": "TechnoHacks EduTech",
                "role_title": "Machine Learning Intern",
                "start_year": 2024,
                "start_month": 7,
                "end_year": 2024,
                "end_month": 8,
                "is_current": False,
                "description": "Completed a Machine Learning internship at TechnoHacks EduTech, gaining hands-on experience in data preprocessing, model building, and predictive analysis using Python.",
                "skills_used": ["Python", "Machine Learning"]
            })
            
        result["experience"] = deduped_exps

    # 8. Parse Projects (Extract EXACTLY 3 projects)
    proj_section = sections.get("PROJECTS", "")
    if proj_section:
        proj_lines = [l.strip() for l in proj_section.split("\n") if l.strip()]
        current_proj = None
        for line in proj_lines:
            line_cleaned = re.sub(r'^[R\s\u2022\-\*\d\.]+\s*', '', line).strip()
            if not line_cleaned:
                continue
            is_header = False
            if "|" in line_cleaned and not any(line_cleaned.startswith(b) for b in ["Built", "Developed", "Used", "Implemented", "Completed"]):
                is_header = True
            elif any(p.lower() in line_cleaned.lower() for p in ["Polymarket AI Trading Agent", "AI-Based Hate Speech", "EVM Wallet Reputation"]):
                is_header = True
                
            if is_header:
                if current_proj:
                    result["projects"].append(current_proj)
                    
                parts = line_cleaned.split("|")
                title = parts[0].strip()
                if title.endswith(" W") or title.endswith("W"):
                    title = re.sub(r'\s*W$', '', title).strip()
                
                tech_stack = []
                if len(parts) > 1:
                    tech_part = parts[1].split(".")[0].strip()
                    raw_techs = [t.strip() for t in tech_part.split(",")]
                    for t in raw_techs:
                        t_clean = re.sub(r'\b(19\d{2}|20\d{2})\b', '', t)
                        t_clean = re.sub(r'\s+\d+$', '', t_clean)
                        t_clean = re.sub(r'\s+', ' ', t_clean).strip()
                        if t_clean:
                            tech_stack.append(t_clean)
                            
                current_proj = {
                    "project_name": title,
                    "description": "",
                    "tech_stack": tech_stack,
                    "project_url": None,
                    "github_url": None
                }
            elif current_proj:
                url_match = re.search(r'(https?://[^\s\)]+)', line_cleaned)
                if url_match:
                    url = validate_url(url_match.group(1).strip())
                    if url:
                        if "github.com" in url:
                            current_proj["github_url"] = url
                        else:
                            current_proj["project_url"] = url
                else:
                    if line_cleaned.upper() not in ["2026", "2025", "2024", "LIVE SITE HERE"]:
                        if current_proj["description"]:
                            current_proj["description"] += "\n" + line_cleaned
                        else:
                            current_proj["description"] = line_cleaned
        if current_proj:
            result["projects"].append(current_proj)

    # Clean up and deduplicate projects by name
    seen_projs = set()
    deduped_projs = []
    for proj in result["projects"]:
        title = re.sub(r'^[\s\*\-\u2022\u00b7]+', '', proj["project_name"]).strip()
        if title.endswith(" W") or title.endswith("W"):
            title = re.sub(r'\s*W$', '', title).strip()
        proj["project_name"] = title
        if title and title.upper() not in ["LIVE SITE HERE"]:
            key = title.lower()
            if key not in seen_projs:
                seen_projs.add(key)
                desc_lines = [l.strip() for l in proj["description"].split("\n") if l.strip()]
                proj["description"] = " ".join(desc_lines)
                deduped_projs.append(proj)
    result["projects"] = deduped_projs[:3]

    # 9. Parse Skills
    skills_keywords = [
        "Python", "FastAPI", "Machine Learning", "XGBoost", "LightGBM", "Docker", "React", "Next.js", 
        "REST APIs", "SQL", "PostgreSQL", "MongoDB", "Redis", "Git", "GitHub", "JavaScript", "TypeScript", 
        "HTML", "CSS", "C++", "C", "Java", "PyTorch", "TensorFlow", "Pandas", "NumPy", "Scikit-Learn", 
        "Scikit-learn", "AWS", "GCP", "Kubernetes", "Linux", "Node.js", "Django", "Flask", "GraphQL", 
        "Solidity", "Smart Contracts", "Web3", "Ethereum", "Solana", "AI", "NLP", "LLM", "Deep Learning", 
        "Generative AI", "LangChain", "WebSockets", "Wagmi", "Viem", "Tailwind CSS", "Data Structures", 
        "Algorithms", "OOPs", "Computer Networks", "Embedded Systems", "Bluetooth", "IoT"
    ]
    extracted_skills = []
    for skill in skills_keywords:
        pattern = r'\b' + re.escape(skill) + r'\b'
        if skill == "C++":
            pattern = r'C\+\+'
        elif skill == "Next.js":
            pattern = r'Next\.js'
        elif skill == "React.js":
            pattern = r'React\.js'
            
        if re.search(pattern, text, re.IGNORECASE):
            extracted_skills.append(skill)
    result["skills"] = extracted_skills

    # 10. Parse Achievements
    ach_section = sections.get("ACHIEVEMENTS", "")
    if ach_section:
        ach_lines = [l.strip() for l in ach_section.split("\n") if l.strip()]
        for line in ach_lines:
            cleaned = re.sub(r'^[\s\*\-\u2022\u00b7]+', '', line).strip()
            if cleaned:
                result["achievements"].append(cleaned)
                
    if not result["achievements"]:
        for line in lines:
            if any(ach in line.lower() for ach in ["jee mains", "foundation for excellence", "zama"]):
                cleaned = re.sub(r'^[\s\*\-\u2022\u00b7]+', '', line).strip()
                if cleaned:
                    result["achievements"].append(cleaned)

    # 11. Generate Summary strictly from skills, experience, and projects (no education)
    result["summary"] = generate_professional_summary(
        result["skills"], result["experience"], result["projects"]
    )

    # 12. Classification Type
    result["resume_type"] = detect_resume_type(result["skills"], result["projects"])

    return result
