#!/usr/bin/env python3
"""
Job Search Automation Script
Scans job boards for matching positions, ranks them, and outputs results.

Usage:
  python3 job_scraper.py                    # Run full scan
  python3 job_scraper.py --boards indeed    # Scan specific board
  python3 job_scraper.py --email            # Send email digest after scan
  python3 job_scraper.py --output json      # Output as JSON (for dashboard import)

Configuration is loaded from job_search_config.json in the same directory.
"""

import json
import os
import sys
import re
import time
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

# Try to import optional dependencies
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    HAS_EMAIL = True
except ImportError:
    HAS_EMAIL = False

# =====================================================================
# CONFIGURATION
# =====================================================================

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "job_search_config.json"
DATA_FILE = SCRIPT_DIR / "job_search_data.json"
LOG_FILE = SCRIPT_DIR / "job_scraper.log"

DEFAULT_CONFIG = {
    "user": {
        "name": "",
        "email": "",
        "phone": "",
        "location": "",
        "linkedin": ""
    },
    "search": {
        "keywords": [],
        "locations": [],
        "min_match_score": 60,
        "max_age_days": 14
    },
    "features": {
        "discovery": True,
        "ranking": True,
        "coverletter_draft": True,
        "auto_apply_top": False,
        "auto_apply_all": False,
        "email_digest": True,
        "followup_reminders": True
    },
    "boards": {
        "indeed": {"enabled": True, "url": "https://www.indeed.com/jobs?q={query}&l={location}&fromage=7"},
        "linkedin": {"enabled": True, "url": "https://www.linkedin.com/jobs/search/?keywords={query}&location={location}&f_TPR=r604800"},
        "biospace": {"enabled": True, "url": "https://jobs.biospace.com/jobs?keyword={query}&location={location}"},
        "glassdoor": {"enabled": True, "url": "https://www.glassdoor.com/Job/jobs.htm?sc.keyword={query}&locT=C"},
        "clearancejobs": {"enabled": False, "url": "https://www.clearancejobs.com/jobs?keywords={query}"},
        "wellfound": {"enabled": False, "url": "https://wellfound.com/role/l/{query}/{location}"},
        "usajobs": {"enabled": False, "url": "https://www.usajobs.gov/Search/Results?k={query}&l={location}"},
        "higheredjobs": {"enabled": False, "url": "https://www.higheredjobs.com/search/default.cfm?search={query}"}
    },
    "schedule": {
        "frequency": "2x",
        "times": ["08:00", "14:00"]
    },
    "email_settings": {
        "notification_email": "",
        "smtp_server": "",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_pass": ""
    }
}

# =====================================================================
# MATCHING KEYWORDS (for scoring)
# =====================================================================

RESUME_KEYWORDS = {
    "high_value": [
        "product manager", "product management", "AI", "machine learning",
        "biotechnology", "biotech", "pharma", "bioinformatics",
        "data governance", "analytics", "SaaS", "agile", "scrum",
        "cross functional", "roadmap", "stakeholder", "strategy",
        "LLM", "generative AI", "python", "AWS", "program manager"
    ],
    "medium_value": [
        "MBA", "product owner", "digital", "platform",
        "quality control", "QC", "lab", "regulatory", "compliance",
        "clinical", "R&D", "research", "innovation", "startup",
        "defense", "aerospace", "government", "project manager",
        "adjunct", "professor", "instructor", "teaching"
    ],
    "low_value": [
        "leadership", "communication", "presentation", "excel",
        "sql", "tableau", "visualization", "reporting", "analysis",
        "team", "collaboration", "documentation", "budget"
    ]
}


def load_config():
    """Load or create configuration file."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            config = json.load(f)
        # Merge with defaults for any missing keys
        for key in DEFAULT_CONFIG:
            if key not in config:
                config[key] = DEFAULT_CONFIG[key]
        return config
    else:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return DEFAULT_CONFIG


def load_data():
    """Load existing job data."""
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"jobs": [], "applications": [], "contacts": [], "logs": []}


def save_data(data):
    """Save job data."""
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def log(msg, data=None):
    """Log a message."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {msg}"
    print(log_entry)
    with open(LOG_FILE, 'a') as f:
        f.write(log_entry + "\n")
    if data:
        data.setdefault("logs", []).append({"time": timestamp, "msg": msg})


# =====================================================================
# JOB SCORING
# =====================================================================

