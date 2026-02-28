#!/usr/bin/env python3
"""
Resume Parser — Extract structured data from PDF/DOCX resumes.
Builds a resume_profile.json that powers the Q&A bank and form filler.
"""

import json
import re
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent

# Try PDF parsing
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    from PyPDF2 import PdfReader
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

# Try DOCX parsing
try:
    from docx import Document as DocxDocument
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False


# =====================================================================
# TEXT EXTRACTION
# =====================================================================

def extract_text_from_pdf(filepath):
    """Extract text from a PDF file."""
    filepath = Path(filepath)
    text = ""

    if HAS_PDFPLUMBER:
        try:
            with pdfplumber.open(filepath) as pdf:
                for pg in pdf.pages:
                    text += (pg.extract_text() or "") + "\n"
            return text.strip()
        except Exception:
            pass

    if HAS_PYPDF2:
        try:
            reader = PdfReader(str(filepath))
            for pg in reader.pages:
                text += (pg.extract_text() or "") + "\n"
            return text.strip()
        except Exception:
            pass

    raise ImportError("No PDF parser available. Install: pip install pdfplumber")


def extract_text_from_docx(filepath):
    """Extract text from a DOCX file."""
    if not HAS_DOCX:
        raise ImportError("python-docx not available. Install: pip install python-docx")

    doc = DocxDocument(str(filepath))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def extract_text(filepath):
    """Extract text from PDF or DOCX."""
    filepath = Path(filepath)
    ext = filepath.suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(filepath)
    elif ext in (".docx", ".doc"):
        return extract_text_from_docx(filepath)
    elif ext == ".txt":
        return filepath.read_text()
    else:
        raise ValueError(f"Unsupported file type: {ext}")


# =====================================================================
# PROFILE EXTRACTION
# =====================================================================

EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+')
# International phone patterns: supports US, UK, Germany, India, and generic +XX formats
# Matches: (555) 123-4567, 555-123-4567, +1-555-123-4567, +44 20 7946 0958, +49 (30) 12345678, etc.
PHONE_RE = re.compile(r'(?:\+\d{1,3})?[\s.-]?[\(]?\d{1,5}[\)]?[\s.-]?\d{1,5}[\s.-]?\d{1,5}(?:[\s.-]?\d{1,5})?')
LINKEDIN_RE = re.compile(r'linkedin\.com/in/[\w-]+', re.IGNORECASE)
URL_RE = re.compile(r'https?://[\w./\-?=&%]+')

DEGREE_PATTERNS = [
    # Masters degrees: US, UK, European variants
    (r'(?:master|m\.?s\.?|ms|m\.?sc\.?|msc|diplôme|magister)\s+(?:of|in)?\s*(?:science|arts)?\s*(?:in)?\s*([\w\s,&/]+)', 'masters'),
    # MBA variants
    (r'(?:m\.?b\.?a\.?|master\s+of\s+business\s+administration)', 'mba'),
    # Bachelor degrees: US, UK, European variants
    (r'(?:bachelor|b\.?s\.?|b\.?a\.?|bs|b\.?sc\.?|bsc|b\.?eng\.?|beng|licence|licenciatura)\s+(?:of|in)?\s*(?:science|arts)?\s*(?:in)?\s*([\w\s,&/]+)', 'bachelors'),
    # PhD/Doctorate variants
    (r'(?:ph\.?d\.?|doctor\s+of\s+philosophy|doctorate|dr\.?rer\.?nat\.?|diplom)\s*(?:in)?\s*([\w\s,&/]+)', 'phd'),
    # Associate degrees
    (r'(?:associate)\s+(?:of|in)?\s*(?:science|arts)?\s*(?:in)?\s*([\w\s,&/]+)', 'associates'),
    # Law degrees (UK/International)
    (r'(?:llb|llm|juris\s+doctor|j\.?d\.?)\s*(?:in)?\s*([\w\s,&/]+)?', 'law'),
    # Medical degrees (International)
    (r'(?:m\.?d\.?|md|m\.?b\.?b\.?s\.?|mbbs|laurea\s+magistrale)\s*(?:in)?\s*([\w\s,&/]+)?', 'medical'),
]

