#!/usr/bin/env python3
"""
Config Manager — Unified configuration that merges job_search_config.json,
career_pages.json, dashboard exports, and automation settings.
"""

import json
import os
import re
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent

# =====================================================================
# DEFAULT AUTOMATION CONFIG
# =====================================================================

DEFAULT_AUTOMATION = {
    "mode": "semi-auto",         # semi-auto | batch | full-auto
    "strategy": "balanced",      # wide-net | balanced | targeted
    "daily_target": 25,
    "strategy_thresholds": {
        "wide-net":  {"min_score": 50, "target_per_day": 40, "quick_apply_min": 40},
        "balanced":  {"min_score": 60, "target_per_day": 25, "quick_apply_min": 50},
        "targeted":  {"min_score": 85, "target_per_day": 15, "quick_apply_min": 50}
    },
    "pause_before_submit": True,
    "screenshot_before_submit": True,
    "max_concurrent_boards": 3,
    "resume_file": None,
    "dry_run": False,
}

DEFAULT_BOARD_CONFIG = {
    # Major aggregators
    "indeed": {
        "enabled": True, "priority": 1,
        "search_url": "https://www.indeed.com/jobs?q={query}&l={location}&fromage=7&sort=date",
        "has_easy_apply": True,
        "selectors": {
            "job_cards": ".job_seen_beacon, .resultContent",
            "title": "h2.jobTitle a, .jobTitle > a",
            "company": "[data-testid='company-name'], .companyName",
            "location": "[data-testid='text-location'], .companyLocation",
            "link": "h2.jobTitle a",
            "next_page": "[data-testid='pagination-page-next'], a[aria-label='Next Page']",
            "description": "#jobDescriptionText",
            "salary": ".salary-snippet, [data-testid='attribute_snippet_testid']",
            "posted": ".date",
        }
    },
    "linkedin": {
        "enabled": True, "priority": 1,
        "search_url": "https://www.linkedin.com/jobs/search/?keywords={query}&location={location}&f_TPR=r604800&sortBy=DD",
        "has_easy_apply": True,
        "requires_login": True,
        "selectors": {
            "job_cards": ".jobs-search-results__list-item, .job-card-container",
            "title": ".job-card-list__title, .job-card-container__link",
            "company": ".job-card-container__primary-description, .artdeco-entity-lockup__subtitle",
            "location": ".job-card-container__metadata-wrapper, .artdeco-entity-lockup__caption",
            "link": ".job-card-list__title a, .job-card-container__link",
            "next_page": "button[aria-label='Next']",
            "description": ".jobs-description__content",
            "easy_apply_btn": ".jobs-apply-button",
        }
    },
    "glassdoor": {
        "enabled": True, "priority": 1,
        "search_url": "https://www.glassdoor.com/Job/jobs.htm?sc.keyword={query}&locT=C&locKeyword={location}&fromAge=7",
        "has_easy_apply": True,
        "selectors": {
            "job_cards": "[data-test='jobListing'], .JobsList_jobListItem__wjTHv",
            "title": "[data-test='job-title'], .JobCard_jobTitle__GLyJ1",
            "company": "[data-test='employer-short-name'], .EmployerProfile_employerName__C1_UV",
            "location": "[data-test='emp-location'], .JobCard_location__N_iYE",
            "link": "[data-test='job-title'] a, .JobCard_jobTitle__GLyJ1 a",
            "next_page": "button[data-test='pagination-next']",
            "description": "#JobDescriptionContainer",
            "salary": "[data-test='detailSalary']",
        }
    },
    "ziprecruiter": {
        "enabled": True, "priority": 2,
        "search_url": "https://www.ziprecruiter.com/jobs-search?search={query}&location={location}&days=7",
        "has_easy_apply": True,
        "selectors": {
            "job_cards": ".job_content, article.job-listing",
            "title": ".job_title a, h2.job_title",
            "company": ".job_org, .t_org_link",
            "location": ".job_location, .t_location_link",
            "link": ".job_title a",
            "next_page": ".pagination a.next",
            "description": ".job_description",
        }
    },
    "monster": {
        "enabled": True, "priority": 2,
        "search_url": "https://www.monster.com/jobs/search?q={query}&where={location}&page=1&so=m.h.s",
        "has_easy_apply": False,
        "selectors": {
            "job_cards": "[data-testid='svx-job-card'], .job-search-resultsstyle__JobCardComponent",
            "title": "[data-testid='svx-job-title'], .job-search-resultsstyle__TitleLinkA",
            "company": "[data-testid='svx-job-company'], .job-search-resultsstyle__CompanySpan",
            "location": "[data-testid='svx-job-location'], .job-search-resultsstyle__LocationSpan",
            "link": "[data-testid='svx-job-title'] a",
            "next_page": "[data-testid='svx-pagination-next']",
            "description": "#JobDescription",
        }
    },
    "careerbuilder": {
        "enabled": True, "priority": 3,
        "search_url": "https://www.careerbuilder.com/jobs?keywords={query}&location={location}&posted=7",
        "has_easy_apply": False,
        "selectors": {
            "job_cards": ".data-results-content-parent, .job-listing-item",
            "title": ".data-results-title a, .job-listing-title",
            "company": ".data-details .data-details-company, .data-results-company",
            "location": ".data-details .data-details-location, .data-results-location",
            "link": ".data-results-title a",
            "next_page": "a.arrow-right, a[aria-label='Next']",
        }
    },
    # Tech / PM boards
    "dice": {
        "enabled": True, "priority": 2,
        "search_url": "https://www.dice.com/jobs?q={query}&location={location}&countryCode=US&radius=30&radiusUnit=mi&page=1&pageSize=20&language=en&eid=S2Q_",
        "has_easy_apply": True,
        "selectors": {
            "job_cards": "[data-cy='search-card'], .card",
            "title": "[data-cy='card-title'] a, .card-title-link",
            "company": "[data-cy='search-result-company-name'], .card-company",
            "location": "[data-cy='search-result-location'], .card-location",
            "link": "[data-cy='card-title'] a",
            "next_page": "li.pagination-next a",
        }
    },
    "builtin": {
        "enabled": True, "priority": 2,
        "search_url": "https://builtin.com/jobs?search={query}&location={location}",
        "has_easy_apply": False,
        "selectors": {
            "job_cards": ".job-bounded-responsive, [data-id='job-card']",
            "title": "h2 a, .job-title a",
            "company": ".company-title, .company-name",
            "location": ".job-location, .location",
            "link": "h2 a, .job-title a",
            "next_page": ".pager-next a",
        }
    },
    "wellfound": {
        "enabled": True, "priority": 2,
        "search_url": "https://wellfound.com/jobs?q={query}&l={location}",
        "has_easy_apply": True,
        "selectors": {
            "job_cards": "[data-test='StartupResult'], .styles_component__ZzTAG",
            "title": ".styles_title__xpQDw, h4 a",
            "company": ".styles_name__xtFSj, .styles_component__mMGol a",
            "location": ".styles_location__GC12h, .styles_coarseLocation__r_oPd",
            "link": "h4 a, .styles_title__xpQDw a",
        }
    },
    # Biotech / Pharma
    "biospace": {
        "enabled": True, "priority": 1,
        "search_url": "https://www.biospace.com/jobs?keyword={query}&location={location}",
        "has_easy_apply": False,
        "selectors": {
            "job_cards": ".job-result, .card",
            "title": ".job-result-title a, h3 a",
            "company": ".job-result-company, .company-name",
            "location": ".job-result-location, .location",
            "link": ".job-result-title a, h3 a",
            "next_page": ".pagination .next a",
        }
    },
    "biopharmguy": {
        "enabled": True, "priority": 2,
        "search_url": "https://biopharmguy.com/jobs/?search={query}",
        "has_easy_apply": False,
    },
    # Government / Defense
    "usajobs": {
        "enabled": True, "priority": 1,
        "search_url": "https://www.usajobs.gov/Search/Results?k={query}&l={location}&d=AG&p=1",
        "has_easy_apply": False,
        "api_url": "https://data.usajobs.gov/api/search?Keyword={query}&LocationName={location}&ResultsPerPage=25",
        "selectors": {
            "job_cards": ".usajobs-search-result--core",
            "title": ".usajobs-search-result--item__header a",
            "company": ".usajobs-search-result--item__department",
            "location": ".usajobs-search-result--item__location",
            "link": ".usajobs-search-result--item__header a",
            "next_page": "a[rel='next']",
        }
    },
    "clearancejobs": {
        "enabled": True, "priority": 1,
        "search_url": "https://www.clearancejobs.com/jobs?keywords={query}&location={location}",
        "has_easy_apply": False,
        "selectors": {
            "job_cards": ".job-listing, .search-result",
            "title": ".job-title a, h3 a",
            "company": ".company-name, .employer",
            "location": ".job-location, .location",
            "link": ".job-title a, h3 a",
            "next_page": ".pagination .next a",
        }
    },
    # Remote
    "weworkremotely": {
        "enabled": True, "priority": 2,
        "search_url": "https://weworkremotely.com/remote-jobs/search?term={query}",
        "has_easy_apply": False,
        "selectors": {
            "job_cards": "li.feature, article",
            "title": ".title, h3 a",
            "company": ".company, h4",
            "location": "Remote",
            "link": "a[href*='/remote-jobs/']",
        }
    },
    "remoteok": {
        "enabled": True, "priority": 3,
        "search_url": "https://remoteok.com/remote-{query}-jobs",
        "has_easy_apply": False,
        "selectors": {
            "job_cards": "tr.job",
            "title": "h2[itemprop='title']",
            "company": "h3[itemprop='name']",
            "location": "Remote",
            "link": "a[href*='/remote-jobs/']",
        }
    },
    "flexjobs": {
        "enabled": True, "priority": 2,
        "search_url": "https://www.flexjobs.com/search?search={query}&location={location}",
        "has_easy_apply": False,
        "requires_login": True,
    },
    # Startup
    "ycombinator": {
        "enabled": True, "priority": 2,
        "search_url": "https://www.workatastartup.com/jobs?query={query}&location={location}",
        "has_easy_apply": True,
        "selectors": {
            "job_cards": ".job-listing, [class*='JobListing']",
            "title": ".job-name, h4",
            "company": ".company-name, h3",
            "location": ".location, .job-location",
            "link": "a[href*='/jobs/']",
        }
    },
    # Aggregator APIs
    "adzuna": {
        "enabled": True, "priority": 3,
        "api_url": "https://api.adzuna.com/v1/api/jobs/us/search/1?app_id={api_id}&app_key={api_key}&results_per_page=25&what={query}&where={location}&max_days_old=7",
        "has_easy_apply": False,
        "is_api": True,
    },
    "themuse": {
        "enabled": True, "priority": 3,
        "api_url": "https://www.themuse.com/api/public/jobs?category=Product+Management&location={location}&page=1",
        "has_easy_apply": False,
        "is_api": True,
    },
    "simplyhired": {
        "enabled": True, "priority": 3,
        "search_url": "https://www.simplyhired.com/search?q={query}&l={location}&fdb=7",
        "has_easy_apply": False,
        "selectors": {
            "job_cards": "[data-testid='searchSerpJob'], .SerpJob",
            "title": "[data-testid='searchSerpJobTitle'] a, .SerpJob-link",
            "company": "[data-testid='searchSerpJobCompany'], .SerpJob-company",
            "location": "[data-testid='searchSerpJobLocation'], .SerpJob-location",
            "link": "[data-testid='searchSerpJobTitle'] a",
            "next_page": "a[aria-label='Next']",
        }
    },
    # Education
    "higheredjobs": {
        "enabled": True, "priority": 2,
        "search_url": "https://www.higheredjobs.com/search/default.cfm?search={query}&location={location}",
        "has_easy_apply": False,
    },
}


