#!/usr/bin/env python3
"""
Enhanced Scoring Engine — Multi-dimensional job scoring with adaptive weights,
strategy awareness, and learning from interview outcomes.
"""

import json
import re
from pathlib import Path
from datetime import datetime, timedelta

SCRIPT_DIR = Path(__file__).parent

# =====================================================================
# KEYWORD DICTIONARIES
# =====================================================================

RESUME_KEYWORDS = {
    "high_value": {
        "product manager": 4, "product management": 4, "AI": 3, "machine learning": 3,
        "biotechnology": 3, "biotech": 3, "pharma": 3, "bioinformatics": 3,
        "data governance": 3, "analytics": 2, "SaaS": 3, "agile": 2, "scrum": 2,
        "cross functional": 2, "roadmap": 2, "stakeholder": 2, "strategy": 2,
        "LLM": 3, "generative AI": 3, "python": 2, "AWS": 2, "program manager": 3,
        "product strategy": 3, "user research": 2, "product owner": 3,
    },
    "medium_value": {
        "MBA": 2, "digital": 1, "platform": 2, "quality control": 2,
        "QC": 1, "lab": 1, "regulatory": 2, "compliance": 2, "clinical": 2,
        "R&D": 2, "research": 1, "innovation": 1, "startup": 2,
        "defense": 2, "aerospace": 2, "government": 1, "project manager": 2,
        "adjunct": 2, "professor": 2, "instructor": 2, "teaching": 1,
    },
    "low_value": {
        "leadership": 1, "communication": 1, "presentation": 1, "excel": 1,
        "sql": 1, "tableau": 1, "visualization": 1, "reporting": 1,
        "analysis": 1, "team": 1, "collaboration": 1, "documentation": 1,
        "budget": 1, "jira": 1, "confluence": 1,
    }
}

# Title patterns that indicate seniority match
SENIORITY_BOOSTS = {
    "senior": 8, "sr": 8, "lead": 10, "principal": 6,
    "head of": 5, "director": 3, "vp": -5, "chief": -10,
    "junior": -10, "jr": -10, "entry": -15, "intern": -20, "associate": -5,
}

# Company tier boosts
COMPANY_TIERS = {
    "tier1": {
        "names": ["amgen", "google", "apple", "microsoft", "meta", "amazon", "nvidia",
                  "genentech", "gilead", "abbvie", "regeneron", "illumina", "thermo fisher",
                  "boeing", "lockheed martin", "raytheon", "northrop grumman", "spacex"],
        "boost": 10
    },
    "tier2": {
        "names": ["snap", "salesforce", "adobe", "netflix", "uber", "airbnb", "stripe",
                  "moderna", "biogen", "vertex", "exact sciences", "10x genomics",
                  "general atomics", "l3harris", "bae systems", "aerojet"],
        "boost": 7
    },
    "tier3": {
        "names": ["startup", "series a", "series b", "seed stage", "ycombinator"],
        "boost": 5
    }
}

# Location scoring — loaded from config; empty default means no location bias
# Users set their preferred locations via the setup wizard or config file.
PREFERRED_LOCATIONS = {
    "remote": 12, "work from home": 12, "hybrid": 8,
}


