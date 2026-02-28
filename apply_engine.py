#!/usr/bin/env python3
"""
Auto-Apply Engine — Orchestrates the application process across three modes:
1. Semi-auto: Fill forms, user reviews and submits
2. Batch prep: Pre-fill all, user batch-reviews
3. Full-auto: Fill and submit with configurable pause

Handles Easy Apply (LinkedIn/Indeed), ATS form filling, and custom applications.
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional, List

try:
    from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

from form_filler import FormFiller
from rate_limiter import get_limiter
from qa_bank import QABank

SCRIPT_DIR = Path(__file__).parent

# =====================================================================
# APPLICATION STATUS MODEL
# =====================================================================

@dataclass
class ApplicationRecord:
    """Tracks a single job application through the pipeline."""
    id: str = ""
    job_id: str = ""
    job_title: str = ""
    company: str = ""
    url: str = ""
    score: int = 0
    apply_type: str = ""  # full-prep, quick-apply
    ats_type: str = ""
    easy_apply: bool = False
    status: str = "queued"  # queued | filling | ready-for-review | submitted | confirmed | error
    materials_ready: bool = False
    fields_filled: list = field(default_factory=list)
    fields_skipped: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    screenshot_path: str = ""
    submitted_at: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    action_log: list = field(default_factory=list)
    # v4.1: Material A/B tracking
    resume_variant_id: str = ""
    cover_letter_variant_id: str = ""
    material_pairing_id: str = ""
    outcome: str = ""               # callback|interview|offer|rejected|ghosted
    outcome_recorded_at: str = ""

    def to_dict(self):
        return asdict(self)

    def log_action(self, action, details=""):
        self.action_log.append({
            "time": datetime.now().isoformat(),
            "action": action,
            "details": details
        })


# =====================================================================
# QUEUE MANAGER
# =====================================================================

class ApplicationQueue:
    """Manages the queue of applications to process."""

    def __init__(self, config_dir=None):
        self.config_dir = Path(config_dir) if config_dir else SCRIPT_DIR
        self.queue_file = self.config_dir / "application_queue.json"
        self.queue: List[ApplicationRecord] = self._load()

    def _load(self):
        """Load queue from file."""
        if self.queue_file.exists():
            try:
                with open(self.queue_file) as f:
                    data = json.load(f)
                return [ApplicationRecord(**item) for item in data]
            except (json.JSONDecodeError, IOError, TypeError):
                pass
        return []

    def save(self):
        """Save queue to file."""
        with open(self.queue_file, 'w') as f:
            json.dump([a.to_dict() for a in self.queue], f, indent=2)

    def add_jobs(self, jobs):
        """Add scored jobs to the application queue.

        Args:
            jobs: List of job dicts with 'match', 'apply_type', etc.
        """
        existing_ids = {a.job_id for a in self.queue}
        added = 0

        for job in jobs:
            job_id = job.get("raw_id") or job.get("id", "")
            if job_id in existing_ids:
                continue
            if job.get("apply_type") == "skip":
                continue

            record = ApplicationRecord(
                id=f"app_{datetime.now().strftime('%Y%m%d%H%M%S')}_{added}",
                job_id=job_id,
                job_title=job.get("title", ""),
                company=job.get("company", ""),
                url=job.get("url", ""),
                score=job.get("match", 0),
                apply_type=job.get("apply_type", "quick-apply"),
                ats_type=job.get("ats_platform", ""),
                easy_apply=job.get("easy_apply", False),
            )
            record.log_action("queued", f"Score: {record.score}, Type: {record.apply_type}")
            self.queue.append(record)
            existing_ids.add(job_id)
            added += 1

        self.save()
        print(f"Queue: Added {added} jobs ({len(self.queue)} total in queue)")
        return added

    def get_pending(self, limit=None):
        """Get pending applications sorted by score."""
        pending = [a for a in self.queue if a.status == "queued"]
        pending.sort(key=lambda a: a.score, reverse=True)
        if limit:
            return pending[:limit]
        return pending

    def get_by_status(self, status):
        """Get applications by status."""
        return [a for a in self.queue if a.status == status]

    def update_status(self, app_id, status, **kwargs):
        """Update an application's status."""
        for app in self.queue:
            if app.id == app_id:
                app.status = status
                app.log_action(f"status_change:{status}", str(kwargs))
                for k, v in kwargs.items():
                    if hasattr(app, k):
                        setattr(app, k, v)
                self.save()
                return True
        return False

    def get_stats(self):
        """Get queue statistics."""
        stats = {
            "total": len(self.queue),
            "queued": len([a for a in self.queue if a.status == "queued"]),
            "filling": len([a for a in self.queue if a.status == "filling"]),
            "ready_for_review": len([a for a in self.queue if a.status == "ready-for-review"]),
            "submitted": len([a for a in self.queue if a.status == "submitted"]),
            "confirmed": len([a for a in self.queue if a.status == "confirmed"]),
            "errors": len([a for a in self.queue if a.status == "error"]),
        }
        stats["today_submitted"] = len([
            a for a in self.queue
            if a.status in ("submitted", "confirmed") and
            a.submitted_at and a.submitted_at[:10] == datetime.now().strftime("%Y-%m-%d")
        ])
        return stats


