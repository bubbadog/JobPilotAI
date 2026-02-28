# JobPilotAI

Your AI-powered job search automation engine.

![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)
![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)

## What is JobPilotAI?

JobPilotAI is an open-source job search automation engine that discovers jobs across 20+ boards, intelligently scores and ranks them by fit, manages your application pipeline, and optionally auto-applies with form-filling automation. It features A/B testing for resume and cover letter variants using epsilon-greedy selection, a beautiful single-file HTML dashboard, and a powerful CLI for power users.

## Features

- **Discovery Engine** — Scrapes 20+ job boards simultaneously with async concurrency and board-specific extractors
- **Smart Scoring** — Multi-dimensional ranking: keyword matching, seniority fit, location preference, company tier, and freshness
- **Deduplication** — Cross-board duplicate detection using fuzzy matching on title and company
- **Application Queue** — Prioritized apply pipeline with three automation modes (semi-auto, full-auto, batch preview)
- **ATS Automation** — Detects and fills Greenhouse, Lever, Workday, iCIMS, Taleo, SmartRecruiters, BrassRing, and Ashby forms using Playwright
- **A/B Testing** — Epsilon-greedy variant selection for resume and cover letter templates per job sector with funnel scoring (callbacks, interviews, offers, rejections, ghosted)
- **Dashboard** — Single-file HTML command center with 17 analytics panels, kanban views, interview coaching, and full data persistence via localStorage
- **Scheduler** — Cron-style automation for background discovery and application cycles
- **Security-First** — No credentials in code, input sanitization, XSS protection, rate limiting per board with exponential backoff
- **Q&A Bank** — LLM-ready interview preparation database with common application and technical questions

## Quick Start

### 1. Clone and Setup

```bash
git clone https://github.com/yourusername/JobPilotAI.git
cd JobPilotAI
chmod +x setup.sh && ./setup.sh
```

The setup script creates a Python virtual environment, installs dependencies, and downloads Playwright browsers.

### 2. Run the Wizard

```bash
source venv/bin/activate
python main.py init
```

This interactive wizard guides you through configuration: job boards, search parameters, resume parsing, and automation preferences.

### 3. Start Discovering

```bash
python main.py discover
```

## CLI Reference

```bash
# Discovery
python main.py discover                          # Scrape all boards
python main.py discover --boards indeed,linkedin # Specific boards only
python main.py discover --limit 20               # Limit results per board

# Applications
python main.py apply                             # Semi-auto (review each form)
python main.py apply --mode full-auto            # Fully automated submission
python main.py apply --mode batch                # Prep forms without submitting
python main.py apply --dry-run                   # Preview without form submission
python main.py apply --limit 10                  # Process N applications

# Full Cycle
python main.py full-cycle                        # Discover → Score → Dedup → Queue → Apply
python main.py full-cycle --dry-run              # Preview full cycle

# Resume Management
python main.py resume --file resume.pdf          # Parse and store resume
python main.py resume --show                     # Display parsed resume

# Materials A/B Testing
python main.py materials --list-resume           # Show resume variants and scores
python main.py materials --list-cl               # Show cover letter variants
python main.py materials --create-resume FILE SECTOR NAME  # Add new resume variant
python main.py materials --performance           # Compare A/B testing results

# Status and Analytics
python main.py status                            # Pipeline status
python main.py stats                             # Funnel analytics

# Scheduling
python main.py schedule                          # Start automation daemon
python main.py schedule --show                   # Show schedule config

# Q&A Bank
python main.py qa --list                         # Show interview questions
python main.py qa --add                          # Add custom questions
python main.py qa --export                       # Export for external use

# Export
python main.py export                            # Export data for dashboard import
```

## Architecture

JobPilotAI is organized into a discovery and application pipeline:

**Core Modules:**
- `main.py` — CLI orchestrator with 10 commands
- `job_discovery.py` — Multi-board concurrent scraping coordinator
- `job_scraper.py` — Playwright-based board-specific extractors
- `scoring_engine.py` — Weighted multi-criteria ranking algorithm
- `dedup_engine.py` — Fuzzy duplicate detection across boards
- `apply_engine.py` — Application queue processor with three automation modes
- `form_filler.py` — ATS form detection and automated field completion
- `material_manager.py` — Resume/cover letter A/B testing with epsilon-greedy selection
- `qa_bank.py` — Interview preparation question database
- `resume_parser.py` — PDF and DOCX resume parsing to structured JSON
- `config_manager.py` — Configuration validation and defaults
- `rate_limiter.py` — Per-board request throttling with exponential backoff
- `scheduler.py` — Cron-style automation runner
- `analytics.py` — Funnel tracking and performance metrics
- `security.py` — Input sanitization and credential management

**Dashboard:**
- `JobPilotAI.html` — Single-file HTML5 dashboard with embedded CSS and JavaScript (17 analytics panels, localStorage persistence, zero dependencies)

**Configuration:**
- `job_search_config.json` — Board configurations, search parameters, scoring weights, and automation settings
- `search_urls.json` — Pre-built search URLs for each board and keyword combination
- `job_search_data.json` — Runtime data store for discovered jobs and application records

## Configuration

All configuration is managed through three files:

**job_search_config.json** — Main configuration file containing board setup, search keywords, locations, scoring weights, and materials settings. The setup wizard populates this during initialization.

**sectors.json** — Job sector definitions for materials A/B testing (biotech, tech, defense, startup, education, general). Auto-detected from job title and company keywords.

**.env** (optional) — Environment variables for SMTP credentials, third-party API keys, and sensitive settings. Copy from `.env.example` and edit as needed.

## Supported Job Boards

Indeed, LinkedIn, Glassdoor, ZipRecruiter, Monster, Dice, RemoteOK, WeWorkRemotely, SimplyHired, USAJobs, Google Jobs, AngelList, The Muse, BuiltIn, Adzuna, Greenhouse Boards, Lever Boards, and company career pages.

## Supported ATS Systems

Greenhouse, Lever, Workday, iCIMS, Taleo, SmartRecruiters, BrassRing, and Ashby.

## Dashboard

Open `JobPilotAI.html` in any modern browser to view your job search pipeline. All data persists locally in browser storage — no server or login required.

**Data Import:** Export Python engine data and import into the dashboard:

```bash
python main.py export > engine_export.json
# Then in the dashboard, click "Import Engine Data" and select engine_export.json
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on reporting issues, submitting features, and code contributions.

## Security

See [SECURITY.md](SECURITY.md) for security policies, known vulnerabilities, and responsible disclosure guidelines.

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.
