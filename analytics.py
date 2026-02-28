#!/usr/bin/env python3
"""
Analytics Engine — Track application success metrics, conversion rates,
board performance, and generate insights for the dashboard.
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent


class AnalyticsEngine:
    """Tracks and analyzes job search campaign metrics."""

    def __init__(self, config_dir=None):
        self.config_dir = Path(config_dir) if config_dir else SCRIPT_DIR
        self.data_file = self.config_dir / "analytics_data.json"
        self.data = self._load()

    def _load(self):
        if self.data_file.exists():
            try:
                with open(self.data_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {
            "daily_stats": {},
            "board_stats": {},
            "ats_stats": {},
            "outcome_tracking": [],
            "funnel": {"discovered": 0, "queued": 0, "applied": 0, "screening": 0,
                       "interview": 0, "offer": 0, "rejected": 0},
        }

    def save(self):
        with open(self.data_file, 'w') as f:
            json.dump(self.data, f, indent=2)

    def record_discovery(self, board, count):
        """Record jobs discovered from a board."""
        today = datetime.now().strftime("%Y-%m-%d")
        self.data.setdefault("daily_stats", {}).setdefault(today, {
            "discovered": 0, "queued": 0, "applied": 0, "errors": 0
        })
        self.data["daily_stats"][today]["discovered"] += count
        self.data.setdefault("board_stats", {}).setdefault(board, {
            "total_discovered": 0, "total_applied": 0, "interviews": 0, "offers": 0
        })
        self.data["board_stats"][board]["total_discovered"] += count
        self.data["funnel"]["discovered"] += count
        self.save()

    def record_application(self, board, ats_type, success=True):
        """Record an application submission."""
        today = datetime.now().strftime("%Y-%m-%d")
        self.data.setdefault("daily_stats", {}).setdefault(today, {
            "discovered": 0, "queued": 0, "applied": 0, "errors": 0
        })
        if success:
            self.data["daily_stats"][today]["applied"] += 1
            self.data["funnel"]["applied"] += 1
            if board:
                self.data.setdefault("board_stats", {}).setdefault(board, {
                    "total_discovered": 0, "total_applied": 0, "interviews": 0, "offers": 0
                })
                self.data["board_stats"][board]["total_applied"] += 1
            if ats_type:
                self.data.setdefault("ats_stats", {}).setdefault(ats_type, {
                    "attempts": 0, "successes": 0, "failures": 0
                })
                self.data["ats_stats"][ats_type]["attempts"] += 1
                self.data["ats_stats"][ats_type]["successes"] += 1
        else:
            self.data["daily_stats"][today]["errors"] += 1
            if ats_type:
                self.data.setdefault("ats_stats", {}).setdefault(ats_type, {
                    "attempts": 0, "successes": 0, "failures": 0
                })
                self.data["ats_stats"][ats_type]["attempts"] += 1
                self.data["ats_stats"][ats_type]["failures"] += 1
        self.save()

    def record_outcome(self, job_id, company, outcome, material_pairing_id=None):
        """Record application outcome (screening, interview, offer, rejected).

        Args:
            job_id: Job identifier
            company: Company name
            outcome: callback|interview|offer|rejected|ghosted
            material_pairing_id: v4.1 A/B — pairing ID for variant tracking (optional)
        """
        entry = {
            "job_id": job_id,
            "company": company,
            "outcome": outcome,
            "date": datetime.now().isoformat(),
            "material_pairing_id": material_pairing_id or "",
        }
        self.data["outcome_tracking"].append(entry)
        if outcome in self.data["funnel"]:
            self.data["funnel"][outcome] += 1

        # v4.1: Update material variant scores if pairing exists
        if material_pairing_id:
            try:
                from material_manager import MaterialManager
                mat_mgr = MaterialManager(self.config_dir)
                mat_mgr.record_pairing_outcome(material_pairing_id, outcome)
            except ImportError:
                pass  # material_manager not available

        self.save()

    def export_material_performance(self):
        """Export material variant performance data for dashboard."""
        try:
            from material_manager import MaterialManager
            mat_mgr = MaterialManager(self.config_dir)
            return mat_mgr.export_for_dashboard()
        except ImportError:
            return {}

    def get_dashboard_stats(self):
        """Get stats formatted for dashboard display."""
        today = datetime.now().strftime("%Y-%m-%d")
        today_stats = self.data.get("daily_stats", {}).get(today, {})

        # 7-day trend
        week_applied = 0
        for i in range(7):
            d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            week_applied += self.data.get("daily_stats", {}).get(d, {}).get("applied", 0)

        # Conversion rates
        funnel = self.data.get("funnel", {})
        applied = max(funnel.get("applied", 1), 1)

        return {
            "today": today_stats,
            "week_applied": week_applied,
            "funnel": funnel,
            "conversion_rates": {
                "applied_to_screening": round(funnel.get("screening", 0) / applied * 100, 1),
                "screening_to_interview": round(
                    funnel.get("interview", 0) / max(funnel.get("screening", 1), 1) * 100, 1),
                "interview_to_offer": round(
                    funnel.get("offer", 0) / max(funnel.get("interview", 1), 1) * 100, 1),
            },
            "top_boards": sorted(
                self.data.get("board_stats", {}).items(),
                key=lambda x: x[1].get("interviews", 0), reverse=True
            )[:5],
            "ats_success_rates": {
                ats: round(stats["successes"] / max(stats["attempts"], 1) * 100, 1)
                for ats, stats in self.data.get("ats_stats", {}).items()
            },
        }

    def get_daily_trend(self, days=28):
        """Get daily application counts for sparkline chart."""
        trend = []
        for i in range(days - 1, -1, -1):
            d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            stats = self.data.get("daily_stats", {}).get(d, {})
            trend.append({
                "date": d,
                "discovered": stats.get("discovered", 0),
                "applied": stats.get("applied", 0),
            })
        return trend

    def export_for_dashboard(self):
        """Export analytics data in format for dashboard import."""
        return {
            "analytics": self.get_dashboard_stats(),
            "daily_trend": self.get_daily_trend(),
            "board_stats": self.data.get("board_stats", {}),
            "ats_stats": self.data.get("ats_stats", {}),
            "funnel": self.data.get("funnel", {}),
        }