class ScoringEngine:
    """Multi-dimensional job scoring with adaptive weights."""

    def __init__(self, config_manager=None):
        self.config = config_manager
        self.adaptive_weights = self._load_adaptive_weights()
        self.strategy = "balanced"
        if config_manager:
            self.strategy = config_manager.get("automation", {}).get("strategy", "balanced")

        # Load scoring weights from config, with hardcoded defaults as fallback
        if config_manager:
            user_config = config_manager.config
            scoring_cfg = user_config.get("scoring", {})
            if scoring_cfg.get("keyword_weights"):
                # Merge user keyword weights with defaults
                self.keyword_weights = {**RESUME_KEYWORDS, **scoring_cfg["keyword_weights"]}
            else:
                self.keyword_weights = RESUME_KEYWORDS
            if scoring_cfg.get("seniority_boosts"):
                self.seniority_boosts = {**SENIORITY_BOOSTS, **scoring_cfg["seniority_boosts"]}
            else:
                self.seniority_boosts = SENIORITY_BOOSTS
            if scoring_cfg.get("company_tiers"):
                self.company_tiers = scoring_cfg["company_tiers"]
            else:
                self.company_tiers = COMPANY_TIERS
            if scoring_cfg.get("preferred_locations"):
                self.preferred_locations = {**PREFERRED_LOCATIONS, **scoring_cfg["preferred_locations"]}
            else:
                self.preferred_locations = PREFERRED_LOCATIONS
        else:
            self.keyword_weights = RESUME_KEYWORDS
            self.seniority_boosts = SENIORITY_BOOSTS
            self.company_tiers = COMPANY_TIERS
            self.preferred_locations = PREFERRED_LOCATIONS

    def _load_adaptive_weights(self):
        """Load learned weights from interview outcome data."""
        weights_file = SCRIPT_DIR / "scoring_weights.json"
        if weights_file.exists():
            try:
                with open(weights_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {"keyword_boosts": {}, "company_boosts": {}, "title_boosts": {}}

    def score(self, job):
        """Score a job listing. Returns dict with total score and breakdown.

        Args:
            job: Dict with title, description, company, location, salary_range,
                 posted_date, easy_apply, board_source, etc.

        Returns:
            Dict with 'total' (0-100) and 'breakdown' with per-dimension scores.
        """
        breakdown = {}

        # 1. Keyword match (0-30)
        breakdown["keywords"] = self._score_keywords(job)

        # 2. Title match (0-20)
        breakdown["title"] = self._score_title(job)

        # 3. Seniority fit (0-15)
        breakdown["seniority"] = self._score_seniority(job)

        # 4. Location match (0-15)
        breakdown["location"] = self._score_location(job)

        # 5. Company tier (0-10)
        breakdown["company"] = self._score_company(job)

        # 6. Freshness (0-10)
        breakdown["freshness"] = self._score_freshness(job)

        # Bonuses
        bonuses = 0
        if job.get("easy_apply"):
            bonuses += 3
        if job.get("salary_range"):
            bonuses += 2
        # Watchlist company bonus
        if self.config:
            watchlist = self.config.get_watchlist()
            company_lower = (job.get("company") or "").lower()
            if any(w.get("companyName", "").lower() == company_lower for w in watchlist):
                bonuses += 5
        breakdown["bonuses"] = min(bonuses, 10)

        # Adaptive adjustments from learning
        adaptive = self._apply_adaptive(job)
        breakdown["adaptive"] = adaptive

        # Total
        raw_total = sum(breakdown.values())
        total = max(0, min(100, int(raw_total)))

        return {
            "total": total,
            "breakdown": breakdown,
            "strategy": self.strategy,
            "meets_threshold": self._meets_threshold(total),
            "apply_type": self._get_apply_type(total),
        }

    def _score_keywords(self, job):
        """Score based on keyword matches in title + description."""
        text = f"{job.get('title', '')} {job.get('description', '')}".lower()
        score = 0
        max_possible = 0

        for keyword, weight in self.keyword_weights["high_value"].items():
            max_possible += weight
            if keyword.lower() in text:
                score += weight

        for keyword, weight in self.keyword_weights["medium_value"].items():
            max_possible += weight
            if keyword.lower() in text:
                score += weight

        for keyword, weight in self.keyword_weights["low_value"].items():
            max_possible += weight
            if keyword.lower() in text:
                score += weight

        if max_possible == 0:
            return 0
        return min(30, int((score / max_possible) * 30))

    def _score_title(self, job):
        """Score based on how well the title matches target roles."""
        title = (job.get("title") or "").lower()
        score = 0

        target_roles = [
            ("product manager", 20), ("program manager", 15), ("product owner", 14),
            ("ai product", 18), ("ml product", 18), ("data product", 16),
            ("technical product", 16), ("product strategy", 15),
            ("adjunct", 12), ("professor", 12), ("instructor", 12),
            ("project manager", 10), ("data governance", 14),
            ("quality control", 10), ("quality assurance", 8),
        ]

        for role, points in target_roles:
            if role in title:
                score = max(score, points)

        return min(20, score)

    def _score_seniority(self, job):
        """Score based on seniority level match."""
        title = (job.get("title") or "").lower()
        score = 8  # Base: assume mid-level match

        for level, boost in self.seniority_boosts.items():
            if level in title:
                score += boost
                break

        return max(0, min(15, score))

    def _score_location(self, job):
        """Score based on location preference."""
        location = (job.get("location") or "").lower()
        score = 0

        for loc, points in self.preferred_locations.items():
            if loc in location:
                score = max(score, points)

        return min(15, score)

    def _score_company(self, job):
        """Score based on company tier."""
        company = (job.get("company") or "").lower()
        description = (job.get("description") or "").lower()
        text = f"{company} {description}"

        for tier_name, tier_data in self.company_tiers.items():
            for name in tier_data["names"]:
                if name in text:
                    return min(10, tier_data["boost"])

        return 3  # Default: unknown company gets some baseline

    def _score_freshness(self, job):
        """Score based on how recently the job was posted."""
        posted = job.get("posted_date", "")
        if not posted:
            return 5  # Unknown = moderate

        try:
            posted_dt = datetime.strptime(posted[:10], "%Y-%m-%d")
            days_old = (datetime.now() - posted_dt).days

            if days_old <= 1:
                return 10
            elif days_old <= 3:
                return 8
            elif days_old <= 7:
                return 6
            elif days_old <= 14:
                return 4
            else:
                return 2
        except ValueError:
            return 5

    def _apply_adaptive(self, job):
        """Apply learned adaptive weight adjustments."""
        adjustment = 0
        title = (job.get("title") or "").lower()
        company = (job.get("company") or "").lower()

        # Check for title patterns that led to interviews
        for pattern, boost in self.adaptive_weights.get("title_boosts", {}).items():
            if pattern.lower() in title:
                adjustment += boost

        # Check for company boosts
        for comp, boost in self.adaptive_weights.get("company_boosts", {}).items():
            if comp.lower() in company:
                adjustment += boost

        return max(-10, min(10, adjustment))

    def _meets_threshold(self, score):
        """Check if score meets the current strategy threshold."""
        thresholds = {
            "wide-net": 50,
            "balanced": 60,
            "targeted": 85,
        }
        return score >= thresholds.get(self.strategy, 60)

    def _get_apply_type(self, score):
        """Determine how to apply based on score and strategy."""
        if self.strategy == "targeted":
            if score >= 85:
                return "full-prep"  # Full materials, custom cover letter
            elif score >= 50:
                return "quick-apply"  # Resume only, generic CL
            else:
                return "skip"
        elif self.strategy == "wide-net":
            if score >= 80:
                return "full-prep"
            elif score >= 50:
                return "quick-apply"
            else:
                return "skip"
        else:  # balanced
            if score >= 80:
                return "full-prep"
            elif score >= 60:
                return "quick-apply"
            else:
                return "skip"

    def learn_from_outcome(self, job, outcome):
        """Update adaptive weights based on interview/application outcome.

        Args:
            job: The job dict
            outcome: 'interview', 'offer', 'rejected', 'ghosted'
        """
        boost = {"interview": 3, "offer": 5, "rejected": -1, "ghosted": -2}.get(outcome, 0)
        if boost == 0:
            return

        title = (job.get("title") or "").lower()
        company = (job.get("company") or "").lower()

        # Extract title keywords to boost
        for word in title.split():
            if len(word) > 3:
                key = word.strip()
                current = self.adaptive_weights.get("title_boosts", {}).get(key, 0)
                self.adaptive_weights.setdefault("title_boosts", {})[key] = max(-5, min(5, current + boost))

        if company:
            current = self.adaptive_weights.get("company_boosts", {}).get(company, 0)
            self.adaptive_weights.setdefault("company_boosts", {})[company] = max(-5, min(5, current + boost))

        # Save weights
        weights_file = SCRIPT_DIR / "scoring_weights.json"
        with open(weights_file, 'w') as f:
            json.dump(self.adaptive_weights, f, indent=2)

    def batch_score(self, jobs):
        """Score a list of jobs and add score data to each.

        Returns:
            List of jobs sorted by score descending, with score data added.
        """
        for job in jobs:
            result = self.score(job)
            job["match"] = result["total"]
            job["score_breakdown"] = result["breakdown"]
            job["meets_threshold"] = result["meets_threshold"]
            job["apply_type"] = result["apply_type"]
            job["sector"] = self._categorize_sector(job)

        return sorted(jobs, key=lambda j: j["match"], reverse=True)

    def _categorize_sector(self, job):
        """Categorize job into a sector."""
        text = f"{job.get('title', '')} {job.get('company', '')} {job.get('description', '')}".lower()
        if any(w in text for w in ["biotech", "pharma", "clinical", "therapeutics", "drug", "genomic", "amgen", "genentech"]):
            return "biotech"
        if any(w in text for w in ["defense", "aerospace", "military", "dod", "clearance", "navy", "air force"]):
            return "defense"
        if any(w in text for w in ["adjunct", "professor", "instructor", "lecturer", "faculty", "university", "college"]):
            return "education"
        if any(w in text for w in ["government", "federal", "state of california", "county", "city of"]):
            return "government"
        if any(w in text for w in ["startup", "seed", "series a", "venture"]):
            return "startup"
        if any(w in text for w in ["remote", "anywhere"]):
            return "remote"
        return "tech"


def score_jobs(jobs, config_manager=None, strategy="balanced"):
    """Convenience function to score a list of jobs."""
    engine = ScoringEngine(config_manager)
    engine.strategy = strategy
    return engine.batch_score(jobs)