# =====================================================================
# APPLY ENGINE
# =====================================================================

class ApplyEngine:
    """Orchestrates the application process."""

    def __init__(self, config_manager=None, config_dir=None):
        self.config_dir = Path(config_dir) if config_dir else SCRIPT_DIR
        self.config = config_manager
        self.queue = ApplicationQueue(self.config_dir)
        self.filler = FormFiller(self.config_dir)
        self.limiter = get_limiter()
        self.mode = "semi-auto"
        if config_manager:
            self.mode = config_manager.get("automation", {}).get("mode", "semi-auto")

    async def process_queue(self, limit=None, dry_run=False):
        """Process pending applications from the queue.

        Args:
            limit: Max number of applications to process
            dry_run: Fill forms but don't submit

        Returns:
            Dict with processing results
        """
        if not HAS_PLAYWRIGHT:
            print("ERROR: Playwright not installed")
            return {"error": "Playwright not installed"}

        pending = self.queue.get_pending(limit)
        if not pending:
            print("No pending applications in queue")
            return {"processed": 0}

        results = {
            "processed": 0,
            "filled": 0,
            "submitted": 0,
            "errors": 0,
            "details": [],
        }

        print(f"\n{'='*60}")
        print(f"AUTO-APPLY ENGINE — Mode: {self.mode.upper()}")
        print(f"Processing {len(pending)} applications {'(DRY RUN)' if dry_run else ''}")
        print(f"{'='*60}\n")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=False if self.mode != "full-auto" else True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=self.limiter.get_random_user_agent(),
            )

            for app_record in pending:
                print(f"\n--- Applying: {app_record.job_title} at {app_record.company} ---")
                print(f"    Score: {app_record.score} | Type: {app_record.apply_type} | ATS: {app_record.ats_type or 'unknown'}")

                self.queue.update_status(app_record.id, "filling")
                app_result = {"job": app_record.job_title, "company": app_record.company}

                try:
                    page = await context.new_page()

                    # Navigate to job page
                    self.limiter.wait(self._get_board_name(app_record.url))
                    await page.goto(app_record.url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(2)

                    # Check for Easy Apply button
                    if app_record.easy_apply:
                        easy_result = await self._try_easy_apply(page, app_record)
                        if easy_result.get("success"):
                            app_result["method"] = "easy_apply"
                            app_result["filled"] = True
                            results["filled"] += 1
                            if not dry_run and self.mode == "full-auto":
                                results["submitted"] += 1
                            continue

                    # Find and click "Apply" button
                    apply_clicked = await self._click_apply_button(page)
                    if not apply_clicked:
                        # Might already be on the application form
                        pass

                    await asyncio.sleep(2)

                    # Fill the application form
                    job_context = {
                        "title": app_record.job_title,
                        "company": app_record.company,
                        "url": app_record.url,
                    }

                    # v4.1: Select best resume + CL variants via A/B engine
                    resume_vid, cl_vid = "", ""
                    try:
                        from material_manager import MaterialManager, detect_sector
                        mat_mgr = MaterialManager(self.config_dir)
                        job_context["sector"] = detect_sector(app_record.job_title, app_record.company)
                        resume_vid, cl_vid, selection_reason = mat_mgr.select_best_materials(job_context)
                        if resume_vid:
                            app_record.resume_variant_id = resume_vid
                            app_record.cover_letter_variant_id = cl_vid
                            pairing_id = mat_mgr.create_material_pairing(
                                app_record.id, app_record.job_id,
                                resume_vid, cl_vid,
                                job_title=app_record.job_title,
                                company=app_record.company,
                                sector=job_context.get("sector", ""),
                                reason=selection_reason,
                            )
                            app_record.material_pairing_id = pairing_id
                            app_record.log_action("material_selected",
                                f"Resume: {resume_vid}, CL: {cl_vid} ({selection_reason})")
                    except ImportError:
                        pass  # material_manager not available — skip A/B

                    fill_result = await self.filler.fill_application(
                        page, job_context, dry_run=dry_run,
                        resume_variant_id=resume_vid, cover_letter_variant_id=cl_vid,
                    )

                    # Update application record
                    app_record.fields_filled = fill_result["fields_filled"]
                    app_record.fields_skipped = fill_result["fields_skipped"]
                    app_record.errors = fill_result["errors"]
                    app_record.screenshot_path = fill_result.get("screenshot_path", "")
                    app_record.ats_type = fill_result.get("ats_detected", app_record.ats_type)
                    app_record.materials_ready = len(fill_result["fields_filled"]) > 0

                    results["filled"] += 1
                    app_result["fields_filled"] = len(fill_result["fields_filled"])
                    app_result["fields_skipped"] = len(fill_result["fields_skipped"])
                    app_result["errors"] = len(fill_result["errors"])

                    # Handle submission based on mode
                    if dry_run:
                        self.queue.update_status(app_record.id, "ready-for-review",
                                                 fields_filled=fill_result["fields_filled"],
                                                 screenshot_path=fill_result.get("screenshot_path", ""))
                        app_result["status"] = "ready-for-review"
                        print(f"    [DRY RUN] Filled {len(fill_result['fields_filled'])} fields, skipped {len(fill_result['fields_skipped'])}")

                    elif self.mode == "full-auto":
                        # Submit after configurable pause
                        pause = self.config.get("automation", {}).get("pause_before_submit", True) if self.config else True
                        if pause:
                            print(f"    Pausing 5 seconds before submit...")
                            await asyncio.sleep(5)

                        submitted = await self._click_submit(page, fill_result.get("ats_detected"))
                        if submitted:
                            self.queue.update_status(app_record.id, "submitted",
                                                     submitted_at=datetime.now().isoformat())
                            results["submitted"] += 1
                            app_result["status"] = "submitted"
                            print(f"    SUBMITTED")
                        else:
                            self.queue.update_status(app_record.id, "ready-for-review")
                            app_result["status"] = "submit-failed"

                    elif self.mode == "batch":
                        self.queue.update_status(app_record.id, "ready-for-review",
                                                 materials_ready=True)
                        app_result["status"] = "ready-for-review"
                        print(f"    [BATCH] Form filled, awaiting batch review")

                    else:  # semi-auto
                        self.queue.update_status(app_record.id, "ready-for-review",
                                                 materials_ready=True)
                        app_result["status"] = "ready-for-review"
                        print(f"    [SEMI-AUTO] Form filled, awaiting user review")

                    await page.close()

                except PlaywrightTimeout:
                    self.queue.update_status(app_record.id, "error",
                                             errors=[{"error": "Page timeout"}])
                    results["errors"] += 1
                    app_result["status"] = "timeout"
                    print(f"    ERROR: Page timed out")

                except Exception as e:
                    self.queue.update_status(app_record.id, "error",
                                             errors=[{"error": str(e)[:200]}])
                    results["errors"] += 1
                    app_result["status"] = "error"
                    print(f"    ERROR: {str(e)[:100]}")

                results["processed"] += 1
                results["details"].append(app_result)

            await browser.close()

        # Save results
        results_file = self.config_dir / "apply_results.json"
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2)

        print(f"\n{'='*60}")
        print(f"APPLY ENGINE COMPLETE")
        print(f"Processed: {results['processed']} | Filled: {results['filled']} | Submitted: {results['submitted']} | Errors: {results['errors']}")
        print(f"{'='*60}\n")

        return results

    async def _try_easy_apply(self, page, app_record):
        """Try to use Easy Apply if available."""
        easy_selectors = [
            "button[aria-label*='Easy Apply']",  # LinkedIn
            ".jobs-apply-button",                  # LinkedIn
            "button[id*='indeedApplyButton']",     # Indeed
            ".indeed-apply-button",                # Indeed
            "button[data-testid*='easy-apply']",   # Various
            "a.easy-apply",
        ]

        for selector in easy_selectors:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(2)
                    app_record.log_action("easy_apply_clicked")

                    # Fill the quick form
                    job_context = {"title": app_record.job_title, "company": app_record.company}
                    fill_result = await self.filler.fill_application(page, job_context)

                    return {"success": True, "fill_result": fill_result}
            except Exception:
                continue

        return {"success": False}

    async def _click_apply_button(self, page):
        """Find and click the main Apply button on a job page."""
        apply_selectors = [
            "a[href*='apply']",
            "button:has-text('Apply')",
            "a:has-text('Apply Now')",
            "a:has-text('Apply for this job')",
            "button:has-text('Apply Now')",
            "button:has-text('Submit Application')",
            ".apply-button",
            "#apply-button",
            "[data-testid='apply-button']",
        ]

        for selector in apply_selectors:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(2)
                    return True
            except Exception:
                continue

        return False

    async def _click_submit(self, page, ats_type=None):
        """Click the submit button on the application form."""
        # ATS-specific submit selectors
        if ats_type and ats_type in ("greenhouse", "lever", "smartrecruiters", "ashby"):
            try:
                btn = page.locator("button[type='submit']").first
                if await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(3)
                    return True
            except Exception:
                pass

        # Generic submit selectors
        submit_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('Submit')",
            "button:has-text('Submit Application')",
            "button:has-text('Apply')",
            "#submit-application",
        ]

        for selector in submit_selectors:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(3)
                    return True
            except Exception:
                continue

        return False

    def _get_board_name(self, url):
        """Infer board name from URL for rate limiting."""
        if not url:
            return "default"
        url_lower = url.lower()
        boards = {
            "indeed.com": "indeed",
            "linkedin.com": "linkedin",
            "glassdoor.com": "glassdoor",
            "greenhouse.io": "career_page",
            "lever.co": "career_page",
            "workday": "career_page",
        }
        for pattern, board in boards.items():
            if pattern in url_lower:
                return board
        return "career_page"

    def get_queue_stats(self):
        """Get current queue statistics."""
        return self.queue.get_stats()


async def run_apply(config_manager=None, mode="semi-auto", limit=None, dry_run=False):
    """Convenience function to run the apply engine."""
    engine = ApplyEngine(config_manager)
    engine.mode = mode
    return await engine.process_queue(limit=limit, dry_run=dry_run)
