"""
Material Manager — Resume & Cover Letter A/B Testing Engine
Job Search Command Center v4.1

Manages resume/CL variant creation, epsilon-greedy A/B assignment,
weighted funnel scoring, and performance tracking.

Usage:
    from material_manager import MaterialManager
    mgr = MaterialManager()

    # Create variants
    mgr.create_resume_variant("Tech-Focused", "resumes/tech_v1.pdf", "tech", "Emphasizes technical background")

    # Select best materials for a job
    resume_id, cl_id = mgr.select_best_materials({"sector": "tech", "title": "Engineer", "company": "Acme Corp"})

    # Record outcome
    pairing_id = mgr.create_material_pairing(app_id, job_id, resume_id, cl_id)
    mgr.record_pairing_outcome(pairing_id, "interview")
"""

import json
import random
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Union
from difflib import SequenceMatcher

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))

# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class ResumeVariant:
    """A resume version optimized for a specific sector/role."""
    id: str = ""
    name: str = ""
    file_path: str = ""
    sector: str = "general"            # biotech|tech|defense|education|startup|general
    description: str = ""
    created_at: str = ""
    created_by: str = "manual"         # manual|ai_suggested|ai_generated

    # Performance counters
    applications_used: int = 0
    callbacks: int = 0                 # Screening call/email reply
    interviews: int = 0                # Interview scheduled
    offers: int = 0                    # Offer received
    rejections: int = 0                # Explicit rejection
    ghosted: int = 0                   # No response after 3+ weeks

    # Calculated metrics (updated on each outcome)
    callback_rate: float = 0.0
    interview_rate: float = 0.0
    offer_rate: float = 0.0
    score: float = 0.0                 # Composite weighted score

    last_used_at: str = ""
    is_active: bool = True


@dataclass
class CoverLetterVariant:
    """A cover letter variant with tone + sector targeting."""
    id: str = ""
    name: str = ""
    tone: str = "confident"            # confident|warm|formal
    sector: str = "general"            # biotech|tech|defense|education|startup|general
    template_text: str = ""            # The actual CL template or text
    created_at: str = ""
    created_by: str = "manual"         # manual|ai_suggested|dashboard

    # Performance counters (same as resume)
    applications_used: int = 0
    callbacks: int = 0
    interviews: int = 0
    offers: int = 0
    rejections: int = 0
    ghosted: int = 0

    # Calculated metrics
    callback_rate: float = 0.0
    interview_rate: float = 0.0
    offer_rate: float = 0.0
    score: float = 0.0

    last_used_at: str = ""
    is_active: bool = True


@dataclass
class MaterialPairing:
    """Tracks which resume + CL combo was used for a specific application."""
    id: str = ""
    application_id: str = ""
    job_id: str = ""
    job_title: str = ""
    company: str = ""
    sector: str = ""
    resume_variant_id: str = ""
    cover_letter_variant_id: str = ""
    reason: str = "highest_score"      # highest_score|exploration|manual

    selected_at: str = ""
    outcome: str = ""                  # callback|interview|offer|rejected|ghosted
    outcome_recorded_at: str = ""

    # Debug/transparency
    resume_score_at_selection: float = 0.0
    cl_score_at_selection: float = 0.0
    epsilon_used: float = 0.0


# ============================================================
# SECTOR DETECTION — loaded from sectors.json (user-extensible)
# ============================================================

def _load_sectors():
    """Load sector definitions from sectors.json, with minimal fallback."""
    sectors_file = Path(__file__).parent / "sectors.json"
    if sectors_file.exists():
        try:
            with open(sectors_file) as f:
                raw = json.load(f)
            # Convert sectors.json format to keyword lists
            sector_kw = {}
            for sector, data in raw.items():
                if sector.startswith("_"):
                    continue  # Skip comments
                keywords = data.get("title_keywords", []) + data.get("company_keywords", [])
                if keywords:
                    sector_kw[sector] = [kw.lower() for kw in keywords]
            return sector_kw
        except (json.JSONDecodeError, IOError):
            pass
    # Minimal fallback if no sectors.json
    return {
        "tech": ["software", "saas", "cloud", "ai", "machine learning", "data science"],
        "biotech": ["biotech", "pharma", "clinical", "therapeutics", "life sciences"],
    }

SECTOR_KEYWORDS = _load_sectors()