def score_job(title, description="", company="", location=""):
    """Score a job listing against resume keywords. Returns 0 to 100."""
    text = f"{title} {description} {company} {location}".lower()
    score = 0
    max_possible = 0

    for keyword in RESUME_KEYWORDS["high_value"]:
        max_possible += 3
        if keyword.lower() in text:
            score += 3

    for keyword in RESUME_KEYWORDS["medium_value"]:
        max_possible += 2
        if keyword.lower() in text:
            score += 2

    for keyword in RESUME_KEYWORDS["low_value"]:
        max_possible += 1
        if keyword.lower() in text:
            score += 1

    # Normalize to 0 to 100
    if max_possible == 0:
        return 0
    raw = (score / max_possible) * 100

    # Boost for exact role matches
    title_lower = title.lower()
    if "product manager" in title_lower:
        raw = min(100, raw + 15)
    if "ai" in title_lower or "ml" in title_lower:
        raw = min(100, raw + 10)
    if "biotech" in title_lower or "pharma" in title_lower:
        raw = min(100, raw + 10)
    if "adjunct" in title_lower or "professor" in title_lower:
        raw = min(100, raw + 8)
    if "program manager" in title_lower:
        raw = min(100, raw + 10)

    return min(100, int(raw))


def categorize_sector(title, company, description=""):
    """Categorize a job into a sector."""
    text = f"{title} {company} {description}".lower()
    if any(w in text for w in ["biotech", "pharma", "clinical", "therapeutics", "drug", "genomic", "amgen", "genentech"]):
        return "biotech"
    if any(w in text for w in ["defense", "aerospace", "military", "dod", "clearance", "navy", "air force"]):
        return "defense"
    if any(w in text for w in ["adjunct", "professor", "instructor", "lecturer", "faculty", "university", "college"]):
        return "education"
    if any(w in text for w in ["government", "federal", "state of california", "county", "city of", "usajobs"]):
        return "government"
    if any(w in text for w in ["startup", "seed", "series a", "venture"]):
        return "startup"
    if any(w in text for w in ["remote", "anywhere"]):
        return "remote"
    return "tech"


def generate_job_id(title, company):
    """Generate unique ID for deduplication."""
    key = f"{title.lower().strip()}:{company.lower().strip()}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


# =====================================================================
# BOARD SCRAPERS (URL generators for manual or automated opening)
# =====================================================================

def generate_search_urls(config):
    """Generate search URLs for each enabled board and keyword combination."""
    urls = []
    boards = config.get("boards", {})
    keywords = config["search"]["keywords"]
    locations = config["search"]["locations"][:3]  # Top 3 locations

    for board_name, board_config in boards.items():
        if not board_config.get("enabled", False):
            continue

        url_template = board_config.get("url", "")
        if not url_template:
            continue

        for keyword in keywords[:5]:  # Top 5 keywords per board
            for location in locations:
                url = url_template.replace("{query}", quote_plus(keyword))
                url = url.replace("{location}", quote_plus(location))
                urls.append({
                    "board": board_name,
                    "keyword": keyword,
                    "location": location,
                    "url": url
                })

    return urls


def generate_career_page_urls(config):
    """Generate search URLs from the career pages watchlist (career_pages.json).

    The dashboard exports a career_pages.json file containing companies
    the user wants to monitor. This function reads that file and generates
    targeted search URLs for each watched company.
    """
    career_pages_file = SCRIPT_DIR / "career_pages.json"
    if not career_pages_file.exists():
        return []

    try:
        with open(career_pages_file) as f:
            watchlist = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

    urls = []
    keywords = config.get("search", {}).get("keywords", ["product manager"])[:3]

    for entry in watchlist:
        company_name = entry.get("companyName", "")
        career_url = entry.get("careerPageUrl", "")
        status = entry.get("status", "active")
        frequency = entry.get("frequency", "weekly")

        if status != "active":
            continue

        # If we have a direct career page URL, add it
        if career_url:
            urls.append({
                "board": "career_page_direct",
                "company": company_name,
                "keyword": "all",
                "location": "all",
                "url": career_url,
                "frequency": frequency,
                "type": "watchlist"
            })

        # Also generate search URLs across boards for this company
        for keyword in keywords:
            query = f"{keyword} {company_name}"
            urls.append({
                "board": "linkedin",
                "company": company_name,
                "keyword": query,
                "location": "all",
                "url": f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(query)}&f_C={quote_plus(company_name)}",
                "frequency": frequency,
                "type": "watchlist"
            })
            urls.append({
                "board": "indeed",
                "company": company_name,
                "keyword": query,
                "location": "all",
                "url": f"https://www.indeed.com/jobs?q={quote_plus(query)}&fromage=7",
                "frequency": frequency,
                "type": "watchlist"
            })
            urls.append({
                "board": "glassdoor",
                "company": company_name,
                "keyword": query,
                "location": "all",
                "url": f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={quote_plus(query)}",
                "frequency": frequency,
                "type": "watchlist"
            })

    return urls