class ConfigManager:
    """Unified configuration manager merging all config sources."""

    def __init__(self, config_dir=None):
        self.config_dir = Path(config_dir) if config_dir else SCRIPT_DIR
        self.config = self._load_all()

    def _load_all(self):
        """Load and merge all config sources."""
        config = {
            "user": {},
            "search": {},
            "boards": {},
            "automation": {**DEFAULT_AUTOMATION},
            "board_configs": {**DEFAULT_BOARD_CONFIG},
        }

        # 1. Load job_search_config.json (primary config)
        config_file = self.config_dir / "job_search_config.json"
        if config_file.exists():
            with open(config_file) as f:
                user_config = json.load(f)
            config["user"] = user_config.get("user", {})
            config["search"] = user_config.get("search", {})
            config["schedule"] = user_config.get("schedule", {})
            config["email_settings"] = user_config.get("email_settings", {})
            # Merge board enabled/disabled from user config
            for board_name, board_data in user_config.get("boards", {}).items():
                if board_name in config["board_configs"]:
                    config["board_configs"][board_name]["enabled"] = board_data.get("enabled", True)
                    if "url" in board_data:
                        config["board_configs"][board_name]["search_url"] = board_data["url"]
            # Merge automation overrides
            if "automation" in user_config:
                config["automation"].update(user_config["automation"])
            # Load AI config
            if "ai" in user_config:
                config["ai"] = user_config["ai"]
            # Load materials config
            if "materials" in user_config:
                config["materials"] = user_config["materials"]

        # Set AI defaults if not configured
        if "ai" not in config:
            config["ai"] = {
                "enabled": True,
                "default_model": "gemini",
                "max_tokens_cover_letter": 1500,
                "max_tokens_interview": 1000,
                "max_tokens_default": 1200,
                "ai_scoring_enabled": True,
                "ai_scoring_threshold": 70,
                "brave_search_enabled": True,
                "cache_ttl_hours": 24,
                "model_overrides": {},
            }

        # 2. Load career_pages.json (watchlist)
        career_file = self.config_dir / "career_pages.json"
        if career_file.exists():
            try:
                with open(career_file) as f:
                    config["watchlist"] = json.load(f)
            except (json.JSONDecodeError, IOError):
                config["watchlist"] = []
        else:
            config["watchlist"] = []

        # 3. Load dashboard export if available
        dashboard_file = self.config_dir / "dashboard_export.json"
        if dashboard_file.exists():
            try:
                with open(dashboard_file) as f:
                    dashboard = json.load(f)
                if "automationConfig" in dashboard:
                    config["automation"].update(dashboard["automationConfig"])
                if "qaBank" in dashboard:
                    config["qa_bank"] = dashboard["qaBank"]
                if "resumeProfile" in dashboard:
                    config["resume_profile"] = dashboard["resumeProfile"]
            except (json.JSONDecodeError, IOError):
                pass

        # 4. Load resume profile if exists
        resume_file = self.config_dir / "resume_profile.json"
        if resume_file.exists():
            try:
                with open(resume_file) as f:
                    config["resume_profile"] = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        return config

    def get(self, key, default=None):
        """Get a top-level config value."""
        return self.config.get(key, default)

    def get_enabled_boards(self):
        """Return list of enabled board configs sorted by priority."""
        boards = []
        for name, cfg in self.config["board_configs"].items():
            if cfg.get("enabled", True):
                boards.append({"name": name, **cfg})
        return sorted(boards, key=lambda b: b.get("priority", 99))

    def get_keywords(self):
        """Return search keywords."""
        return self.config.get("search", {}).get("keywords", [])

    def get_locations(self):
        """Return search locations."""
        return self.config.get("search", {}).get("locations", [])

    def get_strategy_threshold(self):
        """Return the min score threshold for current strategy."""
        strategy = self.config["automation"]["strategy"]
        thresholds = self.config["automation"]["strategy_thresholds"]
        return thresholds.get(strategy, thresholds["balanced"])

    def get_automation_mode(self):
        """Return current automation mode."""
        return self.config["automation"]["mode"]

    def get_watchlist(self):
        """Return active watchlist companies."""
        return [w for w in self.config.get("watchlist", []) if w.get("status", "active") == "active"]

    def save_config(self):
        """Save the merged config back to disk."""
        config_file = self.config_dir / "job_search_config.json"
        # Build the config in original format
        save_data = {
            "user": self.config.get("user", {}),
            "search": self.config.get("search", {}),
            "boards": {},
            "automation": self.config.get("automation", {}),
            "schedule": self.config.get("schedule", {}),
            "email_settings": self.config.get("email_settings", {}),
        }
        # Convert board_configs back to simple format
        for name, cfg in self.config["board_configs"].items():
            save_data["boards"][name] = {
                "enabled": cfg.get("enabled", True),
                "url": cfg.get("search_url", "")
            }
        with open(config_file, 'w') as f:
            json.dump(save_data, f, indent=2)

    def reload(self):
        """Reload all config from disk."""
        self.config = self._load_all()

    def generate_search_urls(self):
        """Generate search URL combos from config keywords × locations × enabled boards.
        Returns list of dicts and saves to search_urls.json."""
        urls = []
        keywords = self.get_keywords()
        locations = self.get_locations()

        if not keywords:
            return urls

        # If no locations specified, use empty string (for remote/any)
        if not locations:
            locations = [""]

        for board in self.get_enabled_boards():
            search_url = board.get("search_url", "")
            if not search_url:
                continue  # Skip API-only boards

            for keyword in keywords:
                for location in locations:
                    url = search_url.replace("{query}", keyword.replace(" ", "+"))
                    url = url.replace("{location}", location.replace(" ", "+"))
                    urls.append({
                        "board": board["name"],
                        "keyword": keyword,
                        "location": location,
                        "url": url,
                        "enabled": True
                    })

        # Save to search_urls.json
        urls_file = self.config_dir / "search_urls.json"
        with open(urls_file, 'w') as f:
            json.dump(urls, f, indent=2)

        return urls

    def validate_config(self):
        """Return list of validation errors/warnings. Empty list = valid."""
        errors = []
        user = self.config.get("user", {})
        search = self.config.get("search", {})

        # Check required fields
        if not user.get("name"):
            errors.append("Missing user name — run 'python main.py init' to configure")
        if not user.get("email"):
            errors.append("Missing email — needed for job applications")

        # Validate email format if provided
        email = user.get("email", "")
        if email and not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            errors.append(f"Invalid email format: {email}")

        # Check search config
        if not search.get("keywords"):
            errors.append("No search keywords configured — add job titles to search for")
        if not search.get("locations"):
            errors.append("No locations configured — add cities/regions to search in (or use 'Remote')")

        # Check boards
        enabled = self.get_enabled_boards()
        if not enabled:
            errors.append("No job boards enabled — enable at least one board")

        return errors

    @staticmethod
    def load_secret(key, fallback=None):
        """Load a secret from environment variables only. Never store secrets in JSON config."""
        return os.environ.get(key, fallback)