def detect_sector(title: str, company: str = "", description: str = "") -> str:
    """Detect job sector from title, company, and description keywords."""
    text = f"{title} {company} {description}".lower()

    sector_scores = {}
    for sector, keywords in SECTOR_KEYWORDS.items():
        matches = sum(1 for kw in keywords if kw in text)
        if matches > 0:
            sector_scores[sector] = matches

    if sector_scores:
        return max(sector_scores, key=sector_scores.get)
    return "general"


# ============================================================
# SCORING ALGORITHM
# ============================================================

# Weighted funnel signal values
OUTCOME_WEIGHTS = {
    "callback": 1,
    "interview": 3,
    "offer": 5,
    "rejected": -1,
    "ghosted": -2,
}

MIN_APPS_FOR_FULL_CONFIDENCE = 3  # Below this, scores are discounted


def calculate_variant_score(variant: Union[ResumeVariant, CoverLetterVariant]) -> float:
    """
    Calculate composite performance score for a variant.

    Formula:
        raw = (callbacks*1 + interviews*3 + offers*5 - rejections*1 - ghosted*2) / max(apps, 1)
        score = raw * min(1.0, apps / MIN_APPS)  # Discount low-data variants

    Returns float score. Higher = better performing.
    """
    apps = max(variant.applications_used, 1)

    raw = (
        variant.callbacks * OUTCOME_WEIGHTS["callback"]
        + variant.interviews * OUTCOME_WEIGHTS["interview"]
        + variant.offers * OUTCOME_WEIGHTS["offer"]
        + variant.rejections * OUTCOME_WEIGHTS["rejected"]
        + variant.ghosted * OUTCOME_WEIGHTS["ghosted"]
    ) / apps

    # Discount score if insufficient data
    confidence = min(1.0, variant.applications_used / MIN_APPS_FOR_FULL_CONFIDENCE)
    return round(raw * confidence, 3)


def recalculate_rates(variant: Union[ResumeVariant, CoverLetterVariant]):
    """Recalculate rate fields and composite score."""
    apps = max(variant.applications_used, 1)
    variant.callback_rate = round(variant.callbacks / apps, 4)
    variant.interview_rate = round(variant.interviews / apps, 4)
    variant.offer_rate = round(variant.offers / apps, 4)
    variant.score = calculate_variant_score(variant)


# ============================================================
# MATERIAL MANAGER
# ============================================================

