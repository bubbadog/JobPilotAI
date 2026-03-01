#!/usr/bin/env python3
"""
Brave Search — Real-time web search for company research and supplemental job discovery.
JobPilotAI v5

Uses Brave Search API (https://api.search.brave.com) for:
  - Company research (culture, news, Glassdoor sentiment)
  - Salary data for negotiation
  - Supplemental job discovery (finds postings Playwright might miss)
  - Interview prep (real interview questions from Glassdoor/forums)

Configuration:
  BRAVE_API_KEY env var (or .env file)
  Free tier: 2,000 queries/month — more than enough for job search
"""

import json
import os
import time
from pathlib import Path
from datetime import datetime
from urllib.parse import quote_plus

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveSearch:
    """Wrapper for Brave Search API with structured result parsing."""

    def __init__(self, config_dir=None):
        self.api_key = os.environ.get("BRAVE_API_KEY", "")
        if not self.api_key and config_dir:
            env_file = Path(config_dir) / ".env"
            if env_file.exists():
                for line in env_file.read_text().splitlines():
                    if line.startswith("BRAVE_API_KEY="):
                        self.api_key = line.split("=", 1)[1].strip().strip('"').strip("'")

        self.enabled = bool(self.api_key) and HAS_REQUESTS
        self._last_request = 0
        self._min_delay = 1.0  # 1 second between requests

    def search(self, query, count=10):
        """Execute a Brave Search query.

        Args:
            query: search query string
            count: max results (1-20)

        Returns:
            list[dict]: search results with title, url, description
        """
        if not self.enabled:
            return []

        # Rate limit
        elapsed = time.time() - self._last_request
        if elapsed < self._min_delay:
            time.sleep(self._min_delay - elapsed)

        try:
            headers = {
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": self.api_key,
            }
            params = {
                "q": query,
                "count": min(count, 20),
                "text_decorations": False,
                "search_lang": "en",
            }

            resp = requests.get(BRAVE_API_URL, headers=headers, params=params, timeout=10)
            self._last_request = time.time()

            if resp.status_code == 429:
                print("[BraveSearch] Rate limited. Waiting 5s...")
                time.sleep(5)
                return []

            if resp.status_code != 200:
                print(f"[BraveSearch] HTTP {resp.status_code}: {resp.text[:200]}")
                return []

            data = resp.json()
            results = []
            for item in data.get("web", {}).get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("description", ""),
                    "age": item.get("age", ""),
                })
            return results

        except requests.RequestException as e:
            print(f"[BraveSearch] Request error: {e}")
            return []
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[BraveSearch] Parse error: {e}")
            return []

    def research_company(self, company_name):
        """Structured company research combining multiple search queries.

        Args:
            company_name: company name to research

        Returns:
            dict: structured company intel
        """
        if not self.enabled:
            return {}

        intel = {
            "company": company_name,
            "searched_at": datetime.now().isoformat(),
            "overview": [],
            "news": [],
            "culture": [],
            "interview_intel": [],
        }

        # Query 1: Company overview
        results = self.search(f'"{company_name}" company overview', count=5)
        intel["overview"] = [{"title": r["title"], "snippet": r["description"]} for r in results[:3]]

        # Query 2: Recent news
        results = self.search(f'"{company_name}" news 2026', count=5)
        intel["news"] = [{"title": r["title"], "snippet": r["description"], "age": r.get("age", "")} for r in results[:3]]

        # Query 3: Culture / Glassdoor
        results = self.search(f'"{company_name}" glassdoor culture reviews', count=5)
        intel["culture"] = [{"title": r["title"], "snippet": r["description"]} for r in results[:3]]

        # Query 4: Interview questions
        results = self.search(f'"{company_name}" interview questions', count=5)
        intel["interview_intel"] = [{"title": r["title"], "snippet": r["description"]} for r in results[:3]]

        return intel

    def search_salary(self, role, location=""):
        """Search for salary data for a specific role.

        Returns:
            list[dict]: salary-related search results
        """
        query = f'"{role}" salary'
        if location:
            query += f" {location}"
        query += " 2026"
        results = self.search(query, count=5)
        return [{"title": r["title"], "snippet": r["description"], "url": r["url"]} for r in results]

    def find_jobs(self, query, location=""):
        """Supplemental job discovery via web search.

        Returns:
            list[dict]: job-like search results
        """
        search_query = f"{query} jobs"
        if location:
            search_query += f" {location}"
        search_query += " apply"
        results = self.search(search_query, count=15)
        # Filter for likely job postings
        job_keywords = ["apply", "hiring", "careers", "job", "position", "opening", "role"]
        filtered = []
        for r in results:
            text = (r["title"] + " " + r["description"]).lower()
            if any(kw in text for kw in job_keywords):
                filtered.append({
                    "title": r["title"],
                    "url": r["url"],
                    "snippet": r["description"],
                    "source": "brave_search",
                })
        return filtered

    def is_available(self):
        """Check if Brave Search is configured and available."""
        return self.enabled


# Module-level convenience
_searcher = None

def get_searcher(config_dir=None):
    """Get or create the global BraveSearch instance."""
    global _searcher
    if _searcher is None:
        _searcher = BraveSearch(config_dir)
    return _searcher