# =====================================================================
# COVER LETTER GENERATOR
# =====================================================================

COVER_LETTER_TEMPLATES = {
    "technical": "Dear Hiring Manager,\n\nI am writing to express my interest in the {role} position at {company}. With relevant experience in technical project management and cross-functional team leadership, I am confident in my ability to contribute meaningfully to your organization.\n\nI would welcome the opportunity to discuss how my background aligns with your team's needs.\n\nSincerely,\n{user_name}",
    "general": "Dear Hiring Manager,\n\nI am excited to apply for the {role} role at {company}. I bring a proven track record of delivering results in dynamic environments through strategic thinking and effective collaboration.\n\nI look forward to discussing how my experience can add value to your team.\n\nSincerely,\n{user_name}"
}


def generate_cover_letter_draft(job, config, tone="confident"):
    """Generate a cover letter draft for a job listing.

    Tries AI generation first (via ai_engine), falls back to templates if unavailable.
    """
    # Try AI-powered generation first
    try:
        from ai_engine import get_engine
        from resume_parser import load_profile
        engine = get_engine(SCRIPT_DIR, config)
        if engine.is_available():
            profile = load_profile(SCRIPT_DIR)
            if profile:
                ai_letter = engine.generate_cover_letter(job, profile, tone=tone)
                if ai_letter:
                    return ai_letter
    except (ImportError, Exception) as e:
        log(f"AI cover letter unavailable ({e}), using template", {})

    # Fallback: template-based generation
    title = job.get("title", "")
    company = job.get("company", "")
    sector = job.get("sector", "tech")
    user_name = config.get("user", {}).get("name", "Hiring Manager")

    tone_templates = {
        "confident": {
            "opening": f"I am writing to express my strong interest in the {title} role at {company}.",
            "closing": "I am confident my background positions me to deliver immediate value to your team. I would welcome a conversation about how I can contribute."
        },
        "warm": {
            "opening": f"I was excited to see the opening for {title} at {company}.",
            "closing": f"I would genuinely enjoy the opportunity to bring my experience to your team and contribute to the meaningful work at {company}. I would love to connect and discuss this further."
        },
        "formal": {
            "opening": f"I am writing to apply for the position of {title} at {company}.",
            "closing": "I am prepared to discuss how my qualifications align with the requirements of this role at your earliest convenience."
        }
    }

    sector_bodies = {
        "biotech": "With relevant experience in biotechnology and bioinformatics, combined with product management expertise and hands-on experience in AI/ML product development, I am positioned to bridge the gap between technical teams and business strategy.",
        "tech": "With extensive product management experience spanning SaaS platforms, AI/ML products, and cross-functional team leadership, I have a proven track record of scaling products and delivering measurable business outcomes.",
        "defense": "With deep experience in product and program management, combined with technical expertise in AI/ML systems and data governance, I bring the structured execution and analytical rigor that defense and aerospace programs demand.",
        "education": "With industry experience across multiple sectors and a deep passion for teaching, I am positioned to bring real-world business expertise and mentorship into the classroom.",
        "government": "With extensive product and program management experience in both regulated and fast-paced environments, combined with expertise in data analytics and cross-functional leadership, I bring the analytical rigor and structured approach that public sector programs require.",
        "startup": "As a product professional who thrives in ambiguity and velocity, I bring adaptability and analytical rigor while wearing multiple hats in startup environments.",
        "remote": "With demonstrated ability to lead distributed teams effectively while delivering measurable business outcomes, I am well-suited for remote and hybrid product management roles."
    }

    t = tone_templates.get(tone, tone_templates["confident"])
    body = sector_bodies.get(sector, sector_bodies["tech"])

    letter = f"""Dear Hiring Manager,

{t['opening']} {body}

{t['closing']}

Sincerely,
{user_name}"""

    return letter


