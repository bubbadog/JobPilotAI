#!/usr/bin/env python3
"""
AI Engine — OpenRouter Multi-Model AI Integration
JobPilotAI v5

Uses OpenRouter (openrouter.ai) as the AI provider, enabling access to multiple models
through a single API. Implements intelligent model routing:
  - Gemini 3.1 Pro Preview: routine tasks (cover letters, follow-ups, outreach)
  - Claude Sonnet 4.6: medium complexity (scoring refinement, interview prep)
  - Claude Opus 4.6: hard tasks (complex analysis, multi-doc synthesis)

OpenRouter uses the OpenAI-compatible API format, so we use the openai library
with a custom base_url.

Configuration:
  OPENROUTER_API_KEY env var (or .env file)
  BRAVE_API_KEY env var for company research (optional)
"""

import json
import os
import time
import hashlib
from pathlib import Path
from datetime import datetime, timedelta

# =====================================================================
# MODEL DEFINITIONS
# =====================================================================

MODELS = {
    "gemini": {
        "id": "google/gemini-2.5-pro-preview-06-05",
        "name": "Gemini 2.5 Pro Preview",
        "tier": "routine",
        "cost_per_1m_input": 2.50,
        "cost_per_1m_output": 15.00,
    },
    "sonnet": {
        "id": "anthropic/claude-sonnet-4",
        "name": "Claude Sonnet 4",
        "tier": "medium",
        "cost_per_1m_input": 3.00,
        "cost_per_1m_output": 15.00,
    },
    "opus": {
        "id": "anthropic/claude-opus-4",
        "name": "Claude Opus 4",
        "tier": "hard",
        "cost_per_1m_input": 15.00,
        "cost_per_1m_output": 75.00,
    },
}

# Task → model routing
TASK_ROUTING = {
    # Routine tasks — Gemini (cheapest, high quality)
    "cover_letter": "gemini",
    "follow_up_email": "gemini",
    "outreach_message": "gemini",
    "resume_tweaks": "gemini",
    
    # Medium tasks — Sonnet (balanced)
    "score_job_fit": "sonnet",
    "interview_answer": "sonnet",
    "coaching_guide": "sonnet",
    "pitch": "sonnet",
    
    # Hard tasks — Opus (best reasoning)
    "company_research_synthesis": "opus",
    "interview_evaluation": "opus",
    "complex_analysis": "opus",
}


# =====================================================================
# RESPONSE CACHE
# =====================================================================

class ResponseCache:
    """Simple in-memory + disk cache for AI responses."""

    def __init__(self, cache_dir, ttl_hours=24):
        self.cache_dir = Path(cache_dir) / ".ai_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = timedelta(hours=ttl_hours)
        self._memory = {}

    def _key(self, prompt, model):
        raw = f"{model}:{prompt}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, prompt, model):
        key = self._key(prompt, model)
        # Check memory first
        if key in self._memory:
            entry = self._memory[key]
            if datetime.now() - entry["ts"] < self.ttl:
                return entry["response"]
        # Check disk
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text())
                ts = datetime.fromisoformat(data["ts"])
                if datetime.now() - ts < self.ttl:
                    self._memory[key] = {"response": data["response"], "ts": ts}
                    return data["response"]
            except (json.JSONDecodeError, KeyError):
                pass
        return None

    def set(self, prompt, model, response):
        key = self._key(prompt, model)
        entry = {"response": response, "ts": datetime.now()}
        self._memory[key] = entry
        cache_file = self.cache_dir / f"{key}.json"
        cache_file.write_text(json.dumps({
            "response": response,
            "ts": entry["ts"].isoformat(),
            "model": model,
        }, indent=2))

    def clear(self):
        self._memory.clear()
        for f in self.cache_dir.glob("*.json"):
            f.unlink()


# =====================================================================
# AI ENGINE
# =====================================================================

