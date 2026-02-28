#!/usr/bin/env python3
"""
Q&A Bank — Pre-built answers to 50+ common application questions.
Answers are templates with {placeholders} that get filled from resume profile,
job context, and user config.
"""

import json
import re
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent

# =====================================================================
# DEFAULT Q&A PAIRS (50+ common application questions)
# =====================================================================

DEFAULT_QA = [
    # Default Q&A entries are empty — users populate via:
    #   python main.py qa --add          (interactive)
    #   python main.py init              (setup wizard)
    #   Dashboard → Q&A Bank → + Add
]


# =====================================================================
# QA BANK MANAGER
# =====================================================================



class QABank:
    """Manages the Q&A bank for auto-filling application forms."""

    def __init__(self, config_dir=None):
        self.config_dir = Path(config_dir) if config_dir else SCRIPT_DIR
        self.qa_file = self.config_dir / "qa_bank.json"
        self.entries = self._load()

    def _load(self):
        """Load Q&A bank from file or defaults."""
        if self.qa_file.exists():
            try:
                with open(self.qa_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return list(DEFAULT_QA)

    def save(self):
        """Save Q&A bank to file."""
        with open(self.qa_file, 'w') as f:
            json.dump(self.entries, f, indent=2)

    def get_answer(self, question_text, job_context=None):
        """Find the best answer for a question.

        Args:
            question_text: The question text from the application form
            job_context: Optional dict with company, role, etc. for template filling

        Returns:
            Dict with 'answer' and 'confidence' (0-1), or None if no match
        """
        q_lower = question_text.lower().strip()
        q_lower = re.sub(r'[*:?\s]+$', '', q_lower)  # Strip trailing punctuation

        best_match = None
        best_score = 0

        for entry in self.entries:
            # Check exact question match
            if q_lower == entry["question"].lower():
                best_match = entry
                best_score = 1.0
                break

            # Check aliases
            for alias in entry.get("aliases", []):
                if alias.lower() in q_lower or q_lower in alias.lower():
                    score = len(alias) / max(len(q_lower), 1)
                    if score > best_score:
                        best_match = entry
                        best_score = min(score, 0.95)

            # Fuzzy keyword match
            entry_words = set(entry["question"].lower().split())
            q_words = set(q_lower.split())
            overlap = len(entry_words & q_words)
            if overlap >= 3:
                score = overlap / max(len(entry_words | q_words), 1)
                if score > best_score:
                    best_match = entry
                    best_score = score * 0.8  # Discount fuzzy matches

        if best_match and best_score >= 0.3:
            answer = best_match["answer"]
            # Fill templates with job context
            if job_context:
                answer = self._fill_template(answer, job_context)
            return {
                "answer": answer,
                "confidence": best_score,
                "field_type": best_match.get("field_type", "text"),
                "category": best_match.get("category", ""),
                "source_question": best_match["question"],
            }

        return None

    def _fill_template(self, answer, context):
        """Replace {placeholders} in answer with job context values."""
        replacements = {
            "{company}": context.get("company", "your company"),
            "{role}": context.get("title", "this role"),
            "{location}": context.get("location", ""),
            "{domain_fit}": self._infer_domain(context),
            "{linkedin_url}": context.get("linkedin_url", ""),
            "{website_url}": context.get("website_url", ""),
        }
        for key, val in replacements.items():
            answer = answer.replace(key, val)
        return answer

    def _infer_domain(self, context):
        """Infer the domain/sector for template filling."""
        text = f"{context.get('title', '')} {context.get('company', '')} {context.get('description', '')}".lower()
        if any(w in text for w in ["biotech", "pharma", "clinical"]):
            return "biotechnology"
        if any(w in text for w in ["ai", "ml", "machine learning"]):
            return "AI/ML"
        if any(w in text for w in ["defense", "aerospace"]):
            return "defense/aerospace"
        if any(w in text for w in ["saas", "software"]):
            return "SaaS"
        return "technology"

    def add_entry(self, question, answer, category="custom", field_type="text", aliases=None):
        """Add a new Q&A entry."""
        self.entries.append({
            "category": category,
            "question": question,
            "answer": answer,
            "field_type": field_type,
            "aliases": aliases or [],
        })
        self.save()

    def update_entry(self, question, new_answer):
        """Update an existing Q&A entry."""
        for entry in self.entries:
            if entry["question"].lower() == question.lower():
                entry["answer"] = new_answer
                self.save()
                return True
        return False

    def get_all(self, category=None):
        """Get all Q&A entries, optionally filtered by category."""
        if category:
            return [e for e in self.entries if e.get("category") == category]
        return self.entries

    def export_for_dashboard(self):
        """Export Q&A bank in format suitable for dashboard import."""
        return [{
            "question": e["question"],
            "answer": e["answer"],
            "category": e.get("category", ""),
            "lastUsed": e.get("last_used", ""),
        } for e in self.entries]