# =====================================================================
# EMAIL DIGEST
# =====================================================================

def send_email_digest(data, config):
    """Send email digest of new job matches."""
    if not HAS_EMAIL:
        log("Email libraries not available. Skipping digest.", data)
        return

    settings = config.get("email_settings", {})
    notification_email = settings.get("notification_email", "")
    
    if not notification_email:
        log("Notification email not configured. Saving digest as HTML instead.", data)
        save_digest_html(data, config)
        return

    if not settings.get("smtp_server"):
        log("SMTP not configured. Saving digest as HTML instead.", data)
        save_digest_html(data, config)
        return

    # Build email content
    new_jobs = [j for j in data.get("jobs", []) if j.get("status") == "new"]
    if not new_jobs:
        log("No new jobs to report.", data)
        return

    subject = f"Job Search Update: {len(new_jobs)} New Matches Found ({datetime.now().strftime('%b %d')})"
    body = build_digest_html(new_jobs)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings["smtp_user"]
    msg["To"] = notification_email
    msg.attach(MIMEText(body, "html"))

    try:
        # Load SMTP credentials securely
        smtp_pass = settings.get("smtp_pass", "")
        if not smtp_pass:
            log("SMTP password not configured. Skipping email send.", data)
            return

        with smtplib.SMTP(settings["smtp_server"], settings["smtp_port"]) as server:
            server.starttls()
            server.login(settings["smtp_user"], smtp_pass)
            server.sendmail(settings["smtp_user"], notification_email, msg.as_string())
        log(f"Email digest sent to {notification_email} with {len(new_jobs)} jobs.", data)
    except Exception as e:
        log(f"Email send failed: {str(e)}", data)


def build_digest_html(jobs):
    """Build HTML email digest content."""
    rows = ""
    for j in sorted(jobs, key=lambda x: x.get("match", 0), reverse=True):
        color = "#28A745" if j.get("match", 0) >= 85 else "#FFC107" if j.get("match", 0) >= 60 else "#6C757D"
        rows += f"""<tr>
            <td style="padding:8px;border-bottom:1px solid #eee;"><strong>{j['title']}</strong><br><span style="color:#2E75B6;">{j['company']}</span></td>
            <td style="padding:8px;border-bottom:1px solid #eee;">{j.get('location','')}</td>
            <td style="padding:8px;border-bottom:1px solid #eee;text-align:center;"><span style="background:{color};color:white;padding:2px 8px;border-radius:12px;font-size:12px;">{j.get('match',0)}%</span></td>
            <td style="padding:8px;border-bottom:1px solid #eee;">{j.get('sector','')}</td>
        </tr>"""

    return f"""<html><body style="font-family:Calibri,sans-serif;max-width:700px;margin:0 auto;">
    <div style="background:#2E75B6;color:white;padding:16px 24px;border-radius:8px 8px 0 0;">
        <h2 style="margin:0;">Job Search Update</h2>
        <p style="margin:4px 0 0;opacity:0.85;">{datetime.now().strftime('%B %d, %Y')} | {len(jobs)} new matches</p>
    </div>
    <table style="width:100%;border-collapse:collapse;background:white;">
        <tr style="background:#f8f9fa;"><th style="padding:8px;text-align:left;">Role</th><th style="padding:8px;">Location</th><th style="padding:8px;">Match</th><th style="padding:8px;">Sector</th></tr>
        {rows}
    </table>
    <div style="padding:16px;background:#f8f9fa;border-radius:0 0 8px 8px;text-align:center;font-size:13px;color:#6c757d;">
        Open your Job Search Command Center dashboard for full details and to take action.
    </div>
    </body></html>"""


def save_digest_html(data, config):
    """Save digest as local HTML file when SMTP is not configured."""
    new_jobs = [j for j in data.get("jobs", []) if j.get("status") == "new"]
    if not new_jobs:
        return

    html = build_digest_html(new_jobs)
    digest_file = SCRIPT_DIR / f"digest_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    with open(digest_file, 'w') as f:
        f.write(html)
    log(f"Digest saved to {digest_file}", data)


# =====================================================================
# MAIN SCAN ROUTINE
# =====================================================================