SKILL_KEYWORDS = {
    "product_management": ["product management", "product manager", "roadmap", "product strategy",
                           "user stories", "product requirements", "PRD", "product owner", "backlog",
                           "product lifecycle", "go-to-market", "product-market fit"],
    "technical": ["python", "sql", "aws", "azure", "gcp", "docker", "kubernetes", "git",
                  "javascript", "react", "node", "java", "c++", "rest api", "graphql",
                  "terraform", "ci/cd", "machine learning", "deep learning", "langchain",
                  "llm", "generative ai", "data pipeline", "etl", "airflow", "spark"],
    "data_analytics": ["tableau", "power bi", "excel", "data analysis", "a/b testing",
                       "analytics", "sql", "bigquery", "snowflake", "looker", "dbt",
                       "data visualization", "statistical analysis", "r programming"],
    "tools": ["jira", "confluence", "asana", "trello", "notion", "miro", "figma",
              "slack", "github", "gitlab", "bitbucket", "linear", "productboard"],
    "methodologies": ["agile", "scrum", "kanban", "lean", "design thinking", "six sigma",
                      "waterfall", "safe", "devops", "okr", "kpi"],
    "soft_skills": ["leadership", "cross-functional", "stakeholder management",
                    "communication", "presentation", "negotiation", "mentoring",
                    "team building", "strategic thinking", "problem solving"],
    "domain": ["biotech", "biotechnology", "pharma", "pharmaceutical", "clinical trials",
               "genomics", "bioinformatics", "healthcare", "medical device",
               "defense", "aerospace", "government", "fintech", "edtech", "saas"],
    "certifications": ["pmp", "csm", "psm", "safe", "aws certified", "google certified",
                       "comptia", "ccna", "cissp", "itil", "prince2"],
}


def parse_resume(filepath, user_overrides=None):
    """Parse a resume file and extract structured profile data.

    Args:
        filepath: Path to PDF/DOCX/TXT resume
        user_overrides: Optional dict to override extracted fields

    Returns:
        Dict with structured resume profile
    """
    text = extract_text(filepath)
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    profile = {
        "source_file": str(filepath),
        "parsed_at": datetime.now().isoformat(),
        "raw_text": text,
    }

    # Extract contact info
    profile["contact"] = _extract_contact(text, lines)

    # Extract education
    profile["education"] = _extract_education(text)

    # Extract skills
    profile["skills"] = _extract_skills(text)

    # Extract work experience
    profile["experience"] = _extract_experience(text, lines)

    # Extract certifications
    profile["certifications"] = _extract_certifications(text)

    # Extract summary
    profile["summary"] = _extract_summary(text, lines)

    # Apply overrides
    if user_overrides:
        for key, val in user_overrides.items():
            if val:
                if isinstance(val, dict) and key in profile and isinstance(profile[key], dict):
                    profile[key].update(val)
                else:
                    profile[key] = val

    return profile


def _extract_contact(text, lines):
    """Extract contact information."""
    contact = {
        "name": "",
        "email": "",
        "phone": "",
        "linkedin": "",
        "location": "",
        "website": "",
    }

    # Name: usually the first non-empty line
    if lines:
        first_line = lines[0]
        if len(first_line.split()) <= 5 and not EMAIL_RE.search(first_line):
            contact["name"] = first_line

    # Email
    emails = EMAIL_RE.findall(text)
    if emails:
        contact["email"] = emails[0]

    # Phone
    phones = PHONE_RE.findall(text)
    if phones:
        contact["phone"] = phones[0]

    # LinkedIn
    linkedin = LINKEDIN_RE.findall(text)
    if linkedin:
        contact["linkedin"] = f"https://{linkedin[0]}"

    # Location: look for city, state/country patterns (flexible for international)
    # Try US format first: City, ST (two-letter state code)
    loc_match = re.search(r'([A-Z][a-z]+(?:\s[A-Z][a-z]+)*),?\s*([A-Z]{2})\b', text[:500])
    if loc_match:
        contact["location"] = f"{loc_match.group(1)}, {loc_match.group(2)}"
    else:
        # Try international format: City, Country or just Country
        # Look for patterns with country names or generic city/country structure
        loc_patterns = [
            r'([A-Z][a-z]+(?:\s[A-Z][a-z]+)*),\s*([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)',  # City, Country
            r'(?:Based in|Location)[\s:]+([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)',  # Based in/Location: City
            r'(?:Remote|Work from Home|WFH|Hybrid)',  # Remote work
        ]
        for pattern in loc_patterns:
            loc_match = re.search(pattern, text[:500])
            if loc_match:
                contact["location"] = loc_match.group(1) if loc_match.lastindex and loc_match.lastindex >= 1 else "Remote"
                break

    return contact