class AIEngine:
    """Central AI module using OpenRouter with multi-model routing."""

    def __init__(self, config_dir=None, config=None):
        self.config_dir = Path(config_dir) if config_dir else Path(__file__).parent
        self.config = config or {}
        
        # Load API key
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not self.api_key:
            env_file = self.config_dir / ".env"
            if env_file.exists():
                for line in env_file.read_text().splitlines():
                    if line.startswith("OPENROUTER_API_KEY="):
                        self.api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
        
        # AI config from job_search_config.json
        ai_config = self.config.get("ai", {})
        self.enabled = ai_config.get("enabled", True) and bool(self.api_key)
        self.default_model = ai_config.get("default_model", "gemini")
        self.max_tokens_cover_letter = ai_config.get("max_tokens_cover_letter", 1500)
        self.max_tokens_interview = ai_config.get("max_tokens_interview", 1000)
        self.max_tokens_default = ai_config.get("max_tokens_default", 1200)
        self.ai_scoring_enabled = ai_config.get("ai_scoring_enabled", True)
        self.ai_scoring_threshold = ai_config.get("ai_scoring_threshold", 70)
        self.cache_ttl = ai_config.get("cache_ttl_hours", 24)
        
        # Initialize cache
        self.cache = ResponseCache(self.config_dir, self.cache_ttl)
        
        # Usage tracking
        self._usage_file = self.config_dir / ".ai_usage.json"
        self._usage = self._load_usage()

        # Try to import openai
        self._client = None

    def _get_client(self):
        """Lazy-init OpenAI client with OpenRouter base URL."""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=self.api_key,
                )
            except ImportError:
                raise RuntimeError(
                    "openai package required. Install: pip install openai"
                )
        return self._client

    def _get_model(self, task):
        """Get the model ID for a task based on routing config."""
        model_key = TASK_ROUTING.get(task, self.default_model)
        # Allow config override
        overrides = self.config.get("ai", {}).get("model_overrides", {})
        if task in overrides:
            model_key = overrides[task]
        return MODELS.get(model_key, MODELS["gemini"])

    def _call(self, task, system_prompt, user_prompt, max_tokens=None, temperature=0.7):
        """Make an API call with routing, caching, and usage tracking."""
        if not self.enabled:
            return None

        model_info = self._get_model(task)
        model_id = model_info["id"]
        
        # Check cache
        cache_key = f"{system_prompt}\n---\n{user_prompt}"
        cached = self.cache.get(cache_key, model_id)
        if cached is not None:
            return cached

        # Make API call
        client = self._get_client()
        tokens = max_tokens or self.max_tokens_default

        try:
            response = client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=tokens,
                temperature=temperature,
                extra_headers={
                    "HTTP-Referer": "https://github.com/jobpilotai",
                    "X-Title": "JobPilotAI",
                },
            )
            result = response.choices[0].message.content

            # Track usage
            usage = response.usage
            self._track_usage(task, model_id, usage.prompt_tokens if usage else 0, usage.completion_tokens if usage else 0)

            # Cache result
            self.cache.set(cache_key, model_id, result)
            return result

        except Exception as e:
            print(f"[AI] Error calling {model_info['name']}: {e}")
            return None

    def _load_usage(self):
        """Load usage tracking data."""
        if self._usage_file.exists():
            try:
                return json.loads(self._usage_file.read_text())
            except (json.JSONDecodeError, IOError):
                pass
        return {"total_calls": 0, "total_input_tokens": 0, "total_output_tokens": 0,
                "estimated_cost_usd": 0.0, "by_model": {}, "by_task": {}, "daily": {}}

    def _track_usage(self, task, model_id, input_tokens, output_tokens):
        """Track API usage and estimated costs."""
        # Find cost rates
        model_info = None
        for m in MODELS.values():
            if m["id"] == model_id:
                model_info = m
                break
        if not model_info:
            model_info = MODELS["gemini"]

        cost = (input_tokens / 1_000_000 * model_info["cost_per_1m_input"] +
                output_tokens / 1_000_000 * model_info["cost_per_1m_output"])

        self._usage["total_calls"] += 1
        self._usage["total_input_tokens"] += input_tokens
        self._usage["total_output_tokens"] += output_tokens
        self._usage["estimated_cost_usd"] += cost

        # By model
        if model_id not in self._usage["by_model"]:
            self._usage["by_model"][model_id] = {"calls": 0, "cost": 0.0}
        self._usage["by_model"][model_id]["calls"] += 1
        self._usage["by_model"][model_id]["cost"] += cost

        # By task
        if task not in self._usage["by_task"]:
            self._usage["by_task"][task] = {"calls": 0, "cost": 0.0}
        self._usage["by_task"][task]["calls"] += 1
        self._usage["by_task"][task]["cost"] += cost

        # Daily
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in self._usage["daily"]:
            self._usage["daily"][today] = {"calls": 0, "cost": 0.0}
        self._usage["daily"][today]["calls"] += 1
        self._usage["daily"][today]["cost"] += cost

        # Save
        try:
            self._usage_file.write_text(json.dumps(self._usage, indent=2))
        except IOError:
            pass

    # =================================================================
    # PUBLIC API — Cover Letters
    # =================================================================

    def generate_cover_letter(self, job, resume_profile, tone="confident"):
        """Generate a tailored cover letter for a specific job.
        
        Args:
            job: dict with title, company, description, url, etc.
            resume_profile: dict from resume_parser (contact, skills, experience, education)
            tone: "confident" | "warm" | "formal" | "enthusiastic"
        
        Returns:
            str: cover letter text, or None if AI unavailable
        """
        system_prompt = f"""You are an expert career coach and cover letter writer. 
Write a compelling, tailored cover letter in a {tone} tone.

Rules:
- Address the specific job requirements
- Reference 2-3 specific experiences from the resume that match
- Keep it under 400 words (4 paragraphs)
- Be specific, not generic — mention the company and role by name
- End with a strong call-to-action
- Do NOT include placeholder text like [Your Name] — use the actual name
- Output ONLY the letter text, no subject line or metadata"""

        user_prompt = f"""Write a cover letter for this job:

JOB TITLE: {job.get('title', 'Unknown')}
COMPANY: {job.get('company', 'Unknown')}
DESCRIPTION: {job.get('description', job.get('snippet', 'No description available'))[:3000]}

APPLICANT PROFILE:
Name: {resume_profile.get('contact', {}).get('name', 'The Applicant')}
Skills: {', '.join(_flatten_skills(resume_profile.get('skills', {})))[:500]}
Experience: {_format_experience(resume_profile.get('experience', []))[:1500]}
Education: {_format_education(resume_profile.get('education', []))[:500]}"""

        return self._call("cover_letter", system_prompt, user_prompt,
                         max_tokens=self.max_tokens_cover_letter, temperature=0.7)

    # =================================================================
    # PUBLIC API — Job Fit Scoring
    # =================================================================

    def score_job_fit(self, job_description, resume_profile):
        """AI-enhanced job fit scoring. Returns a dict with score adjustment and reasoning.
        
        Args:
            job_description: str — full job description text
            resume_profile: dict from resume_parser
            
        Returns:
            dict: {"adjustment": int (-15 to +15), "reasoning": str, "fit_areas": list, "gap_areas": list}
        """
        system_prompt = """You are an expert recruiter evaluating job fit.
Analyze how well this candidate matches the job. Be realistic and specific.

Return a JSON object with:
{
    "adjustment": <int from -15 to +15>,
    "reasoning": "<2-3 sentences explaining the fit>",
    "fit_areas": ["<strength1>", "<strength2>", ...],
    "gap_areas": ["<gap1>", "<gap2>", ...],
    "interview_likelihood": "<high|medium|low>"
}

IMPORTANT: Return ONLY valid JSON, no markdown fences or extra text."""

        user_prompt = f"""JOB DESCRIPTION:
{job_description[:3000]}

CANDIDATE PROFILE:
Skills: {', '.join(_flatten_skills(resume_profile.get('skills', {})))[:500]}
Experience: {_format_experience(resume_profile.get('experience', []))[:1500]}
Education: {_format_education(resume_profile.get('education', []))[:300]}"""

        result = self._call("score_job_fit", system_prompt, user_prompt,
                           max_tokens=500, temperature=0.3)
        if result:
            try:
                # Strip markdown fences if present
                cleaned = result.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()
                parsed = json.loads(cleaned)
                # Clamp adjustment
                parsed["adjustment"] = max(-15, min(15, int(parsed.get("adjustment", 0))))
                return parsed
            except (json.JSONDecodeError, ValueError, TypeError):
                return {"adjustment": 0, "reasoning": "AI scoring parse error", "fit_areas": [], "gap_areas": []}
        return None

    # =================================================================
    # PUBLIC API — Interview Prep
    # =================================================================

    def generate_interview_answers(self, question, job_context, resume_profile):
        """Generate a STAR-format interview answer.
        
        Args:
            question: str — the interview question
            job_context: dict with title, company, description
            resume_profile: dict from resume_parser
            
        Returns:
            str: STAR-format answer, or None
        """
        system_prompt = """You are an expert interview coach. Generate a strong answer using the STAR method
(Situation, Task, Action, Result) when applicable.

Rules:
- Draw from the candidate's actual experience
- Be specific with numbers and outcomes where possible
- Keep answers under 250 words
- Sound natural, not rehearsed
- Tailor to the specific role and company
- Output ONLY the answer text"""

        user_prompt = f"""INTERVIEW QUESTION: {question}

JOB: {job_context.get('title', '')} at {job_context.get('company', '')}
JOB DESCRIPTION: {job_context.get('description', '')[:1500]}

CANDIDATE:
Experience: {_format_experience(resume_profile.get('experience', []))[:1500]}
Skills: {', '.join(_flatten_skills(resume_profile.get('skills', {})))[:300]}"""

        return self._call("interview_answer", system_prompt, user_prompt,
                         max_tokens=self.max_tokens_interview, temperature=0.6)

    # =================================================================
    # PUBLIC API — Coaching Guide
    # =================================================================

    def generate_coaching_guide(self, job, resume_profile):
        """Generate a comprehensive interview coaching guide for a specific job.
        
        Returns:
            dict: {"company_angle": str, "key_themes": list, "likely_questions": list,
                   "talking_points": list, "red_flags_to_address": list, "closing_strategy": str}
        """
        system_prompt = """You are a senior career coach preparing a candidate for an interview.
Create a comprehensive coaching guide.

Return a JSON object with:
{
    "company_angle": "<what the company likely values most>",
    "key_themes": ["<theme to emphasize>", ...],
    "likely_questions": [
        {"question": "<likely question>", "approach": "<how to answer>"},
        ...
    ],
    "talking_points": ["<point to weave in>", ...],
    "red_flags_to_address": ["<potential concern and how to address it>", ...],
    "closing_strategy": "<how to close the interview strong>"
}

Return ONLY valid JSON."""

        user_prompt = f"""JOB: {job.get('title', '')} at {job.get('company', '')}
DESCRIPTION: {job.get('description', '')[:2500]}

CANDIDATE:
Skills: {', '.join(_flatten_skills(resume_profile.get('skills', {})))[:400]}
Experience: {_format_experience(resume_profile.get('experience', []))[:1500]}"""

        result = self._call("coaching_guide", system_prompt, user_prompt,
                           max_tokens=1500, temperature=0.5)
        if result:
            try:
                cleaned = _strip_json_fences(result)
                return json.loads(cleaned)
            except (json.JSONDecodeError, ValueError):
                return {"error": "Failed to parse coaching guide", "raw": result}
        return None

    # =================================================================
    # PUBLIC API — Elevator Pitch
    # =================================================================

    def generate_pitch(self, job, resume_profile):
        """Generate a 30-second elevator pitch tailored to a specific role.
        
        Returns:
            dict: {"pitch": str, "key_hooks": list, "personalization_notes": str}
        """
        system_prompt = """You are an expert career coach. Write a 30-second elevator pitch
(about 75-100 words) that the candidate can use when asked "Tell me about yourself" 
in an interview for this specific role.

Return JSON:
{
    "pitch": "<the elevator pitch text>",
    "key_hooks": ["<memorable hook 1>", "<memorable hook 2>"],
    "personalization_notes": "<tips for natural delivery>"
}

Return ONLY valid JSON."""

        user_prompt = f"""JOB: {job.get('title', '')} at {job.get('company', '')}
DESCRIPTION: {job.get('description', '')[:1500]}

CANDIDATE:
Name: {resume_profile.get('contact', {}).get('name', '')}
Experience: {_format_experience(resume_profile.get('experience', []))[:1000]}
Skills: {', '.join(_flatten_skills(resume_profile.get('skills', {})))[:300]}"""

        result = self._call("pitch", system_prompt, user_prompt,
                           max_tokens=500, temperature=0.6)
        if result:
            try:
                return json.loads(_strip_json_fences(result))
            except (json.JSONDecodeError, ValueError):
                return {"pitch": result, "key_hooks": [], "personalization_notes": ""}
        return None

    # =================================================================
    # PUBLIC API — Company Research (uses Brave Search)
    # =================================================================

    def research_company(self, company_name, brave_search=None):
        """Research a company using Brave Search + AI synthesis.
        
        Args:
            company_name: str
            brave_search: BraveSearch instance (optional, imported if needed)
            
        Returns:
            dict: structured company intelligence
        """
        # Get search results
        search_context = ""
        if brave_search is None:
            try:
                from brave_search import BraveSearch
                brave_search = BraveSearch()
            except (ImportError, RuntimeError):
                pass

        if brave_search and brave_search.enabled:
            results = brave_search.research_company(company_name)
            if results:
                search_context = f"\nRECENT SEARCH RESULTS:\n{json.dumps(results, indent=2)[:3000]}"

        system_prompt = """You are a business analyst preparing company intelligence for a job seeker.
Synthesize all available information into actionable insights.

Return JSON:
{
    "overview": "<1-2 sentence company description>",
    "industry": "<primary industry>",
    "size": "<estimated employee count or range>",
    "culture_signals": ["<culture insight>", ...],
    "recent_news": ["<notable recent event>", ...],
    "interview_talking_points": ["<point to reference in interview>", ...],
    "potential_concerns": ["<thing to watch out for>", ...],
    "glassdoor_sentiment": "<positive|mixed|negative|unknown>",
    "growth_trajectory": "<growing|stable|declining|unknown>"
}

Return ONLY valid JSON. If information is unavailable, use "unknown" rather than guessing."""

        user_prompt = f"""Research this company for job interview preparation:
COMPANY: {company_name}
{search_context}"""

        result = self._call("company_research_synthesis", system_prompt, user_prompt,
                           max_tokens=1200, temperature=0.4)
        if result:
            try:
                return json.loads(_strip_json_fences(result))
            except (json.JSONDecodeError, ValueError):
                return {"overview": result, "error": "parse_failed"}
        return None

    # =================================================================
    # PUBLIC API — Outreach Messages
    # =================================================================

    def generate_outreach_message(self, job, resume_profile, channel="email"):
        """Generate a networking/outreach message for a hiring manager or recruiter.
        
        Args:
            channel: "email" | "linkedin" | "cold_intro"
        """
        length_guide = {
            "email": "Keep under 150 words. Professional but personable.",
            "linkedin": "Keep under 100 words. Casual-professional LinkedIn tone.",
            "cold_intro": "Keep under 75 words. Very brief and intriguing."
        }
        
        system_prompt = f"""You are an expert at writing compelling professional outreach messages.
Write a {channel} message to a hiring manager or recruiter.

{length_guide.get(channel, length_guide['email'])}

Rules:
- Reference something specific about the company or role
- Briefly state your relevant value proposition (1-2 sentences)
- Include a clear, low-friction call to action
- Sound human, not templated
- Do NOT include subject line unless it's an email (then include it)
- Output ONLY the message text"""

        user_prompt = f"""TARGET ROLE: {job.get('title', '')} at {job.get('company', '')}
JOB DESCRIPTION: {job.get('description', '')[:1500]}

CANDIDATE:
Name: {resume_profile.get('contact', {}).get('name', '')}
Key strengths: {', '.join(_flatten_skills(resume_profile.get('skills', {})))[:300]}
Recent role: {_format_experience(resume_profile.get('experience', []))[:500]}"""

        return self._call("outreach_message", system_prompt, user_prompt,
                         max_tokens=500, temperature=0.7)

    # =================================================================
    # PUBLIC API — Follow-up Emails
    # =================================================================

    def generate_follow_up_email(self, application, template_type="post_apply"):
        """Generate a follow-up email for an application.
        
        Args:
            application: dict with title, company, applied_date, status, etc.
            template_type: "post_apply" | "post_interview" | "thank_you" | "check_in"
        """
        templates = {
            "post_apply": "a brief follow-up 1 week after applying, expressing continued interest",
            "post_interview": "a thank-you note after a phone/video interview, referencing specific discussion points",
            "thank_you": "a formal thank-you after an in-person/final round interview",
            "check_in": "a polite check-in when you haven't heard back in 2+ weeks",
        }
        
        system_prompt = f"""Write {templates.get(template_type, templates['post_apply'])}.

Rules:
- Keep it under 100 words
- Be professional but warm
- Reference the specific role
- Include a soft call to action
- Output ONLY the email body (no greeting or signature — the system adds those)"""

        user_prompt = f"""ROLE: {application.get('title', '')} at {application.get('company', '')}
APPLIED: {application.get('applied_date', 'recently')}
STATUS: {application.get('status', 'applied')}"""

        return self._call("follow_up_email", system_prompt, user_prompt,
                         max_tokens=300, temperature=0.6)

    # =================================================================
    # PUBLIC API — Resume Tweaks
    # =================================================================

    def suggest_resume_tweaks(self, job_description, resume_profile, sector="general"):
        """Suggest specific resume modifications for a job.
        
        Returns:
            dict: {"summary_suggestion": str, "skills_to_emphasize": list,
                   "keywords_to_add": list, "experience_tweaks": list, "overall_strategy": str}
        """
        system_prompt = """You are an expert resume optimizer and ATS specialist.
Analyze the job description against the resume and suggest specific, actionable tweaks.

Return JSON:
{
    "summary_suggestion": "<rewritten professional summary tailored to this role>",
    "skills_to_emphasize": ["<skill to move up or highlight>", ...],
    "keywords_to_add": ["<missing ATS keyword from the JD>", ...],
    "experience_tweaks": [
        {"section": "<which experience>", "suggestion": "<specific change>"},
        ...
    ],
    "overall_strategy": "<1-2 sentence strategy for this application>"
}

Return ONLY valid JSON."""

        user_prompt = f"""JOB DESCRIPTION ({sector} sector):
{job_description[:3000]}

CURRENT RESUME:
Skills: {', '.join(_flatten_skills(resume_profile.get('skills', {})))[:500]}
Experience: {_format_experience(resume_profile.get('experience', []))[:2000]}
Education: {_format_education(resume_profile.get('education', []))[:300]}"""

        result = self._call("resume_tweaks", system_prompt, user_prompt,
                           max_tokens=1000, temperature=0.4)
        if result:
            try:
                return json.loads(_strip_json_fences(result))
            except (json.JSONDecodeError, ValueError):
                return {"overall_strategy": result, "error": "parse_failed"}
        return None

    # =================================================================
    # PUBLIC API — Interview Answer Evaluation
    # =================================================================

    def evaluate_interview_answer(self, question, answer, job_context):
        """Evaluate a practice interview answer and provide feedback.
        
        Returns:
            dict: {"score": int (1-10), "strengths": list, "improvements": list,
                   "revised_answer": str}
        """
        system_prompt = """You are a tough but fair interview coach evaluating a practice answer.
Be specific with feedback — generic advice like "be more specific" isn't helpful.

Return JSON:
{
    "score": <1-10>,
    "strengths": ["<specific strength>", ...],
    "improvements": ["<specific actionable improvement>", ...],
    "revised_answer": "<improved version of the answer>"
}

Return ONLY valid JSON."""

        user_prompt = f"""QUESTION: {question}

CANDIDATE'S ANSWER: {answer}

JOB CONTEXT: {job_context.get('title', '')} at {job_context.get('company', '')}
{job_context.get('description', '')[:1000]}"""

        result = self._call("interview_evaluation", system_prompt, user_prompt,
                           max_tokens=1000, temperature=0.4)
        if result:
            try:
                return json.loads(_strip_json_fences(result))
            except (json.JSONDecodeError, ValueError):
                return {"score": 0, "strengths": [], "improvements": [result]}
        return None

    # =================================================================
    # UTILITY — Usage Stats
    # =================================================================

    def get_usage_stats(self):
        """Return current usage statistics."""
        return dict(self._usage)

    def is_available(self):
        """Check if AI is configured and available."""
        return self.enabled and bool(self.api_key)

    def get_model_for_task(self, task):
        """Return which model would be used for a given task."""
        model_info = self._get_model(task)
        return model_info["name"]


