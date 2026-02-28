#!/usr/bin/env python3
"""
Scheduler — Cron-like recurring job discovery and application processing.
Supports daily/twice-daily/custom schedules with configurable time windows.
"""

import asyncio
import json
import time
import signal
from pathlib import Path
from datetime import datetime, timedelta

SCRIPT_DIR = Path(__file__).parent

DEFAULT_SCHEDULE = {
    "discovery": {
        "enabled": True,
        "frequency": "twice_daily",  # once_daily | twice_daily | hourly | custom
        "times": ["08:00", "14:00"],
        "days": ["mon", "tue", "wed", "thu", "fri"],  # Weekdays only
        "max_boards_per_run": 10,
    },
    "apply": {
        "enabled": False,  # Disabled by default for safety
        "frequency": "once_daily",
        "times": ["09:00"],
        "days": ["mon", "tue", "wed", "thu", "fri"],
        "max_per_run": 10,
        "mode": "semi-auto",
    },
    "digest": {
        "enabled": True,
        "frequency": "once_daily",
        "times": ["18:00"],
        "days": ["mon", "tue", "wed", "thu", "fri"],
    }
}


class Scheduler:
    """Simple scheduler for recurring job search tasks."""

    def __init__(self, config_manager=None, config_dir=None):
        self.config_dir = Path(config_dir) if config_dir else SCRIPT_DIR
        self.config = config_manager
        self.schedule = self._load_schedule()
        self.running = False
        self.last_run = {}

    def _load_schedule(self):
        """Load schedule configuration."""
        schedule_file = self.config_dir / "schedule_config.json"
        if schedule_file.exists():
            try:
                with open(schedule_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return DEFAULT_SCHEDULE

    def save_schedule(self):
        """Save schedule configuration."""
        schedule_file = self.config_dir / "schedule_config.json"
        with open(schedule_file, 'w') as f:
            json.dump(self.schedule, f, indent=2)

    def should_run(self, task_name):
        """Check if a task should run now."""
        task = self.schedule.get(task_name, {})
        if not task.get("enabled", False):
            return False

        now = datetime.now()
        current_day = now.strftime("%a").lower()
        current_time = now.strftime("%H:%M")

        # Check day of week
        allowed_days = task.get("days", ["mon", "tue", "wed", "thu", "fri"])
        if current_day not in allowed_days:
            return False

        # Check time windows
        times = task.get("times", [])
        for t in times:
            # Allow a 5-minute window around scheduled time
            scheduled = datetime.strptime(t, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
            window_start = scheduled - timedelta(minutes=2)
            window_end = scheduled + timedelta(minutes=5)
            if window_start <= now <= window_end:
                # Check if already run in this window
                last = self.last_run.get(f"{task_name}_{t}")
                if last and (now - last).total_seconds() < 300:  # 5 min cooldown
                    return False
                return True

        return False

    async def run_once(self):
        """Check and run any due tasks once."""
        from config_manager import ConfigManager
        from job_discovery import run_discovery
        from dedup_engine import deduplicate_jobs
        from scoring_engine import score_jobs
        from apply_engine import ApplyEngine
        from analytics import AnalyticsEngine

        config = self.config or ConfigManager(self.config_dir)
        ran_anything = False

        # Discovery
        if self.should_run("discovery"):
            print(f"\n[SCHEDULER] Running discovery at {datetime.now().strftime('%H:%M')}")
            try:
                raw_jobs = await run_discovery(config)
                deduped = deduplicate_jobs([j.to_dict() for j in raw_jobs])
                scored = score_jobs(deduped, config)

                analytics = AnalyticsEngine(self.config_dir)
                for board in set(j.get("board_source", "") for j in raw_jobs):
                    count = len([j for j in raw_jobs if j.board_source == board])
                    analytics.record_discovery(board, count)

                # Add to application queue
                engine = ApplyEngine(config, self.config_dir)
                engine.queue.add_jobs(scored)

                self.last_run[f"discovery_{datetime.now().strftime('%H:%M')[:5]}"] = datetime.now()
                ran_anything = True
                print(f"[SCHEDULER] Discovery complete: {len(raw_jobs)} raw → {len(deduped)} deduped → {len(scored)} scored")
            except Exception as e:
                print(f"[SCHEDULER] Discovery failed: {e}")

        # Apply (if enabled)
        if self.should_run("apply"):
            print(f"\n[SCHEDULER] Running apply at {datetime.now().strftime('%H:%M')}")
            try:
                apply_config = self.schedule.get("apply", {})
                engine = ApplyEngine(config, self.config_dir)
                engine.mode = apply_config.get("mode", "semi-auto")
                results = await engine.process_queue(
                    limit=apply_config.get("max_per_run", 10),
                    dry_run=apply_config.get("mode") == "semi-auto"
                )
                self.last_run[f"apply_{datetime.now().strftime('%H:%M')[:5]}"] = datetime.now()
                ran_anything = True
                print(f"[SCHEDULER] Apply complete: {results.get('processed', 0)} processed")
            except Exception as e:
                print(f"[SCHEDULER] Apply failed: {e}")

        return ran_anything

    async def run_daemon(self, check_interval=60):
        """Run as a long-running daemon, checking schedule every minute."""
        self.running = True
        print(f"[SCHEDULER] Daemon started. Checking every {check_interval}s")
        print(f"[SCHEDULER] Schedule: {json.dumps(self.schedule, indent=2)}")

        # Handle graceful shutdown
        def handle_signal(signum, frame):
            print("\n[SCHEDULER] Shutdown signal received")
            self.running = False

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        while self.running:
            try:
                await self.run_once()
            except Exception as e:
                print(f"[SCHEDULER] Error in run loop: {e}")

            await asyncio.sleep(check_interval)

        print("[SCHEDULER] Daemon stopped")

    def get_next_run(self):
        """Get the next scheduled run time for each task."""
        next_runs = {}
        now = datetime.now()

        for task_name, task in self.schedule.items():
            if not task.get("enabled"):
                next_runs[task_name] = "disabled"
                continue

            times = task.get("times", [])
            days = task.get("days", ["mon", "tue", "wed", "thu", "fri"])

            # Find next matching day+time
            for day_offset in range(7):
                check_date = now + timedelta(days=day_offset)
                if check_date.strftime("%a").lower() not in days:
                    continue
                for t in sorted(times):
                    scheduled = datetime.strptime(t, "%H:%M").replace(
                        year=check_date.year, month=check_date.month, day=check_date.day
                    )
                    if scheduled > now:
                        next_runs[task_name] = scheduled.strftime("%Y-%m-%d %H:%M")
                        break
                if task_name in next_runs:
                    break

        return next_runs

    def get_status(self):
        """Get scheduler status for display."""
        return {
            "running": self.running,
            "schedule": self.schedule,
            "last_runs": {k: v.isoformat() for k, v in self.last_run.items()},
            "next_runs": self.get_next_run(),
        }