class MaterialManager:
    """
    Central manager for resume/CL variants, A/B assignment, and performance tracking.

    Persistence: material_variants.json in config_dir.
    """

    def __init__(self, config_dir=None):
        self.config_dir = Path(config_dir) if config_dir else SCRIPT_DIR
        self.data_file = self.config_dir / "material_variants.json"
        self.variants_dir = self.config_dir / "resume_variants"
        self.epsilon = 0.15  # 15% exploration rate
        self.data = self._load()

    # ── Persistence ──

    def _load(self) -> dict:
        """Load variant data from JSON file."""
        default = {
            "resume_variants": [],
            "cover_letter_variants": [],
            "material_pairings": [],
            "config": {
                "epsilon": 0.15,
                "min_apps_for_scoring": MIN_APPS_FOR_FULL_CONFIDENCE,
                "ab_testing_enabled": True,
            }
        }
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r') as f:
                    loaded = json.load(f)
                    # Merge with defaults for backward compat
                    for key in default:
                        if key not in loaded:
                            loaded[key] = default[key]
                    return loaded
            except (json.JSONDecodeError, IOError):
                return default
        return default

    def save(self):
        """Persist variant data to JSON."""
        with open(self.data_file, 'w') as f:
            json.dump(self.data, f, indent=2, default=str)

    # ── Resume Variant CRUD ──

    def create_resume_variant(self, name: str, file_path: str, sector: str,
                              description: str = "", created_by: str = "manual") -> str:
        """Create a new resume variant. Returns variant ID."""
        now = datetime.now()
        variant_id = f"resume_{sector}_{now.strftime('%Y%m%d%H%M%S')}_{len(self.data['resume_variants'])}"

        variant = ResumeVariant(
            id=variant_id,
            name=name,
            file_path=str(file_path),
            sector=sector,
            description=description,
            created_at=now.isoformat(),
            created_by=created_by,
        )

        self.data["resume_variants"].append(asdict(variant))
        self.save()
        return variant_id

    def list_resume_variants(self, active_only: bool = True, sector: str = None) -> List[dict]:
        """Get all resume variants with optional filtering."""
        variants = self.data.get("resume_variants", [])
        if active_only:
            variants = [v for v in variants if v.get("is_active", True)]
        if sector:
            variants = [v for v in variants if v.get("sector") == sector or v.get("sector") == "general"]
        return variants

    def get_resume_variant(self, variant_id: str) -> Optional[dict]:
        """Get single resume variant by ID."""
        for v in self.data.get("resume_variants", []):
            if v["id"] == variant_id:
                return v
        return None

    def update_resume_variant(self, variant_id: str, **kwargs) -> bool:
        """Update resume variant metadata."""
        for v in self.data.get("resume_variants", []):
            if v["id"] == variant_id:
                for key, val in kwargs.items():
                    if key in v:
                        v[key] = val
                self.save()
                return True
        return False

    def delete_resume_variant(self, variant_id: str) -> bool:
        """Soft-delete a resume variant (mark inactive)."""
        return self.update_resume_variant(variant_id, is_active=False)

    # ── Cover Letter Variant CRUD ──

    def create_cover_letter_variant(self, name: str, tone: str, sector: str,
                                    template_text: str = "", created_by: str = "manual") -> str:
        """Create a new cover letter variant. Returns variant ID."""
        now = datetime.now()
        variant_id = f"cl_{sector}_{tone}_{now.strftime('%Y%m%d%H%M%S')}_{len(self.data['cover_letter_variants'])}"

        variant = CoverLetterVariant(
            id=variant_id,
            name=name,
            tone=tone,
            sector=sector,
            template_text=template_text,
            created_at=now.isoformat(),
            created_by=created_by,
        )

        self.data["cover_letter_variants"].append(asdict(variant))
        self.save()
        return variant_id

    def list_cover_letter_variants(self, active_only: bool = True,
                                   sector: str = None, tone: str = None) -> List[dict]:
        """Get CL variants with optional filtering."""
        variants = self.data.get("cover_letter_variants", [])
        if active_only:
            variants = [v for v in variants if v.get("is_active", True)]
        if sector:
            variants = [v for v in variants if v.get("sector") == sector or v.get("sector") == "general"]
        if tone:
            variants = [v for v in variants if v.get("tone") == tone]
        return variants

    def get_cover_letter_variant(self, variant_id: str) -> Optional[dict]:
        """Get single CL variant by ID."""
        for v in self.data.get("cover_letter_variants", []):
            if v["id"] == variant_id:
                return v
        return None

    def update_cover_letter_variant(self, variant_id: str, **kwargs) -> bool:
        """Update CL variant metadata."""
        for v in self.data.get("cover_letter_variants", []):
            if v["id"] == variant_id:
                for key, val in kwargs.items():
                    if key in v:
                        v[key] = val
                self.save()
                return True
        return False

    def delete_cover_letter_variant(self, variant_id: str) -> bool:
        """Soft-delete a CL variant."""
        return self.update_cover_letter_variant(variant_id, is_active=False)

    # ── Material Pairing ──

    def create_material_pairing(self, application_id: str, job_id: str,
                                resume_variant_id: str, cover_letter_variant_id: str,
                                job_title: str = "", company: str = "",
                                sector: str = "", reason: str = "highest_score") -> str:
        """Record which materials were used for an application. Returns pairing ID."""
        now = datetime.now()
        pairing_id = f"pair_{now.strftime('%Y%m%d%H%M%S')}_{application_id[-6:]}"

        # Get variant scores at time of selection
        rv = self.get_resume_variant(resume_variant_id)
        cv = self.get_cover_letter_variant(cover_letter_variant_id)

        pairing = MaterialPairing(
            id=pairing_id,
            application_id=application_id,
            job_id=job_id,
            job_title=job_title,
            company=company,
            sector=sector,
            resume_variant_id=resume_variant_id,
            cover_letter_variant_id=cover_letter_variant_id,
            reason=reason,
            selected_at=now.isoformat(),
            resume_score_at_selection=rv.get("score", 0) if rv else 0,
            cl_score_at_selection=cv.get("score", 0) if cv else 0,
            epsilon_used=self.epsilon,
        )

        # Increment applications_used for both variants
        if rv:
            rv["applications_used"] = rv.get("applications_used", 0) + 1
            rv["last_used_at"] = now.isoformat()
            recalculate_rates_dict(rv)
        if cv:
            cv["applications_used"] = cv.get("applications_used", 0) + 1
            cv["last_used_at"] = now.isoformat()
            recalculate_rates_dict(cv)

        self.data["material_pairings"].append(asdict(pairing))
        self.save()
        return pairing_id

    def get_pairing(self, pairing_id: str) -> Optional[dict]:
        """Get pairing by ID."""
        for p in self.data.get("material_pairings", []):
            if p["id"] == pairing_id:
                return p
        return None

    def get_pairing_by_application(self, application_id: str) -> Optional[dict]:
        """Get pairing for a specific application."""
        for p in self.data.get("material_pairings", []):
            if p["application_id"] == application_id:
                return p
        return None

    def record_pairing_outcome(self, pairing_id: str, outcome: str) -> bool:
        """
        Record the outcome for a material pairing and update variant scores.

        Args:
            pairing_id: The pairing to update
            outcome: callback|interview|offer|rejected|ghosted

        Returns True if successful.
        """
        if outcome not in OUTCOME_WEIGHTS:
            print(f"Invalid outcome: {outcome}. Must be one of: {list(OUTCOME_WEIGHTS.keys())}")
            return False

        pairing = self.get_pairing(pairing_id)
        if not pairing:
            print(f"Pairing not found: {pairing_id}")
            return False

        # Update pairing
        pairing["outcome"] = outcome
        pairing["outcome_recorded_at"] = datetime.now().isoformat()

        # Update resume variant counters
        rv = self.get_resume_variant(pairing["resume_variant_id"])
        if rv:
            self._increment_outcome_counter(rv, outcome)
            recalculate_rates_dict(rv)

        # Update CL variant counters
        cv = self.get_cover_letter_variant(pairing["cover_letter_variant_id"])
        if cv:
            self._increment_outcome_counter(cv, outcome)
            recalculate_rates_dict(cv)

        self.save()
        return True

    def _increment_outcome_counter(self, variant: dict, outcome: str):
        """Increment the appropriate counter on a variant dict."""
        counter_map = {
            "callback": "callbacks",
            "interview": "interviews",
            "offer": "offers",
            "rejected": "rejections",
            "ghosted": "ghosted",
        }
        key = counter_map.get(outcome)
        if key:
            variant[key] = variant.get(key, 0) + 1

    # ── A/B Assignment Algorithm ──

    def select_best_materials(self, job_context: dict) -> Tuple[str, str, str]:
        """
        Epsilon-greedy variant selection for a job application.

        Args:
            job_context: {
                "title": str,
                "company": str,
                "sector": str (optional — auto-detected if missing),
                "description": str (optional),
                "apply_type": str (optional),
            }

        Returns:
            (resume_variant_id, cover_letter_variant_id, reason)
            reason is "highest_score", "exploration", or "only_option"
        """
        # Detect sector if not provided
        sector = job_context.get("sector") or detect_sector(
            job_context.get("title", ""),
            job_context.get("company", ""),
            job_context.get("description", ""),
        )

        # Get active variants for this sector
        resume_candidates = self.list_resume_variants(active_only=True, sector=sector)
        cl_candidates = self.list_cover_letter_variants(active_only=True, sector=sector)

        # Fallback to general if no sector-specific variants
        if not resume_candidates:
            resume_candidates = self.list_resume_variants(active_only=True, sector="general")
        if not cl_candidates:
            cl_candidates = self.list_cover_letter_variants(active_only=True, sector="general")

        # If still no variants, return empty (caller should use defaults)
        if not resume_candidates:
            return ("", "", "no_variants")
        if not cl_candidates:
            # Resume only — no CL variant
            best_resume, reason = self._epsilon_greedy_select(resume_candidates)
            return (best_resume["id"], "", reason)

        # Select resume and CL independently via epsilon-greedy
        best_resume, r_reason = self._epsilon_greedy_select(resume_candidates)
        best_cl, c_reason = self._epsilon_greedy_select(cl_candidates)

        # Use "exploration" if either was exploration
        reason = "exploration" if "exploration" in (r_reason, c_reason) else r_reason

        return (best_resume["id"], best_cl["id"], reason)

    def _epsilon_greedy_select(self, candidates: List[dict]) -> Tuple[dict, str]:
        """
        Epsilon-greedy selection from a list of variant dicts.

        Returns (selected_variant_dict, reason).
        """
        if len(candidates) == 1:
            return (candidates[0], "only_option")

        # Ensure scores are up-to-date
        for c in candidates:
            recalculate_rates_dict(c)

        if random.random() < self.epsilon:
            # Explore: random selection
            return (random.choice(candidates), "exploration")
        else:
            # Exploit: pick highest score (ties broken randomly)
            max_score = max(c.get("score", 0) for c in candidates)
            top_candidates = [c for c in candidates if c.get("score", 0) == max_score]
            return (random.choice(top_candidates), "highest_score")

    # ── Analytics & Comparison ──

    def get_variant_comparison(self, variant_type: str = "resume") -> dict:
        """
        Get performance comparison across all variants of a type.

        Returns:
            {
                "variants": [...sorted by score descending],
                "best_by_sector": {"biotech": "resume_biotech_v1", ...},
                "total_applications": int,
                "total_outcomes_recorded": int,
            }
        """
        if variant_type == "resume":
            variants = self.list_resume_variants(active_only=False)
        else:
            variants = self.list_cover_letter_variants(active_only=False)

        # Recalculate all scores
        for v in variants:
            recalculate_rates_dict(v)

        # Sort by score descending
        variants.sort(key=lambda v: v.get("score", 0), reverse=True)

        # Add status labels
        for v in variants:
            apps = v.get("applications_used", 0)
            score = v.get("score", 0)
            if apps < MIN_APPS_FOR_FULL_CONFIDENCE:
                v["status"] = "needs_data"
            elif score > 1.5:
                v["status"] = "performing"
            elif score < -0.5:
                v["status"] = "underperforming"
            else:
                v["status"] = "neutral"

        # Best by sector
        best_by_sector = {}
        sectors = set(v.get("sector", "general") for v in variants if v.get("is_active", True))
        for sector in sectors:
            sector_variants = [v for v in variants if v.get("sector") == sector and v.get("is_active", True)]
            if sector_variants:
                best_by_sector[sector] = sector_variants[0]["id"]  # Already sorted by score

        total_apps = sum(v.get("applications_used", 0) for v in variants)
        total_outcomes = sum(
            v.get("callbacks", 0) + v.get("interviews", 0) + v.get("offers", 0)
            + v.get("rejections", 0) + v.get("ghosted", 0) for v in variants
        )

        return {
            "variants": variants,
            "best_by_sector": best_by_sector,
            "total_applications": total_apps,
            "total_outcomes_recorded": total_outcomes,
        }

    def get_best_pairings_by_sector(self) -> Dict[str, dict]:
        """
        Get recommended resume+CL combo for each sector.

        Returns: {
            "biotech": {"resume_id": "...", "cl_id": "...", "combined_score": float},
            ...
        }
        """
        result = {}
        sectors = set()
        for v in self.data.get("resume_variants", []):
            if v.get("is_active", True):
                sectors.add(v.get("sector", "general"))
        for v in self.data.get("cover_letter_variants", []):
            if v.get("is_active", True):
                sectors.add(v.get("sector", "general"))

        for sector in sectors:
            resumes = self.list_resume_variants(active_only=True, sector=sector)
            cls = self.list_cover_letter_variants(active_only=True, sector=sector)

            best_resume = max(resumes, key=lambda v: v.get("score", 0)) if resumes else None
            best_cl = max(cls, key=lambda v: v.get("score", 0)) if cls else None

            result[sector] = {
                "resume_id": best_resume["id"] if best_resume else "",
                "resume_name": best_resume["name"] if best_resume else "N/A",
                "resume_score": best_resume.get("score", 0) if best_resume else 0,
                "cl_id": best_cl["id"] if best_cl else "",
                "cl_name": best_cl["name"] if best_cl else "N/A",
                "cl_score": best_cl.get("score", 0) if best_cl else 0,
                "combined_score": (
                    (best_resume.get("score", 0) if best_resume else 0) +
                    (best_cl.get("score", 0) if best_cl else 0)
                ),
                "total_apps": (
                    (best_resume.get("applications_used", 0) if best_resume else 0) +
                    (best_cl.get("applications_used", 0) if best_cl else 0)
                ),
            }

        return result

    # ── AI Variant Suggestions ──

    def generate_resume_suggestions(self, base_profile: dict, sectors: List[str] = None) -> List[dict]:
        """
        Generate structured suggestions for sector-optimized resume variants.

        This does NOT auto-generate files — it produces a list of recommended
        changes/emphasis areas for the user to apply to their base resume.

        Args:
            base_profile: Parsed resume profile from resume_parser.py
            sectors: Target sectors (default: biotech, tech, general)

        Returns list of suggestion dicts:
        [
            {
                "sector": "biotech",
                "suggested_name": "Biotech-Focused Resume",
                "emphasis_skills": ["FDA regulatory", "clinical trials", ...],
                "deemphasize": ["web development", ...],
                "title_suggestion": "Senior Product Manager | Biotech & Life Sciences",
                "summary_angle": "Emphasize pharma experience, regulatory knowledge, cross-functional clinical teams",
                "proof_points": ["Led clinical data platform at...", ...],
                "keywords_to_add": ["GxP", "IND", "NDA", "Phase I-IV", ...],
            },
            ...
        ]
        """
        if sectors is None:
            sectors = ["biotech", "tech", "general"]

        skills = base_profile.get("skills", {})
        experience = base_profile.get("experience", [])
        all_skills = []
        for cat_skills in skills.values():
            all_skills.extend(cat_skills)

        suggestions = []

        for sector in sectors:
            suggestion = {
                "sector": sector,
                "suggested_name": f"{sector.title()}-Focused Resume",
                "emphasis_skills": [],
                "deemphasize": [],
                "title_suggestion": "",
                "summary_angle": "",
                "proof_points": [],
                "keywords_to_add": [],
            }

            if sector == "biotech":
                suggestion["emphasis_skills"] = [s for s in all_skills if any(
                    kw in s.lower() for kw in ["bio", "pharma", "clinical", "fda", "regulatory", "gmp", "quality"]
                )]
                suggestion["deemphasize"] = [s for s in all_skills if any(
                    kw in s.lower() for kw in ["javascript", "react", "web", "css", "frontend"]
                )]
                suggestion["title_suggestion"] = "Senior Product Manager | Biotech & Life Sciences"
                suggestion["summary_angle"] = (
                    "Lead with pharma/biotech domain expertise. Emphasize regulated environments, "
                    "cross-functional clinical teams, data governance, and FDA compliance."
                )
                suggestion["keywords_to_add"] = [
                    "GxP", "CAPA", "clinical trials", "regulatory affairs", "pharmacovigilance",
                    "LIMS", "ELN", "21 CFR Part 11", "ICH guidelines", "biostatistics"
                ]

            elif sector == "tech":
                suggestion["emphasis_skills"] = [s for s in all_skills if any(
                    kw in s.lower() for kw in ["ai", "ml", "data", "analytics", "saas", "platform", "agile", "api"]
                )]
                suggestion["deemphasize"] = [s for s in all_skills if any(
                    kw in s.lower() for kw in ["gmp", "fda", "regulatory", "clinical"]
                )]
                suggestion["title_suggestion"] = "Senior Product Manager | AI/ML & Data Products"
                suggestion["summary_angle"] = (
                    "Lead with technical product management. Emphasize AI/ML platforms, "
                    "data-driven decision making, agile delivery, and cross-functional engineering teams."
                )
                suggestion["keywords_to_add"] = [
                    "product-led growth", "OKRs", "A/B testing", "user research",
                    "API design", "microservices", "CI/CD", "sprint planning"
                ]

            elif sector == "defense":
                suggestion["emphasis_skills"] = [s for s in all_skills if any(
                    kw in s.lower() for kw in ["program", "project", "risk", "compliance", "security", "systems"]
                )]
                suggestion["title_suggestion"] = "Program Manager | Defense & Aerospace"
                suggestion["summary_angle"] = (
                    "Lead with program management and systems thinking. Emphasize "
                    "risk management, compliance frameworks, and cross-organizational coordination."
                )
                suggestion["keywords_to_add"] = [
                    "ITAR", "EAR", "DoD", "CMMC", "earned value management",
                    "systems engineering", "milestone reviews", "security clearance"
                ]

            elif sector == "education":
                suggestion["emphasis_skills"] = [s for s in all_skills if any(
                    kw in s.lower() for kw in ["teaching", "mentor", "curriculum", "research", "publish"]
                )]
                suggestion["title_suggestion"] = "Adjunct Faculty | Business & Technology"
                suggestion["summary_angle"] = (
                    "Lead with industry experience translatable to academia. Emphasize "
                    "real-world case studies, mentorship, and bridging theory to practice."
                )
                suggestion["keywords_to_add"] = [
                    "curriculum development", "student outcomes", "pedagogy",
                    "experiential learning", "capstone projects"
                ]

            else:  # general
                suggestion["emphasis_skills"] = all_skills[:10]
                suggestion["title_suggestion"] = "Senior Product Manager"
                suggestion["summary_angle"] = (
                    "Balanced resume emphasizing breadth of experience across sectors. "
                    "Highlight adaptability, leadership, and cross-domain impact."
                )
                suggestion["keywords_to_add"] = [
                    "cross-functional leadership", "stakeholder management",
                    "strategic planning", "data-driven", "revenue growth"
                ]

            # Extract relevant proof points from experience
            for exp in experience[:5]:
                exp_text = str(exp).lower()
                sector_kws = SECTOR_KEYWORDS.get(sector, [])
                if any(kw in exp_text for kw in sector_kws[:10]):
                    suggestion["proof_points"].append(str(exp)[:200])

            suggestions.append(suggestion)

        return suggestions

    # ── Export for Dashboard ──

    def export_for_dashboard(self) -> dict:
        """Export all material data for dashboard import."""
        # Recalculate all scores before export
        for v in self.data.get("resume_variants", []):
            recalculate_rates_dict(v)
        for v in self.data.get("cover_letter_variants", []):
            recalculate_rates_dict(v)

        return {
            "resume_variants": self.data.get("resume_variants", []),
            "cover_letter_variants": self.data.get("cover_letter_variants", []),
            "material_pairings": self.data.get("material_pairings", []),
            "best_pairings_by_sector": self.get_best_pairings_by_sector(),
            "resume_comparison": self.get_variant_comparison("resume"),
            "cl_comparison": self.get_variant_comparison("cover_letter"),
            "config": self.data.get("config", {}),
        }

    # ── Summary / CLI Display ──

    def print_summary(self):
        """Print a CLI-friendly summary of all variants and performance."""
        print("\n" + "=" * 60)
        print("  MATERIAL VARIANTS — A/B Testing Summary")
        print("=" * 60)

        # Resume variants
        resumes = self.list_resume_variants(active_only=False)
        print(f"\n📄 Resume Variants ({len(resumes)} total):")
        print(f"  {'Name':<25} {'Sector':<10} {'Apps':>5} {'CB%':>6} {'IV%':>6} {'Score':>7} {'Status':<15}")
        print("  " + "-" * 78)
        for v in sorted(resumes, key=lambda x: x.get("score", 0), reverse=True):
            apps = v.get("applications_used", 0)
            status = "needs_data" if apps < 3 else ("performing" if v.get("score", 0) > 1.5 else "neutral")
            active = "" if v.get("is_active", True) else " [INACTIVE]"
            print(f"  {v['name']:<25} {v['sector']:<10} {apps:>5} {v.get('callback_rate',0)*100:>5.1f}% {v.get('interview_rate',0)*100:>5.1f}% {v.get('score',0):>7.2f} {status:<15}{active}")

        # CL variants
        cls = self.list_cover_letter_variants(active_only=False)
        print(f"\n✉️  Cover Letter Variants ({len(cls)} total):")
        print(f"  {'Name':<25} {'Tone':<10} {'Sector':<10} {'Apps':>5} {'Score':>7}")
        print("  " + "-" * 60)
        for v in sorted(cls, key=lambda x: x.get("score", 0), reverse=True):
            print(f"  {v['name']:<25} {v['tone']:<10} {v['sector']:<10} {v.get('applications_used',0):>5} {v.get('score',0):>7.2f}")

        # Best pairings
        pairings = self.get_best_pairings_by_sector()
        if pairings:
            print(f"\n🏆 Best Pairings by Sector:")
            for sector, p in sorted(pairings.items()):
                print(f"  {sector:<12} → Resume: {p['resume_name']:<20} CL: {p['cl_name']:<20} Combined: {p['combined_score']:.2f}")

        # Recent outcomes
        recent_pairings = sorted(
            [p for p in self.data.get("material_pairings", []) if p.get("outcome")],
            key=lambda p: p.get("outcome_recorded_at", ""),
            reverse=True
        )[:10]
        if recent_pairings:
            print(f"\n📊 Recent Outcomes ({len(recent_pairings)} shown):")
            for p in recent_pairings:
                emoji = {"callback": "📞", "interview": "🎯", "offer": "🎉", "rejected": "❌", "ghosted": "👻"}.get(p["outcome"], "?")
                print(f"  {emoji} {p.get('job_title','?'):<30} {p['outcome']:<12} {p.get('resume_variant_id','?')}")

        print()


