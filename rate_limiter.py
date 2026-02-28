#!/usr/bin/env python3
"""
Rate Limiter — Per-board request throttling with jitter, user-agent rotation,
daily caps, and backoff on 429/captcha detection.
"""

import time
import random
import threading
from datetime import datetime, date
from collections import defaultdict

# =====================================================================
# USER AGENT POOL
# =====================================================================

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OPR/106.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Vivaldi/6.5",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; WOW64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

# =====================================================================
# DEFAULT RATE CONFIGS PER BOARD
# =====================================================================

DEFAULT_BOARD_RATES = {
    "indeed":           {"min_delay": 3.0, "max_delay": 7.0,  "daily_cap": 200, "backoff_factor": 2.0},
    "linkedin":         {"min_delay": 5.0, "max_delay": 10.0, "daily_cap": 150, "backoff_factor": 2.5},
    "glassdoor":        {"min_delay": 4.0, "max_delay": 8.0,  "daily_cap": 150, "backoff_factor": 2.0},
    "ziprecruiter":     {"min_delay": 3.0, "max_delay": 6.0,  "daily_cap": 200, "backoff_factor": 2.0},
    "monster":          {"min_delay": 2.0, "max_delay": 5.0,  "daily_cap": 250, "backoff_factor": 1.5},
    "careerbuilder":    {"min_delay": 2.0, "max_delay": 5.0,  "daily_cap": 250, "backoff_factor": 1.5},
    "dice":             {"min_delay": 2.0, "max_delay": 5.0,  "daily_cap": 200, "backoff_factor": 1.5},
    "builtin":          {"min_delay": 2.0, "max_delay": 4.0,  "daily_cap": 200, "backoff_factor": 1.5},
    "wellfound":        {"min_delay": 3.0, "max_delay": 6.0,  "daily_cap": 150, "backoff_factor": 2.0},
    "biospace":         {"min_delay": 2.0, "max_delay": 4.0,  "daily_cap": 200, "backoff_factor": 1.5},
    "usajobs":          {"min_delay": 1.0, "max_delay": 3.0,  "daily_cap": 300, "backoff_factor": 1.5},
    "clearancejobs":    {"min_delay": 2.0, "max_delay": 5.0,  "daily_cap": 200, "backoff_factor": 1.5},
    "flexjobs":         {"min_delay": 3.0, "max_delay": 6.0,  "daily_cap": 150, "backoff_factor": 2.0},
    "weworkremotely":   {"min_delay": 1.0, "max_delay": 3.0,  "daily_cap": 200, "backoff_factor": 1.5},
    "remoteok":         {"min_delay": 1.0, "max_delay": 3.0,  "daily_cap": 200, "backoff_factor": 1.5},
    "ycombinator":      {"min_delay": 2.0, "max_delay": 5.0,  "daily_cap": 200, "backoff_factor": 2.0},
    "simplyhired":      {"min_delay": 2.0, "max_delay": 5.0,  "daily_cap": 200, "backoff_factor": 1.5},
    "adzuna":           {"min_delay": 1.0, "max_delay": 3.0,  "daily_cap": 300, "backoff_factor": 1.5},
    "themuse":          {"min_delay": 1.0, "max_delay": 3.0,  "daily_cap": 300, "backoff_factor": 1.5},
    "jooble":           {"min_delay": 2.0, "max_delay": 5.0,  "daily_cap": 200, "backoff_factor": 1.5},
    "career_page":      {"min_delay": 2.0, "max_delay": 5.0,  "daily_cap": 500, "backoff_factor": 1.5},
    "default":          {"min_delay": 2.0, "max_delay": 5.0,  "daily_cap": 200, "backoff_factor": 2.0},
}


class RateLimiter:
    """Thread-safe per-board rate limiter with jitter, daily caps, and backoff."""

    def __init__(self, custom_rates=None):
        self.rates = {**DEFAULT_BOARD_RATES}
        if custom_rates:
            self.rates.update(custom_rates)
        self._last_request = defaultdict(float)  # board -> timestamp
        self._daily_counts = defaultdict(int)     # board -> count today
        self._daily_date = date.today()
        self._backoff_level = defaultdict(int)    # board -> backoff multiplier
        self._lock = threading.Lock()

    def _get_rate(self, board):
        """Get rate config for a board, falling back to default."""
        return self.rates.get(board, self.rates["default"])

    def _reset_daily_if_needed(self):
        """Reset daily counters if the date has changed."""
        today = date.today()
        if today != self._daily_date:
            self._daily_counts.clear()
            self._backoff_level.clear()
            self._daily_date = today

    def can_request(self, board):
        """Check if we can make a request to this board (under daily cap)."""
        with self._lock:
            self._reset_daily_if_needed()
            rate = self._get_rate(board)
            return self._daily_counts[board] < rate["daily_cap"]

    def wait(self, board):
        """Wait the appropriate amount of time before making a request.
        Returns True if request is allowed, False if daily cap reached."""
        with self._lock:
            self._reset_daily_if_needed()
            rate = self._get_rate(board)

            # Check daily cap
            if self._daily_counts[board] >= rate["daily_cap"]:
                return False

            # Calculate delay with jitter and backoff
            base_delay = random.uniform(rate["min_delay"], rate["max_delay"])
            backoff = rate["backoff_factor"] ** self._backoff_level[board]
            delay = base_delay * backoff

            # Ensure minimum time since last request
            elapsed = time.time() - self._last_request[board]
            wait_time = max(0, delay - elapsed)

            # Reserve this slot (increment count while holding lock)
            self._daily_counts[board] += 1

        # Sleep OUTSIDE the lock so other boards aren't blocked
        if wait_time > 0:
            time.sleep(wait_time)

        # Update timestamp after sleep
        with self._lock:
            self._last_request[board] = time.time()
        return True

    def report_success(self, board):
        """Report a successful request — reduces backoff."""
        with self._lock:
            if self._backoff_level[board] > 0:
                self._backoff_level[board] -= 1

    def report_throttled(self, board):
        """Report a 429 or captcha — increases backoff."""
        with self._lock:
            self._backoff_level[board] = min(self._backoff_level[board] + 1, 5)

    def report_blocked(self, board):
        """Report being blocked — max out backoff for this board."""
        with self._lock:
            self._backoff_level[board] = 5

    def get_random_user_agent(self):
        """Return a random user agent string."""
        return random.choice(USER_AGENTS)

    def get_stats(self):
        """Return current rate limiter stats."""
        with self._lock:
            self._reset_daily_if_needed()
            stats = {}
            for board in set(list(self._daily_counts.keys()) + list(self._backoff_level.keys())):
                rate = self._get_rate(board)
                stats[board] = {
                    "requests_today": self._daily_counts[board],
                    "daily_cap": rate["daily_cap"],
                    "remaining": rate["daily_cap"] - self._daily_counts[board],
                    "backoff_level": self._backoff_level[board],
                    "current_delay_range": (
                        rate["min_delay"] * (rate["backoff_factor"] ** self._backoff_level[board]),
                        rate["max_delay"] * (rate["backoff_factor"] ** self._backoff_level[board])
                    )
                }
            return stats


# Module-level singleton
_limiter = None

def get_limiter(custom_rates=None):
    """Get or create the global rate limiter instance."""
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(custom_rates)
    return _limiter