def _extract_education(text):
    """Extract education entries."""
    education = []
    text_lower = text.lower()

    for pattern, degree_type in DEGREE_PATTERNS:
        matches = re.finditer(pattern, text_lower)
        for match in matches:
            field = match.group(1).strip() if match.lastindex and match.lastindex >= 1 else ""
            field = re.sub(r'\s+', ' ', field)[:100]  # Clean up

            # Try to find the school name nearby
            start = max(0, match.start() - 200)
            end = min(len(text), match.end() + 200)
            context = text[start:end]

            school = ""
            school_match = re.search(r'(?:University|College|Institute|School)\s+of\s+[\w\s]+', context)
            if school_match:
                school = school_match.group(0).strip()

            year_match = re.search(r'20\d{2}|19\d{2}', context)
            year = year_match.group(0) if year_match else ""

            education.append({
                "degree_type": degree_type,
                "field": field,
                "school": school,
                "year": year,
            })

    return education


def _extract_skills(text):
    """Extract categorized skills from resume text."""
    found = {}
    text_lower = text.lower()

    for category, keywords in SKILL_KEYWORDS.items():
        matched = [kw for kw in keywords if kw.lower() in text_lower]
        if matched:
            found[category] = matched

    return found


def _extract_experience(text, lines):
    """Extract work experience entries."""
    experiences = []

    # Look for patterns like: Title at/| Company | Date - Date
    exp_pattern = re.compile(
        r'([A-Z][\w\s]+(?:Manager|Director|Lead|Engineer|Analyst|Owner|Founder|VP|Head)[\w\s]*?)'
        r'[\s|,@]+([A-Z][\w\s.&]+?)[\s|,]+'
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[\w\s]*\d{4}\s*[-–]\s*(?:Present|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[\w\s]*\d{4}))',
        re.MULTILINE
    )

    for match in exp_pattern.finditer(text):
        experiences.append({
            "title": match.group(1).strip(),
            "company": match.group(2).strip(),
            "dates": match.group(3).strip(),
        })

    # If regex didn't find enough, try simpler approach
    if len(experiences) < 2:
        section_started = False
        for i, line in enumerate(lines):
            if any(h in line.lower() for h in ["experience", "work history", "employment"]):
                section_started = True
                continue
            if section_started and any(h in line.lower() for h in ["education", "skills", "certifications", "projects"]):
                break
            if section_started and line and len(line) > 10:
                # Check if this looks like a job title line
                if re.search(r'20\d{2}|present', line.lower()):
                    experiences.append({"raw": line})

    return experiences[:10]  # Cap at 10


def _extract_certifications(text):
    """Extract certifications."""
    certs = []
    text_lower = text.lower()

    cert_keywords = [
        "pmp", "csm", "psm", "safe agilist", "aws certified", "aws cloud practitioner",
        "google certified", "comptia", "ccna", "cissp", "itil", "prince2",
        "six sigma", "lean six sigma", "scrum master", "product owner",
    ]

    for cert in cert_keywords:
        if cert in text_lower:
            certs.append(cert.upper() if len(cert) <= 4 else cert.title())

    return certs


def _extract_summary(text, lines):
    """Extract professional summary/objective."""
    summary = ""
    capture = False

    for line in lines:
        lower = line.lower().strip()
        if any(h in lower for h in ["summary", "objective", "profile", "about"]):
            capture = True
            continue
        if capture:
            if any(h in lower for h in ["experience", "work", "education", "skills", "certifications"]):
                break
            if line:
                summary += line + " "

    return summary.strip()[:500]


def save_profile(profile, output_dir=None):
    """Save parsed profile to resume_profile.json."""
    out_dir = Path(output_dir) if output_dir else SCRIPT_DIR
    profile_file = out_dir / "resume_profile.json"

    # Remove raw_text before saving (too large)
    save_data = {k: v for k, v in profile.items() if k != "raw_text"}

    with open(profile_file, 'w') as f:
        json.dump(save_data, f, indent=2)

    print(f"Resume profile saved to {profile_file}")
    return profile_file


def load_profile(profile_dir=None):
    """Load a previously parsed resume profile."""
    p_dir = Path(profile_dir) if profile_dir else SCRIPT_DIR
    profile_file = p_dir / "resume_profile.json"
    if profile_file.exists():
        with open(profile_file) as f:
            return json.load(f)
    return None