# =====================================================================
# HELPER FUNCTIONS
# =====================================================================

def _flatten_skills(skills_dict):
    """Flatten a nested skills dict into a flat list."""
    flat = []
    if isinstance(skills_dict, dict):
        for category, items in skills_dict.items():
            if isinstance(items, list):
                flat.extend(items)
            elif isinstance(items, str):
                flat.append(items)
    elif isinstance(skills_dict, list):
        flat = skills_dict
    return flat[:50]  # Cap at 50 to avoid token bloat


def _format_experience(experience_list):
    """Format experience entries into a concise string."""
    if not experience_list:
        return "No experience data available"
    parts = []
    for exp in experience_list[:5]:  # Max 5 entries
        if isinstance(exp, dict):
            title = exp.get("title", exp.get("role", ""))
            company = exp.get("company", exp.get("organization", ""))
            dates = exp.get("dates", exp.get("period", ""))
            desc = exp.get("description", exp.get("highlights", ""))
            if isinstance(desc, list):
                desc = "; ".join(desc[:3])
            parts.append(f"- {title} at {company} ({dates}): {str(desc)[:200]}")
        elif isinstance(exp, str):
            parts.append(f"- {exp[:200]}")
    return "\n".join(parts)


def _format_education(education_list):
    """Format education entries into a concise string."""
    if not education_list:
        return "No education data available"
    parts = []
    for edu in education_list[:3]:
        if isinstance(edu, dict):
            degree = edu.get("degree", "")
            school = edu.get("school", edu.get("institution", ""))
            year = edu.get("year", edu.get("graduation_year", ""))
            parts.append(f"- {degree} from {school} ({year})")
        elif isinstance(edu, str):
            parts.append(f"- {edu}")
    return "\n".join(parts)


def _strip_json_fences(text):
    """Strip markdown JSON fences from a response."""
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


# =====================================================================
# MODULE-LEVEL CONVENIENCE
# =====================================================================

_engine = None

def get_engine(config_dir=None, config=None):
    """Get or create the global AI engine instance."""
    global _engine
    if _engine is None:
        _engine = AIEngine(config_dir, config)
    return _engine