# ============================================================
# HELPER: Recalculate rates on a plain dict (not dataclass)
# ============================================================

def recalculate_rates_dict(variant_dict: dict):
    """Recalculate rate fields and score on a variant dict."""
    apps = max(variant_dict.get("applications_used", 0), 1)
    variant_dict["callback_rate"] = round(variant_dict.get("callbacks", 0) / apps, 4)
    variant_dict["interview_rate"] = round(variant_dict.get("interviews", 0) / apps, 4)
    variant_dict["offer_rate"] = round(variant_dict.get("offers", 0) / apps, 4)

    # Composite score
    raw = (
        variant_dict.get("callbacks", 0) * OUTCOME_WEIGHTS["callback"]
        + variant_dict.get("interviews", 0) * OUTCOME_WEIGHTS["interview"]
        + variant_dict.get("offers", 0) * OUTCOME_WEIGHTS["offer"]
        + variant_dict.get("rejections", 0) * OUTCOME_WEIGHTS["rejected"]
        + variant_dict.get("ghosted", 0) * OUTCOME_WEIGHTS["ghosted"]
    ) / apps

    confidence = min(1.0, variant_dict.get("applications_used", 0) / MIN_APPS_FOR_FULL_CONFIDENCE)
    variant_dict["score"] = round(raw * confidence, 3)