def run_scan(config, data):
    """Run the full job discovery scan."""
    log("Starting job scan...", data)

    # Generate search URLs
    urls = generate_search_urls(config)
    log(f"Generated {len(urls)} search URLs across {len(set(u['board'] for u in urls))} boards.", data)

    # Generate career page watchlist URLs
    career_urls = generate_career_page_urls(config)
    if career_urls:
        log(f"Generated {len(career_urls)} watchlist URLs from {len(set(u.get('company','') for u in career_urls))} watched companies.", data)
        urls.extend(career_urls)

    # Save URLs for browser automation or manual checking
    urls_file = SCRIPT_DIR / "search_urls.json"
    with open(urls_file, 'w') as f:
        json.dump(urls, f, indent=2)
    log(f"Search URLs saved to {urls_file}", data)

    # For now, process any manually added jobs and score them
    for job in data.get("jobs", []):
        if "match" not in job or job.get("needs_rescore"):
            job["match"] = score_job(
                job.get("title", ""),
                job.get("description", ""),
                job.get("company", ""),
                job.get("location", "")
            )
            job["sector"] = categorize_sector(
                job.get("title", ""),
                job.get("company", ""),
                job.get("description", "")
            )
            job["needs_rescore"] = False

    # Generate cover letter drafts for high match jobs
    if config["features"].get("coverletter_draft"):
        for job in data.get("jobs", []):
            if job.get("match", 0) >= 85 and not job.get("cover_letter"):
                for tone in ["confident", "warm", "formal"]:
                    job.setdefault("cover_letters", {})[tone] = generate_cover_letter_draft(job, config, tone)
                log(f"Generated 3 cover letter drafts for {job['title']} at {job['company']}", data)

    # Check for follow up reminders
    if config["features"].get("followup_reminders"):
        today = datetime.now().strftime("%Y-%m-%d")
        for app in data.get("applications", []):
            if app.get("followupDate") and app["followupDate"] <= today and app.get("status") not in ["rejected", "interview"]:
                log(f"FOLLOW UP DUE: {app['company']} : {app['role']} (applied {app['date']})", data)

    # Save updated data
    save_data(data)
    log(f"Scan complete. {len(data.get('jobs', []))} total jobs tracked.", data)

    # Send email digest if enabled
    if config["features"].get("email_digest"):
        send_email_digest(data, config)

    return data


# =====================================================================
# CLI INTERFACE
# =====================================================================

def main():
    config = load_config()
    data = load_data()

    args = sys.argv[1:]

    if "--help" in args:
        print(__doc__)
        return

    if "--urls" in args:
        # Just generate and print search URLs
        urls = generate_search_urls(config)
        career_urls = generate_career_page_urls(config)
        all_urls = urls + career_urls
        for u in all_urls:
            tag = f"[{u['board']}]"
            if u.get('type') == 'watchlist':
                tag = f"[WATCHLIST: {u.get('company', u['board'])}]"
            print(f"{tag} {u.get('keyword', '')} in {u.get('location', '')}")
            print(f"  {u['url']}")
        print(f"\n{len(urls)} board URLs + {len(career_urls)} watchlist URLs = {len(all_urls)} total")
        return

    if "--score" in args:
        # Score a job title from command line
        idx = args.index("--score")
        if idx + 1 < len(args):
            title = args[idx + 1]
            score = score_job(title)
            sector = categorize_sector(title, "")
            print(f"Title: {title}")
            print(f"Match Score: {score}%")
            print(f"Sector: {sector}")
        return

    if "--add" in args:
        # Add a job manually
        print("Add a new job listing:")
        title = input("  Title: ")
        company = input("  Company: ")
        location = input("  Location: ")
        url = input("  URL: ")
        description = input("  Description (optional): ")

        job = {
            "id": generate_job_id(title, company),
            "title": title,
            "company": company,
            "location": location,
            "url": url,
            "description": description,
            "match": score_job(title, description, company, location),
            "sector": categorize_sector(title, company, description),
            "posted": datetime.now().strftime("%Y-%m-%d"),
            "status": "new"
        }
        data.setdefault("jobs", []).append(job)
        save_data(data)
        print(f"\nAdded: {title} at {company}")
        print(f"Match Score: {job['match']}% | Sector: {job['sector']}")
        return

    if "--export" in args:
        # Export dashboard compatible JSON
        export_file = SCRIPT_DIR / "dashboard_import.json"
        with open(export_file, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Data exported to {export_file}")
        return

    # Default: run full scan
    run_scan(config, data)


if __name__ == "__main__":
    main()
