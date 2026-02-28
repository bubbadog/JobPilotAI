#!/usr/bin/env python3
"""
Setup Wizard — Interactive first-run configuration for JobPilotAI.
Guides users through profile setup, job search preferences, and board selection.

Usage:
    python main.py init
    # or directly:
    python setup_wizard.py
"""

import json
import re
import os
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

# ANSI colors
BLUE = '\033[0;34m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
RED = '\033[0;31m'
BOLD = '\033[1m'
NC = '\033[0m'  # No Color


class SetupWizard:
    """Interactive setup wizard for JobPilotAI."""

    def __init__(self, config_dir=None):
        self.config_dir = Path(config_dir) if config_dir else SCRIPT_DIR
        self.config = self._load_template()

    def _load_template(self):
        """Load the config template as starting point."""
        template = self.config_dir / "job_search_config.template.json"
        if template.exists():
            with open(template) as f:
                return json.load(f)
        # Minimal fallback
        return {
            "user": {"name": "", "email": "", "phone": "", "location": "", "linkedin": ""},
            "search": {"keywords": [], "locations": [], "excluded_companies": [], "min_match_score": 60, "max_age_days": 14},
            "features": {"discovery": True, "ranking": True, "coverletter_draft": True, "auto_apply_top": False, "auto_apply_all": False, "email_digest": False, "followup_reminders": True, "dedup": True, "salary_floor": False},
            "automation": {"mode": "semi-auto", "strategy": "balanced", "daily_target": 25, "pause_before_submit": True, "screenshot_before_submit": True},
            "boards": {},
            "schedule": {"frequency": "2x", "times": ["08:00", "14:00"]},
            "email_settings": {"notification_email": "", "smtp_server": "", "smtp_port": 587},
            "materials": {"ab_testing_enabled": True, "exploration_rate": 0.15, "default_sectors": ["tech", "general"]}
        }

    def run(self):
        """Run the full interactive setup flow."""
        self._print_welcome()
        self._collect_profile()
        self._collect_search_prefs()
        self._select_boards()
        self._configure_automation()
        self._optional_email_setup()
        self._optional_resume_parse()
        self._save_config()
        self._generate_search_urls()
        self._print_next_steps()

    def _print_welcome(self):
        print(f"\n{BLUE}")
        print("╔══════════════════════════════════════════════════╗")
        print("║     JobPilotAI — Setup Wizard                   ║")
        print("║     Let's configure your job search engine       ║")
        print("╚══════════════════════════════════════════════════╝")
        print(f"{NC}")
        print("I'll walk you through setting up your profile, search")
        print("preferences, and job board connections. This takes ~3 minutes.\n")
        print(f"  {YELLOW}Tip: Press Enter to skip optional fields.{NC}\n")

    def _prompt(self, label, default="", required=False, validator=None):
        """Prompt for input with optional validation."""
        while True:
            suffix = f" [{default}]" if default else ""
            prompt_str = f"  {BOLD}{label}{NC}{suffix}: "
            value = input(prompt_str).strip()
            if not value and default:
                value = default
            if required and not value:
                print(f"  {RED}This field is required.{NC}")
                continue
            if value and validator:
                error = validator(value)
                if error:
                    print(f"  {RED}{error}{NC}")
                    continue
            return value

    def _prompt_list(self, label, hint=""):
        """Prompt for a comma-separated list."""
        if hint:
            print(f"  {YELLOW}{hint}{NC}")
        raw = input(f"  {BOLD}{label}{NC}: ").strip()
        if not raw:
            return []
        return [item.strip() for item in raw.split(",") if item.strip()]

    def _prompt_choice(self, label, options, default=None):
        """Prompt for a numbered choice."""
        print(f"\n  {BOLD}{label}{NC}")
        for i, (key, desc) in enumerate(options.items(), 1):
            marker = " (default)" if key == default else ""
            print(f"    {i}. {desc}{marker}")
        while True:
            choice = input(f"  Choice [1-{len(options)}]: ").strip()
            if not choice and default:
                return default
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(options):
                    return list(options.keys())[idx]
            except (ValueError, IndexError):
                pass
            print(f"  {RED}Enter a number 1-{len(options)}{NC}")

    def _validate_email(self, email):
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            return "Invalid email format"
        return None

    def _validate_phone(self, phone):
        cleaned = re.sub(r'[\s\-\.\(\)]', '', phone)
        if not re.match(r'^\+?\d{7,15}$', cleaned):
            return "Invalid phone format (use digits, dashes, or parentheses)"
        return None

    def _collect_profile(self):
        """Collect user profile information."""
        print(f"\n{GREEN}━━━ Step 1/6: Your Profile ━━━{NC}\n")
        self.config["user"]["name"] = self._prompt("Full Name", required=True)
        self.config["user"]["email"] = self._prompt("Email", required=True, validator=self._validate_email)
        self.config["user"]["phone"] = self._prompt("Phone (optional)", validator=self._validate_phone)
        self.config["user"]["location"] = self._prompt("Location (city, state/country)", required=True)
        self.config["user"]["linkedin"] = self._prompt("LinkedIn URL (optional)")
        print(f"  {GREEN}✓ Profile saved{NC}")

    def _collect_search_prefs(self):
        """Collect job search preferences."""
        print(f"\n{GREEN}━━━ Step 2/6: Search Preferences ━━━{NC}\n")

        keywords = self._prompt_list(
            "Target job titles (comma-separated)",
            "e.g.: Product Manager, Software Engineer, Data Scientist"
        )
        if not keywords:
            print(f"  {YELLOW}⚠ No keywords entered — you can add them later in the config file.{NC}")
        self.config["search"]["keywords"] = keywords

        locations = self._prompt_list(
            "Search locations (comma-separated)",
            "e.g.: San Francisco CA, New York NY, Remote"
        )
        if not locations:
            locations = ["Remote"]
            print(f"  {YELLOW}Defaulting to: Remote{NC}")
        self.config["search"]["locations"] = locations

        excluded = self._prompt_list(
            "Companies to exclude (optional, comma-separated)",
            "e.g.: companies you've already worked at"
        )
        self.config["search"]["excluded_companies"] = excluded

        # Detect sectors from keywords
        detected_sectors = set()
        sector_map = {
            "tech": ["software", "engineer", "developer", "data", "AI", "ML", "cloud", "SaaS"],
            "biotech": ["biotech", "pharma", "clinical", "genomics", "life science"],
            "finance": ["finance", "banking", "fintech", "trading", "investment"],
            "healthcare": ["healthcare", "health", "medical", "clinical"],
            "defense": ["defense", "aerospace", "military", "government", "federal"],
        }
        for kw in keywords:
            kw_lower = kw.lower()
            for sector, triggers in sector_map.items():
                if any(t.lower() in kw_lower for t in triggers):
                    detected_sectors.add(sector)
        if detected_sectors:
            self.config["materials"]["default_sectors"] = list(detected_sectors) + ["general"]
            print(f"  {GREEN}✓ Detected sectors: {', '.join(detected_sectors)}{NC}")

        print(f"  {GREEN}✓ Search preferences saved{NC}")

    def _select_boards(self):
        """Select which job boards to enable."""
        print(f"\n{GREEN}━━━ Step 3/6: Job Boards ━━━{NC}\n")

        BOARDS = {
            "indeed": "Indeed — largest job aggregator",
            "linkedin": "LinkedIn — professional network jobs",
            "glassdoor": "Glassdoor — jobs with company reviews",
            "ziprecruiter": "ZipRecruiter — AI-matched jobs",
            "monster": "Monster — established job board",
            "dice": "Dice — tech & IT focused",
            "simplyhired": "SimplyHired — job aggregator",
            "wellfound": "Wellfound — startup jobs",
            "usajobs": "USAJobs — US government positions",
            "biospace": "BioSpace — biotech & pharma",
            "clearancejobs": "ClearanceJobs — security clearance",
            "weworkremotely": "We Work Remotely — remote only",
            "remoteok": "RemoteOK — remote jobs",
            "higheredjobs": "HigherEdJobs — education sector",
        }

        # Default enabled boards
        defaults = {"indeed", "linkedin", "glassdoor", "ziprecruiter", "monster", "simplyhired"}

        print("  Select job boards to search. Default boards are pre-selected.")
        print(f"  {YELLOW}Enter numbers to toggle, 'a' for all, 'd' for defaults, or Enter to continue:{NC}\n")

        enabled = set(defaults)
        board_keys = list(BOARDS.keys())

        while True:
            for i, (key, desc) in enumerate(BOARDS.items(), 1):
                marker = f"{GREEN}[✓]{NC}" if key in enabled else "[ ]"
                print(f"    {i:2}. {marker} {desc}")

            choice = input(f"\n  Toggle (1-{len(BOARDS)}), 'a'=all, 'd'=defaults, Enter=done: ").strip().lower()
            if not choice:
                break
            if choice == 'a':
                enabled = set(board_keys)
                continue
            if choice == 'd':
                enabled = set(defaults)
                continue
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(board_keys):
                    key = board_keys[idx]
                    if key in enabled:
                        enabled.discard(key)
                    else:
                        enabled.add(key)
            except ValueError:
                pass

        # Update config boards
        for board_name in self.config.get("boards", {}):
            if board_name in BOARDS:
                self.config["boards"][board_name]["enabled"] = board_name in enabled

        print(f"  {GREEN}✓ {len(enabled)} boards enabled{NC}")

    def _configure_automation(self):
        """Configure automation mode and strategy."""
        print(f"\n{GREEN}━━━ Step 4/6: Automation ━━━{NC}\n")

        mode = self._prompt_choice("Automation mode:", {
            "semi-auto": "Semi-Auto — discover jobs, you review & apply (recommended for new users)",
            "batch": "Batch — queue jobs for batch review, then apply selected",
            "full-auto": "Full-Auto — discover and auto-apply to high-match jobs (advanced)",
        }, default="semi-auto")
        self.config["automation"]["mode"] = mode

        strategy = self._prompt_choice("Search strategy:", {
            "wide-net": "Wide Net — cast broadly, lower match threshold (40+ jobs/day)",
            "balanced": "Balanced — moderate filtering, good coverage (25 jobs/day)",
            "targeted": "Targeted — high match only, quality over quantity (10 jobs/day)",
        }, default="balanced")
        self.config["automation"]["strategy"] = strategy

        if mode == "full-auto":
            print(f"\n  {YELLOW}⚠ Full-auto mode will submit applications without review.")
            print(f"  Safety settings enabled: screenshot before submit, pause on first run.{NC}")
            self.config["automation"]["pause_before_submit"] = True
            self.config["automation"]["screenshot_before_submit"] = True

        print(f"  {GREEN}✓ Automation configured: {mode} / {strategy}{NC}")

    def _optional_email_setup(self):
        """Optionally configure email notifications."""
        print(f"\n{GREEN}━━━ Step 5/6: Notifications (optional) ━━━{NC}\n")

        setup_email = input(f"  Set up email notifications? (y/N): ").strip().lower()
        if setup_email != 'y':
            print(f"  {YELLOW}Skipped — you can set this up later in .env{NC}")
            return

        email = self._prompt("Notification email", default=self.config["user"]["email"])
        self.config["email_settings"]["notification_email"] = email

        print(f"\n  {YELLOW}For Gmail, use an App Password (not your regular password).")
        print(f"  Generate one at: https://myaccount.google.com/apppasswords{NC}\n")

        smtp_server = self._prompt("SMTP server", default="smtp.gmail.com")
        smtp_port = self._prompt("SMTP port", default="587")

        # Save SMTP credentials to .env (never in JSON)
        smtp_user = self._prompt("SMTP username (email)")
        smtp_pass = self._prompt("SMTP password/app password")

        if smtp_user and smtp_pass:
            env_file = self.config_dir / ".env"
            env_lines = []
            if env_file.exists():
                with open(env_file) as f:
                    env_lines = f.readlines()

            # Update or append SMTP settings
            env_dict = {}
            for line in env_lines:
                if '=' in line and not line.startswith('#'):
                    k, v = line.strip().split('=', 1)
                    env_dict[k] = v

            env_dict['SMTP_SERVER'] = smtp_server
            env_dict['SMTP_PORT'] = smtp_port
            env_dict['SMTP_USER'] = smtp_user
            env_dict['SMTP_PASS'] = smtp_pass
            env_dict['NOTIFICATION_EMAIL'] = email

            with open(env_file, 'w') as f:
                f.write("# JobPilotAI — Environment Variables (auto-generated)\n")
                f.write("# SECURITY: Never commit this file.\n\n")
                for k, v in env_dict.items():
                    f.write(f"{k}={v}\n")

            print(f"  {GREEN}✓ SMTP credentials saved to .env{NC}")

        self.config["email_settings"]["smtp_server"] = smtp_server
        self.config["email_settings"]["smtp_port"] = int(smtp_port)
        self.config["features"]["email_digest"] = True

    def _optional_resume_parse(self):
        """Offer to parse a resume if found."""
        print(f"\n{GREEN}━━━ Step 6/6: Resume (optional) ━━━{NC}\n")

        # Look for resume files
        resume_files = []
        for ext in ["*.pdf", "*.docx"]:
            resume_files.extend(self.config_dir.glob(ext))

        if resume_files:
            print("  Found these files that might be resumes:")
            for i, f in enumerate(resume_files, 1):
                print(f"    {i}. {f.name}")
            choice = input(f"\n  Parse one? Enter number or Enter to skip: ").strip()
            if choice:
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(resume_files):
                        print(f"  Parsing {resume_files[idx].name}...")
                        try:
                            from resume_parser import ResumeParser
                            parser = ResumeParser()
                            profile = parser.parse(str(resume_files[idx]))
                            profile_file = self.config_dir / "resume_profile.json"
                            with open(profile_file, 'w') as f:
                                json.dump(profile, f, indent=2)
                            print(f"  {GREEN}✓ Resume parsed! Profile saved to resume_profile.json{NC}")
                        except Exception as e:
                            print(f"  {YELLOW}⚠ Parse error: {e}")
                            print(f"  You can retry later: python main.py resume --file {resume_files[idx].name}{NC}")
                except (ValueError, IndexError):
                    pass
        else:
            print(f"  {YELLOW}No resume files found in this directory.")
            print(f"  Place your resume (PDF/DOCX) here and run: python main.py resume --file your_resume.pdf{NC}")

    def _save_config(self):
        """Save the configuration to job_search_config.json."""
        config_file = self.config_dir / "job_search_config.json"
        with open(config_file, 'w') as f:
            json.dump(self.config, f, indent=2)
        print(f"\n  {GREEN}✓ Configuration saved to job_search_config.json{NC}")

    def _generate_search_urls(self):
        """Generate search URLs from config."""
        try:
            from config_manager import ConfigManager
            cm = ConfigManager(self.config_dir)
            urls = cm.generate_search_urls()
            print(f"  {GREEN}✓ Generated {len(urls)} search URLs{NC}")
        except Exception as e:
            print(f"  {YELLOW}⚠ Could not generate search URLs: {e}{NC}")

    def _print_next_steps(self):
        """Print what to do next."""
        print(f"\n{GREEN}╔══════════════════════════════════════════════════╗")
        print(f"║   Setup complete! You're ready to search.        ║")
        print(f"╚══════════════════════════════════════════════════╝{NC}\n")
        print(f"  {BLUE}Run your first discovery scan:{NC}")
        print(f"    python main.py discover\n")
        print(f"  {BLUE}Run a full cycle (discover → score → dedup → queue):{NC}")
        print(f"    python main.py full-cycle --strategy {self.config['automation']['strategy']}\n")
        print(f"  {BLUE}Open the dashboard:{NC}")
        print(f"    Open JobPilotAI.html in your browser\n")
        print(f"  {BLUE}Re-run setup anytime:{NC}")
        print(f"    python main.py init\n")


if __name__ == "__main__":
    wizard = SetupWizard()
    wizard.run()