# ============================================================
# CLI ENTRY POINT (for standalone testing)
# ============================================================

if __name__ == "__main__":
    import sys

    mgr = MaterialManager()

    if len(sys.argv) < 2:
        mgr.print_summary()
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "summary":
        mgr.print_summary()

    elif cmd == "create-resume":
        if len(sys.argv) < 5:
            print("Usage: python material_manager.py create-resume FILE SECTOR NAME")
            sys.exit(1)
        file_path, sector, name = sys.argv[2], sys.argv[3], " ".join(sys.argv[4:])
        vid = mgr.create_resume_variant(name, file_path, sector)
        print(f"Created resume variant: {vid}")

    elif cmd == "create-cl":
        if len(sys.argv) < 5:
            print("Usage: python material_manager.py create-cl TONE SECTOR NAME")
            sys.exit(1)
        tone, sector, name = sys.argv[2], sys.argv[3], " ".join(sys.argv[4:])
        vid = mgr.create_cover_letter_variant(name, tone, sector)
        print(f"Created CL variant: {vid}")

    elif cmd == "select":
        if len(sys.argv) < 3:
            print("Usage: python material_manager.py select SECTOR")
            sys.exit(1)
        sector = sys.argv[2]
        r_id, cl_id, reason = mgr.select_best_materials({"sector": sector})
        print(f"Selected for {sector}: resume={r_id}, cl={cl_id}, reason={reason}")

    elif cmd == "record-outcome":
        if len(sys.argv) < 4:
            print("Usage: python material_manager.py record-outcome PAIRING_ID OUTCOME")
            sys.exit(1)
        pid, outcome = sys.argv[2], sys.argv[3]
        success = mgr.record_pairing_outcome(pid, outcome)
        print(f"Outcome recorded: {success}")

    elif cmd == "export":
        data = mgr.export_for_dashboard()
        out_file = SCRIPT_DIR / "material_export.json"
        with open(out_file, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Exported to {out_file}")

    elif cmd == "suggestions":
        # Load resume profile if available
        profile_file = SCRIPT_DIR / "resume_profile.json"
        if profile_file.exists():
            with open(profile_file) as f:
                profile = json.load(f)
            suggestions = mgr.generate_resume_suggestions(profile)
            for s in suggestions:
                print(f"\n{'='*50}")
                print(f"Sector: {s['sector'].upper()}")
                print(f"Suggested name: {s['suggested_name']}")
                print(f"Title: {s['title_suggestion']}")
                print(f"Angle: {s['summary_angle']}")
                print(f"Emphasize: {', '.join(s['emphasis_skills'][:5])}")
                print(f"Keywords to add: {', '.join(s['keywords_to_add'][:5])}")
        else:
            print("No resume_profile.json found. Run: python main.py resume --file your_resume.pdf")

    else:
        print(f"Unknown command: {cmd}")
        print("Commands: summary, create-resume, create-cl, select, record-outcome, export, suggestions")
