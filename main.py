#!/usr/bin/env python3
"""
JobPilotAI v4.1 — Main Orchestrator

Usage:
  python main.py discover                        # Discover jobs across all boards
  python main.py discover --boards indeed,linkedin  # Specific boards only
  python main.py discover --limit 20             # Limit results per board

  python main.py apply                           # Process application queue (semi-auto)
  python main.py apply --mode full-auto          # Full auto mode
  python main.py apply --mode batch              # Batch prep mode
  python main.py apply --dry-run                 # Fill forms without submitting
  python main.py apply --limit 10                # Process N applications

  python main.py full-cycle                      # Discover → Score → Dedup → Queue → Apply
  python main.py full-cycle --dry-run            # Full cycle without submitting

  python main.py resume --file resume.pdf        # Parse resume file
  python main.py resume --show                   # Show parsed resume profile

  python main.py qa --list                       # List Q&A bank entries
  python main.py qa --add                        # Add Q&A entry interactively
  python main.py qa --export                     # Export Q&A bank as JSON

  python main.py status                          # Show pipeline status
  python main.py stats                           # Show analytics

  python main.py schedule                        # Run scheduler daemon
  python main.py schedule --show                 # Show schedule config

  python main.py materials --list-resume          # Show resume variants with scores
  python main.py materials --list-cl              # Show cover letter variants
  python main.py materials --create-resume FILE SECTOR NAME  # Register variant
  python main.py materials --performance          # A/B performance comparison
  python main.py materials --record-outcome ID OUTCOME  # Record result
  python main.py materials --suggestions          # AI-driven variant suggestions

  python main.py export                          # Export all data for dashboard import

  python main.py init                            # Run interactive setup wizard

  python main.py ai-cover-letter --job-id ID [--tone confident]  # AI cover letter
  python main.py ai-score --job-id ID              # AI-enhanced job scoring
  python main.py ai-interview --question "..." --job-id ID  # AI interview answer
  python main.py ai-research --company "Acme Corp" # AI company research
  python main.py ai-pitch --job-id ID              # AI elevator pitch
  python main.py ai-coach --job-id ID              # AI interview coaching guide
  python main.py ai-usage                          # Show AI usage stats
"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from config_manager import ConfigManager
from rate_limiter import get_limiter


def _auto_export(config):
    """Silently export engine data so the dashboard auto-syncs on refresh."""
    try:
        cmd_export([], config)
        print("  (Dashboard auto-sync file updated)")
    except Exception:
        pass  # Non-critical — don't break the main command


def cmd_discover(args, config):
    """Run job discovery."""
    from job_discovery import DiscoveryEngine
    from dedup_engine import deduplicate_jobs
    from scoring_engine import ScoringEngine
    from analytics import AnalyticsEngine

    boards = None
    if "--boards" in args:
        idx = args.index("--boards")
        if idx + 1 < len(args):
            boards = args[idx + 1].split(",")

    limit = 50
    if "--limit" in args:
        idx = args.index("--limit")
        if idx + 1 < len(args):
            limit = int(args[idx + 1])

    async def run():
        engine = DiscoveryEngine(config)
        raw_jobs = await engine.discover(boards=boards, max_per_board=limit)

        # Deduplicate
        job_dicts = [j.to_dict() for j in raw_jobs]
        deduped = deduplicate_jobs(job_dicts)

        # Score
        scorer = ScoringEngine(config)
        scored = scorer.batch_score(deduped)

        # Track analytics
        analytics = AnalyticsEngine(SCRIPT_DIR)
        board_counts = {}
        for j in raw_jobs:
            board_counts[j.board_source] = board_counts.get(j.board_source, 0) + 1
        for board, count in board_counts.items():
            analytics.record_discovery(board, count)

        # Save scored results
        output_file = SCRIPT_DIR / "discovered_jobs.json"
        with open(output_file, 'w') as f:
            json.dump(scored, f, indent=2)

        # Summary
        threshold = config.get_strategy_threshold()
        qualifying = [j for j in scored if j.get("match", 0) >= threshold["min_score"]]

        print(f"\n{'='*60}")
        print(f"DISCOVERY SUMMARY")
        print(f"{'='*60}")
        print(f"Raw jobs found:     {len(raw_jobs)}")
        print(f"After dedup:        {len(deduped)}")
        print(f"Qualifying (>={threshold['min_score']}%): {len(qualifying)}")
        print(f"\nTop 10 matches:")
        for j in scored[:10]:
            emoji = "🟢" if j["match"] >= 85 else "🟡" if j["match"] >= 60 else "⚪"
            print(f"  {emoji} {j['match']:3d}% | {j['title'][:40]:40s} | {j.get('company','')[:20]:20s} | {j.get('apply_type','')}")
        print(f"\nResults saved to: {output_file}")

        return scored

    result = asyncio.run(run())
    _auto_export(config)
    return result


def cmd_apply(args, config):
    """Process application queue."""
    from apply_engine import ApplyEngine

    mode = config.get("automation", {}).get("mode", "semi-auto")
    if "--mode" in args:
        idx = args.index("--mode")
        if idx + 1 < len(args):
            mode = args[idx + 1]

    dry_run = "--dry-run" in args

    limit = None
    if "--limit" in args:
        idx = args.index("--limit")
        if idx + 1 < len(args):
            limit = int(args[idx + 1])

    async def run():
        engine = ApplyEngine(config, SCRIPT_DIR)
        engine.mode = mode

        # If queue is empty, check for discovered jobs to queue
        if not engine.queue.get_pending():
            jobs_file = SCRIPT_DIR / "discovered_jobs.json"
            if jobs_file.exists():
                with open(jobs_file) as f:
                    jobs = json.load(f)
                engine.queue.add_jobs(jobs)

        return await engine.process_queue(limit=limit, dry_run=dry_run)

    result = asyncio.run(run())
    _auto_export(config)
    return result


def cmd_full_cycle(args, config):
    """Full cycle: discover → score → dedup → queue → apply."""
    print(f"\n{'='*60}")
    print(f"FULL CYCLE — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    # Step 1: Discover
    print("\n[1/4] DISCOVERING JOBS...")
    scored = cmd_discover(args, config)

    if not scored:
        print("No jobs found. Stopping.")
        return

    # Step 2: Queue
    print("\n[2/4] QUEUEING APPLICATIONS...")
    from apply_engine import ApplyEngine
    engine = ApplyEngine(config, SCRIPT_DIR)
    added = engine.queue.add_jobs(scored)
    print(f"Added {added} jobs to application queue")

    # Step 3: Apply
    dry_run = "--dry-run" in args
    mode = config.get("automation", {}).get("mode", "semi-auto")
    if "--mode" in args:
        idx = args.index("--mode")
        if idx + 1 < len(args):
            mode = args[idx + 1]

    limit = None
    if "--limit" in args:
        idx = args.index("--limit")
        if idx + 1 < len(args):
            limit = int(args[idx + 1])

    print(f"\n[3/4] APPLYING — Mode: {mode} {'(DRY RUN)' if dry_run else ''}...")

    async def run_apply():
        engine_apply = ApplyEngine(config, SCRIPT_DIR)
        engine_apply.mode = mode
        return await engine_apply.process_queue(limit=limit, dry_run=dry_run)

    results = asyncio.run(run_apply())

    # Step 4: Summary
    print(f"\n[4/4] CYCLE COMPLETE")
    print(f"{'='*60}")
    stats = engine.queue.get_stats()
    print(f"Queue: {stats['total']} total | {stats['queued']} pending | {stats['submitted']} submitted | {stats['errors']} errors")
    print(f"Today: {stats['today_submitted']} submitted")

    _auto_export(config)


def cmd_resume(args, config):
    """Parse a resume file."""
    from resume_parser import parse_resume, save_profile, load_profile

    if "--show" in args:
        profile = load_profile(SCRIPT_DIR)
        if profile:
            print(json.dumps(profile, indent=2))
        else:
            print("No resume profile found. Run: python main.py resume --file your_resume.pdf")
        return

    if "--file" in args:
        idx = args.index("--file")
        if idx + 1 < len(args):
            filepath = Path(args[idx + 1])
            if not filepath.exists():
                print(f"File not found: {filepath}")
                return

            print(f"Parsing resume: {filepath}")
            # Get user overrides from config
            user = config.get("user", {})
            overrides = {
                "contact": {
                    "name": user.get("name", ""),
                    "email": user.get("email", ""),
                    "phone": user.get("phone", ""),
                    "location": user.get("location", ""),
                }
            }
            profile = parse_resume(filepath, user_overrides=overrides)
            save_profile(profile, SCRIPT_DIR)

            # Print summary
            contact = profile.get("contact", {})
            skills = profile.get("skills", {})
            print(f"\n{'='*40}")
            print(f"Name:     {contact.get('name', 'N/A')}")
            print(f"Email:    {contact.get('email', 'N/A')}")
            print(f"Phone:    {contact.get('phone', 'N/A')}")
            print(f"Location: {contact.get('location', 'N/A')}")
            print(f"LinkedIn: {contact.get('linkedin', 'N/A')}")
            print(f"\nSkills found: {sum(len(v) for v in skills.values())} across {len(skills)} categories")
            for cat, items in skills.items():
                print(f"  {cat}: {', '.join(items[:5])}{' ...' if len(items) > 5 else ''}")
            print(f"\nEducation: {len(profile.get('education', []))} entries")
            print(f"Experience: {len(profile.get('experience', []))} entries")
            print(f"Certifications: {', '.join(profile.get('certifications', [])) or 'N/A'}")
    else:
        print("Usage: python main.py resume --file resume.pdf")
        print("       python main.py resume --show")


def cmd_qa(args, config):
    """Manage Q&A bank."""
    from qa_bank import QABank

    bank = QABank(SCRIPT_DIR)

    if "--list" in args:
        entries = bank.get_all()
        for i, e in enumerate(entries):
            print(f"[{i+1}] [{e.get('category','')}] {e['question']}")
            print(f"     → {e['answer'][:80]}{'...' if len(e['answer']) > 80 else ''}")
        print(f"\n{len(entries)} total Q&A entries")
        return

    if "--export" in args:
        data = bank.export_for_dashboard()
        out_file = SCRIPT_DIR / "qa_bank_export.json"
        with open(out_file, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Exported {len(data)} entries to {out_file}")
        return

    if "--add" in args:
        q = input("Question: ")
        a = input("Answer: ")
        cat = input("Category (personal/experience/behavioral/technical/custom): ") or "custom"
        bank.add_entry(q, a, category=cat)
        print("Added to Q&A bank.")
        return

    print("Usage: python main.py qa --list | --export | --add")


def cmd_status(args, config):
    """Show pipeline status."""
    from apply_engine import ApplicationQueue
    from analytics import AnalyticsEngine

    queue = ApplicationQueue(SCRIPT_DIR)
    analytics = AnalyticsEngine(SCRIPT_DIR)
    stats = queue.get_stats()
    dashboard = analytics.get_dashboard_stats()

    print(f"\n{'='*60}")
    print(f"JobPilotAI — STATUS")
    print(f"{'='*60}")
    print(f"\nApplication Queue:")
    print(f"  Queued:          {stats['queued']}")
    print(f"  Filling:         {stats['filling']}")
    print(f"  Ready to review: {stats['ready_for_review']}")
    print(f"  Submitted:       {stats['submitted']}")
    print(f"  Confirmed:       {stats['confirmed']}")
    print(f"  Errors:          {stats['errors']}")
    print(f"  Total:           {stats['total']}")
    print(f"  Today submitted: {stats['today_submitted']}")

    print(f"\nFunnel:")
    funnel = dashboard.get("funnel", {})
    print(f"  Discovered → Queued → Applied → Screening → Interview → Offer")
    print(f"  {funnel.get('discovered',0):>10}   {funnel.get('queued',0):>6}   {funnel.get('applied',0):>7}   {funnel.get('screening',0):>9}   {funnel.get('interview',0):>9}   {funnel.get('offer',0):>5}")

    rates = dashboard.get("conversion_rates", {})
    print(f"\nConversion Rates:")
    print(f"  Applied → Screening: {rates.get('applied_to_screening', 0)}%")
    print(f"  Screening → Interview: {rates.get('screening_to_interview', 0)}%")
    print(f"  Interview → Offer: {rates.get('interview_to_offer', 0)}%")

    print(f"\nWeek applications: {dashboard.get('week_applied', 0)}")

    limiter = get_limiter()
    limiter_stats = limiter.get_stats()
    if limiter_stats:
        print(f"\nRate Limiter:")
        for board, ls in sorted(limiter_stats.items()):
            print(f"  {board}: {ls['requests_today']}/{ls['daily_cap']} requests | backoff: {ls['backoff_level']}")


def cmd_schedule(args, config):
    """Run or show scheduler."""
    from scheduler import Scheduler

    sched = Scheduler(config, SCRIPT_DIR)

    if "--show" in args:
        status = sched.get_status()
        print(json.dumps(status, indent=2))
        return

    print("Starting scheduler daemon...")
    asyncio.run(sched.run_daemon())


def cmd_export(args, config):
    """Export all data for dashboard import."""
    from apply_engine import ApplicationQueue
    from analytics import AnalyticsEngine
    from qa_bank import QABank
    from resume_parser import load_profile

    queue = ApplicationQueue(SCRIPT_DIR)
    analytics = AnalyticsEngine(SCRIPT_DIR)
    qa_bank = QABank(SCRIPT_DIR)
    profile = load_profile(SCRIPT_DIR)

    export = {
        "exported_at": datetime.now().isoformat(),
        "applicationQueue": [a.to_dict() for a in queue.queue],
        "analytics": analytics.export_for_dashboard(),
        "qaBank": qa_bank.export_for_dashboard(),
        "resumeProfile": profile,
        "queueStats": queue.get_stats(),
        "automationConfig": config.get("automation", {}),
    }

    # Also include discovered jobs if available
    jobs_file = SCRIPT_DIR / "discovered_jobs.json"
    if jobs_file.exists():
        with open(jobs_file) as f:
            export["discoveredJobs"] = json.load(f)

    output_file = SCRIPT_DIR / "engine_export.json"
    with open(output_file, 'w') as f:
        json.dump(export, f, indent=2)

    print(f"Exported to {output_file}")
    print(f"  Queue: {len(export['applicationQueue'])} applications")
    print(f"  Q&A Bank: {len(export['qaBank'])} entries")
    print(f"  Jobs: {len(export.get('discoveredJobs', []))} discovered")


def cmd_materials(args, config):
    """Manage resume/CL variants and A/B testing."""
    from material_manager import MaterialManager

    mgr = MaterialManager(SCRIPT_DIR)

    if not args or "--summary" in args:
        mgr.print_summary()
        return

    if "--list-resume" in args:
        variants = mgr.list_resume_variants(active_only=False)
        print(f"\nResume Variants ({len(variants)}):")
        for v in variants:
            active = "" if v.get("is_active", True) else " [INACTIVE]"
            print(f"  {v['id']}: {v['name']} ({v['sector']}) — {v.get('applications_used',0)} apps, score={v.get('score',0):.2f}{active}")
        return

    if "--list-cl" in args:
        variants = mgr.list_cover_letter_variants(active_only=False)
        print(f"\nCover Letter Variants ({len(variants)}):")
        for v in variants:
            print(f"  {v['id']}: {v['name']} [{v['tone']}/{v['sector']}] — {v.get('applications_used',0)} apps, score={v.get('score',0):.2f}")
        return

    if "--create-resume" in args:
        idx = args.index("--create-resume")
        remaining = args[idx+1:]
        if len(remaining) < 3:
            print("Usage: python main.py materials --create-resume FILE SECTOR NAME")
            return
        file_path, sector = remaining[0], remaining[1]
        name = " ".join(remaining[2:])
        vid = mgr.create_resume_variant(name, file_path, sector)
        print(f"Created resume variant: {vid}")
        return

    if "--create-cl" in args:
        idx = args.index("--create-cl")
        remaining = args[idx+1:]
        if len(remaining) < 3:
            print("Usage: python main.py materials --create-cl TONE SECTOR NAME")
            return
        tone, sector = remaining[0], remaining[1]
        name = " ".join(remaining[2:])
        vid = mgr.create_cover_letter_variant(name, tone, sector)
        print(f"Created CL variant: {vid}")
        return

    if "--performance" in args:
        resume_comp = mgr.get_variant_comparison("resume")
        cl_comp = mgr.get_variant_comparison("cover_letter")
        pairings = mgr.get_best_pairings_by_sector()

        print("\n== Resume Variant Performance ==")
        for v in resume_comp["variants"]:
            print(f"  {v['name']:<25} score={v.get('score',0):>6.2f}  CB={v.get('callback_rate',0)*100:.0f}%  IV={v.get('interview_rate',0)*100:.0f}%  [{v.get('status','?')}]")

        print("\n== CL Variant Performance ==")
        for v in cl_comp["variants"]:
            print(f"  {v['name']:<25} score={v.get('score',0):>6.2f}  CB={v.get('callback_rate',0)*100:.0f}%  IV={v.get('interview_rate',0)*100:.0f}%  [{v.get('status','?')}]")

        print("\n== Best Pairings by Sector ==")
        for sector, p in sorted(pairings.items()):
            print(f"  {sector:<12} Resume: {p['resume_name']:<20} CL: {p['cl_name']:<20} Combined: {p['combined_score']:.2f}")
        return

    if "--record-outcome" in args:
        idx = args.index("--record-outcome")
        remaining = args[idx+1:]
        if len(remaining) < 2:
            print("Usage: python main.py materials --record-outcome PAIRING_ID OUTCOME")
            print("  Outcomes: callback, interview, offer, rejected, ghosted")
            return
        pairing_id, outcome = remaining[0], remaining[1]
        success = mgr.record_pairing_outcome(pairing_id, outcome)
        if success:
            print(f"Recorded {outcome} for pairing {pairing_id}")
            # Also update analytics
            from analytics import AnalyticsEngine
            analytics = AnalyticsEngine(SCRIPT_DIR)
            pairing = mgr.get_pairing(pairing_id)
            if pairing:
                analytics.record_outcome(pairing.get("job_id", ""), pairing.get("company", ""), outcome, pairing_id)
        return

    if "--suggestions" in args:
        profile_file = SCRIPT_DIR / "resume_profile.json"
        if not profile_file.exists():
            print("No resume_profile.json. Run: python main.py resume --file YOUR_RESUME.pdf")
            return
        with open(profile_file) as f:
            profile = json.load(f)
        suggestions = mgr.generate_resume_suggestions(profile)
        for s in suggestions:
            print(f"\n{'='*50}")
            print(f"Sector: {s['sector'].upper()}")
            print(f"Suggested name: {s['suggested_name']}")
            print(f"Title: {s['title_suggestion']}")
            print(f"Angle: {s['summary_angle']}")
            if s['emphasis_skills']:
                print(f"Emphasize: {', '.join(s['emphasis_skills'][:5])}")
            if s['keywords_to_add']:
                print(f"Keywords to add: {', '.join(s['keywords_to_add'][:5])}")
        return

    if "--export" in args:
        data = mgr.export_for_dashboard()
        out_file = SCRIPT_DIR / "material_export.json"
        with open(out_file, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Exported material data to {out_file}")
        return

    print("Unknown materials option. Use: --list-resume, --list-cl, --create-resume, --create-cl, --performance, --record-outcome, --suggestions, --export")


def cmd_init(args, config):
    """Interactive setup wizard."""
    from setup_wizard import SetupWizard
    wizard = SetupWizard(SCRIPT_DIR)
    wizard.run()


# =====================================================================
# AI-POWERED COMMANDS
# =====================================================================

def _load_job_by_id(job_id):
    """Load a job from discovered_jobs.json by ID."""
    jobs_file = SCRIPT_DIR / "discovered_jobs.json"
    if not jobs_file.exists():
        print("No discovered_jobs.json found. Run: python main.py discover")
        return None
    with open(jobs_file) as f:
        jobs = json.load(f)
    for job in jobs:
        if job.get("id") == job_id or job.get("job_id") == job_id:
            return job
    # Try partial match
    for job in jobs:
        jid = job.get("id", job.get("job_id", ""))
        if job_id in jid:
            return job
    print(f"Job ID '{job_id}' not found. Use 'python main.py status' to see available jobs.")
    return None


def _get_ai_engine(config):
    """Initialize and return the AI engine."""
    from ai_engine import get_engine
    engine = get_engine(SCRIPT_DIR, config.config if hasattr(config, 'config') else config)
    if not engine.is_available():
        print("AI not available. Set OPENROUTER_API_KEY in .env or environment.")
        print("Get a key at: https://openrouter.ai/keys")
        return None
    return engine


def cmd_ai_cover_letter(args, config):
    """Generate an AI-powered cover letter."""
    from resume_parser import load_profile

    job_id = None
    if "--job-id" in args:
        idx = args.index("--job-id")
        if idx + 1 < len(args):
            job_id = args[idx + 1]

    tone = "confident"
    if "--tone" in args:
        idx = args.index("--tone")
        if idx + 1 < len(args):
            tone = args[idx + 1]

    if not job_id:
        print("Usage: python main.py ai-cover-letter --job-id JOB_ID [--tone confident|warm|formal]")
        return

    job = _load_job_by_id(job_id)
    if not job:
        return

    engine = _get_ai_engine(config)
    if not engine:
        return

    profile = load_profile(SCRIPT_DIR)
    if not profile:
        print("No resume profile. Run: python main.py resume --file your_resume.pdf")
        return

    print(f"\nGenerating cover letter for: {job.get('title', '')} at {job.get('company', '')}")
    print(f"Model: {engine.get_model_for_task('cover_letter')} | Tone: {tone}\n")

    letter = engine.generate_cover_letter(job, profile, tone=tone)
    if letter:
        print(letter)
        # Save to file
        out_file = SCRIPT_DIR / f"cover_letter_{job_id[:8]}.txt"
        out_file.write_text(letter)
        print(f"\nSaved to: {out_file}")
    else:
        print("AI generation failed. Check your API key and try again.")


def cmd_ai_score(args, config):
    """AI-enhanced job scoring."""
    from resume_parser import load_profile

    job_id = None
    if "--job-id" in args:
        idx = args.index("--job-id")
        if idx + 1 < len(args):
            job_id = args[idx + 1]

    if not job_id:
        print("Usage: python main.py ai-score --job-id JOB_ID")
        return

    job = _load_job_by_id(job_id)
    if not job:
        return

    engine = _get_ai_engine(config)
    if not engine:
        return

    profile = load_profile(SCRIPT_DIR)
    if not profile:
        print("No resume profile. Run: python main.py resume --file your_resume.pdf")
        return

    desc = job.get("description", job.get("snippet", ""))
    print(f"\nScoring: {job.get('title', '')} at {job.get('company', '')}")
    print(f"Model: {engine.get_model_for_task('score_job_fit')}\n")

    result = engine.score_job_fit(desc, profile)
    if result:
        base = job.get("match", 0)
        adj = result.get("adjustment", 0)
        print(f"Base score:    {base}")
        print(f"AI adjustment: {'+' if adj >= 0 else ''}{adj}")
        print(f"Final score:   {base + adj}")
        print(f"\nReasoning: {result.get('reasoning', 'N/A')}")
        if result.get("fit_areas"):
            print(f"Strengths: {', '.join(result['fit_areas'])}")
        if result.get("gap_areas"):
            print(f"Gaps: {', '.join(result['gap_areas'])}")
        print(f"Interview likelihood: {result.get('interview_likelihood', 'N/A')}")
    else:
        print("AI scoring failed.")


def cmd_ai_interview(args, config):
    """Generate AI interview answer."""
    from resume_parser import load_profile

    question = None
    if "--question" in args:
        idx = args.index("--question")
        if idx + 1 < len(args):
            question = args[idx + 1]

    job_id = None
    if "--job-id" in args:
        idx = args.index("--job-id")
        if idx + 1 < len(args):
            job_id = args[idx + 1]

    if not question:
        print("Usage: python main.py ai-interview --question \"Tell me about yourself\" [--job-id JOB_ID]")
        return

    engine = _get_ai_engine(config)
    if not engine:
        return

    profile = load_profile(SCRIPT_DIR)
    if not profile:
        print("No resume profile. Run: python main.py resume --file your_resume.pdf")
        return

    job_context = {}
    if job_id:
        job = _load_job_by_id(job_id)
        if job:
            job_context = job

    print(f"\nQuestion: {question}")
    print(f"Model: {engine.get_model_for_task('interview_answer')}\n")

    answer = engine.generate_interview_answers(question, job_context, profile)
    if answer:
        print(answer)
    else:
        print("AI generation failed.")


def cmd_ai_research(args, config):
    """AI-powered company research."""
    company = None
    if "--company" in args:
        idx = args.index("--company")
        if idx + 1 < len(args):
            company = args[idx + 1]

    if not company:
        print("Usage: python main.py ai-research --company \"Acme Corp\"")
        return

    engine = _get_ai_engine(config)
    if not engine:
        return

    print(f"\nResearching: {company}")
    print(f"Model: {engine.get_model_for_task('company_research_synthesis')}")

    try:
        from brave_search import BraveSearch
        brave = BraveSearch(SCRIPT_DIR)
        if brave.is_available():
            print("Brave Search: enabled (real-time data)")
        else:
            print("Brave Search: disabled (AI will use training data only)")
    except ImportError:
        brave = None
        print("Brave Search: not available")

    print()
    result = engine.research_company(company, brave)
    if result:
        print(json.dumps(result, indent=2))
        # Save
        out_file = SCRIPT_DIR / f"research_{company.lower().replace(' ', '_')}.json"
        with open(out_file, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"\nSaved to: {out_file}")
    else:
        print("Research failed.")


def cmd_ai_pitch(args, config):
    """Generate AI elevator pitch."""
    from resume_parser import load_profile

    job_id = None
    if "--job-id" in args:
        idx = args.index("--job-id")
        if idx + 1 < len(args):
            job_id = args[idx + 1]

    if not job_id:
        print("Usage: python main.py ai-pitch --job-id JOB_ID")
        return

    job = _load_job_by_id(job_id)
    if not job:
        return

    engine = _get_ai_engine(config)
    if not engine:
        return

    profile = load_profile(SCRIPT_DIR)
    if not profile:
        print("No resume profile. Run: python main.py resume --file your_resume.pdf")
        return

    print(f"\nGenerating pitch for: {job.get('title', '')} at {job.get('company', '')}")
    result = engine.generate_pitch(job, profile)
    if result:
        print(f"\n{'='*50}")
        print(result.get("pitch", ""))
        print(f"{'='*50}")
        if result.get("key_hooks"):
            print(f"\nKey hooks: {', '.join(result['key_hooks'])}")
        if result.get("personalization_notes"):
            print(f"Notes: {result['personalization_notes']}")
    else:
        print("Pitch generation failed.")


def cmd_ai_coach(args, config):
    """Generate AI interview coaching guide."""
    from resume_parser import load_profile

    job_id = None
    if "--job-id" in args:
        idx = args.index("--job-id")
        if idx + 1 < len(args):
            job_id = args[idx + 1]

    if not job_id:
        print("Usage: python main.py ai-coach --job-id JOB_ID")
        return

    job = _load_job_by_id(job_id)
    if not job:
        return

    engine = _get_ai_engine(config)
    if not engine:
        return

    profile = load_profile(SCRIPT_DIR)
    if not profile:
        print("No resume profile. Run: python main.py resume --file your_resume.pdf")
        return

    print(f"\nGenerating coaching guide for: {job.get('title', '')} at {job.get('company', '')}")
    result = engine.generate_coaching_guide(job, profile)
    if result and not result.get("error"):
        print(f"\n{'='*50}")
        print(f"Company Angle: {result.get('company_angle', 'N/A')}")
        print(f"\nKey Themes:")
        for theme in result.get("key_themes", []):
            print(f"  - {theme}")
        print(f"\nLikely Questions:")
        for q in result.get("likely_questions", []):
            if isinstance(q, dict):
                print(f"  Q: {q.get('question', '')}")
                print(f"     Approach: {q.get('approach', '')}")
            else:
                print(f"  - {q}")
        print(f"\nTalking Points:")
        for tp in result.get("talking_points", []):
            print(f"  - {tp}")
        if result.get("red_flags_to_address"):
            print(f"\nRed Flags to Address:")
            for rf in result["red_flags_to_address"]:
                print(f"  ! {rf}")
        print(f"\nClosing Strategy: {result.get('closing_strategy', 'N/A')}")

        # Save
        out_file = SCRIPT_DIR / f"coaching_{job_id[:8]}.json"
        with open(out_file, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"\nSaved to: {out_file}")
    else:
        print("Coaching guide generation failed.")


def cmd_ai_usage(args, config):
    """Show AI usage statistics."""
    engine = _get_ai_engine(config)
    if not engine:
        return

    stats = engine.get_usage_stats()
    print(f"\n{'='*50}")
    print(f"AI Usage Statistics")
    print(f"{'='*50}")
    print(f"Total calls:       {stats.get('total_calls', 0)}")
    print(f"Input tokens:      {stats.get('total_input_tokens', 0):,}")
    print(f"Output tokens:     {stats.get('total_output_tokens', 0):,}")
    print(f"Estimated cost:    ${stats.get('estimated_cost_usd', 0):.4f}")

    by_model = stats.get("by_model", {})
    if by_model:
        print(f"\nBy Model:")
        for model, data in sorted(by_model.items()):
            print(f"  {model}: {data['calls']} calls, ${data['cost']:.4f}")

    by_task = stats.get("by_task", {})
    if by_task:
        print(f"\nBy Task:")
        for task, data in sorted(by_task.items()):
            print(f"  {task}: {data['calls']} calls, ${data['cost']:.4f}")

    daily = stats.get("daily", {})
    if daily:
        print(f"\nRecent Daily Usage:")
        for day in sorted(daily.keys())[-7:]:
            d = daily[day]
            print(f"  {day}: {d['calls']} calls, ${d['cost']:.4f}")


def main():
    args = sys.argv[1:]

    if not args or "--help" in args:
        print(__doc__)
        return

    config = ConfigManager(SCRIPT_DIR)
    command = args[0]

    commands = {
        "discover": cmd_discover,
        "apply": cmd_apply,
        "full-cycle": cmd_full_cycle,
        "resume": cmd_resume,
        "qa": cmd_qa,
        "status": cmd_status,
        "stats": cmd_status,
        "schedule": cmd_schedule,
        "export": cmd_export,
        "materials": cmd_materials,
        "init": cmd_init,
        # AI-powered commands
        "ai-cover-letter": cmd_ai_cover_letter,
        "ai-score": cmd_ai_score,
        "ai-interview": cmd_ai_interview,
        "ai-research": cmd_ai_research,
        "ai-pitch": cmd_ai_pitch,
        "ai-coach": cmd_ai_coach,
        "ai-usage": cmd_ai_usage,
    }

    if command in commands:
        commands[command](args[1:], config)
    else:
        print(f"Unknown command: {command}")
        print(f"Available: {', '.join(commands.keys())}")


if __name__ == "__main__":
    main()
