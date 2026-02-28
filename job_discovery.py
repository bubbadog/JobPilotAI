#!/usr/bin/env python3
"""
Job Discovery Engine — Playwright-powered multi-board scraper that harvests
real job listings from 30+ sources. Supports search pages, APIs, and RSS feeds.
"""

import asyncio
import json
import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus, urlparse, urljoin
from dataclasses import dataclass, field, asdict
from typing import Optional

# Playwright import (install: pip install playwright && playwright install chromium)
try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

# RSS parsing
try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

# HTTP requests (for APIs)
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    try:
        import requests as httpx
        HAS_HTTPX = True
    except ImportError:
        HAS_HTTPX = False

from rate_limiter import get_limiter

SCRIPT_DIR = Path(__file__).parent

# =====================================================================
# DATA MODELS
# =====================================================================

@dataclass
class RawJob:
    """A job listing as scraped from a board."""
    title: str
    company: str
    location: str
    url: str
    board_source: str
    description: str = ""
    salary_range: str = ""
    posted_date: str = ""
    easy_apply: bool = False
    ats_platform: str = ""
    job_type: str = ""  # full-time, contract, part-time
    remote: bool = False
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())
    raw_id: str = ""

    def __post_init__(self):
        if not self.raw_id:
            key = f"{self.title.lower().strip()}:{self.company.lower().strip()}"
            self.raw_id = hashlib.md5(key.encode()).hexdigest()[:12]

    def to_dict(self):
        return asdict(self)


# =====================================================================
# BASE SCRAPER CLASS
# =====================================================================

class BoardScraper:
    """Base class for all job board scrapers."""

    board_name = "generic"
    max_pages = 5

    def __init__(self, config, rate_limiter=None):
        self.config = config
        self.limiter = rate_limiter or get_limiter()
        self.selectors = config.get("selectors", {})
        self.search_url = config.get("search_url", "")
        self.results = []

    def build_search_url(self, keyword, location):
        """Build the search URL from template."""
        url = self.search_url
        url = url.replace("{query}", quote_plus(keyword))
        url = url.replace("{location}", quote_plus(location))
        return url

    async def scrape(self, browser, keyword, location, max_results=50):
        """Main scrape entry point. Override for custom logic."""
        if not self.search_url:
            return []

        url = self.build_search_url(keyword, location)
        jobs = []
        page = await browser.new_page(
            user_agent=self.limiter.get_random_user_agent()
        )

        try:
            for page_num in range(self.max_pages):
                if len(jobs) >= max_results:
                    break

                if not self.limiter.can_request(self.board_name):
                    print(f"  [{self.board_name}] Daily cap reached, stopping")
                    break

                self.limiter.wait(self.board_name)

                try:
                    if page_num == 0:
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    else:
                        # Click next page
                        next_sel = self.selectors.get("next_page", "")
                        if not next_sel:
                            break
                        next_btn = page.locator(next_sel).first
                        if not await next_btn.is_visible():
                            break
                        await next_btn.click()
                        await page.wait_for_load_state("domcontentloaded", timeout=15000)

                    await asyncio.sleep(1)  # Let dynamic content load
                    page_jobs = await self.extract_jobs_from_page(page)
                    if not page_jobs:
                        break
                    jobs.extend(page_jobs)
                    self.limiter.report_success(self.board_name)
                    print(f"  [{self.board_name}] Page {page_num+1}: found {len(page_jobs)} jobs (total: {len(jobs)})")

                except PlaywrightTimeout:
                    print(f"  [{self.board_name}] Timeout on page {page_num+1}")
                    self.limiter.report_throttled(self.board_name)
                    break
                except Exception as e:
                    err = str(e).lower()
                    if "captcha" in err or "verify" in err or "robot" in err:
                        print(f"  [{self.board_name}] CAPTCHA detected, stopping")
                        self.limiter.report_blocked(self.board_name)
                    else:
                        print(f"  [{self.board_name}] Error on page {page_num+1}: {e}")
                        self.limiter.report_throttled(self.board_name)
                    break

        finally:
            await page.close()

        return jobs[:max_results]

    async def extract_jobs_from_page(self, page):
        """Extract job listings from a search results page."""
        jobs = []
        card_sel = self.selectors.get("job_cards", "")
        if not card_sel:
            return jobs

        cards = page.locator(card_sel)
        count = await cards.count()

        for i in range(min(count, 25)):  # Max 25 per page
            try:
                card = cards.nth(i)
                title = await self._safe_text(card, self.selectors.get("title", ""))
                company = await self._safe_text(card, self.selectors.get("company", ""))
                location = await self._safe_text(card, self.selectors.get("location", ""))
                link = await self._safe_href(card, self.selectors.get("link", ""), page)
                salary = await self._safe_text(card, self.selectors.get("salary", ""))
                posted = await self._safe_text(card, self.selectors.get("posted", ""))

                if title and (company or link):
                    job = RawJob(
                        title=title.strip(),
                        company=company.strip() if company else "",
                        location=location.strip() if location else "",
                        url=link or "",
                        board_source=self.board_name,
                        salary_range=salary.strip() if salary else "",
                        posted_date=self._parse_date(posted) if posted else "",
                        easy_apply=self.config.get("has_easy_apply", False),
                        ats_platform=self._detect_ats(link or ""),
                        remote="remote" in (location or "").lower()
                    )
                    jobs.append(job)
            except Exception:
                continue

        return jobs

    async def _safe_text(self, parent, selector):
        """Safely extract text from a selector."""
        if not selector:
            return ""
        try:
            el = parent.locator(selector).first
            if await el.is_visible():
                return await el.inner_text()
        except Exception:
            pass
        return ""

    async def _safe_href(self, parent, selector, page):
        """Safely extract href from a link selector."""
        if not selector:
            return ""
        try:
            el = parent.locator(selector).first
            href = await el.get_attribute("href")
            if href:
                if href.startswith("/"):
                    base = urlparse(page.url)
                    href = f"{base.scheme}://{base.netloc}{href}"
                return href
        except Exception:
            pass
        return ""

    def _parse_date(self, text):
        """Try to parse a date string from various formats."""
        if not text:
            return ""
        text = text.strip().lower()
        today = datetime.now()

        # "X days ago" pattern
        match = re.search(r'(\d+)\s*day', text)
        if match:
            days = int(match.group(1))
            return (today - timedelta(days=days)).strftime("%Y-%m-%d")

        # "Just posted" / "Today"
        if any(w in text for w in ["just", "today", "now"]):
            return today.strftime("%Y-%m-%d")

        # "X hours ago"
        if "hour" in text:
            return today.strftime("%Y-%m-%d")

        # Try ISO format
        for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y", "%B %d, %Y"]:
            try:
                return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue

        return ""

    def _detect_ats(self, url):
        """Detect ATS platform from URL."""
        if not url:
            return ""
        url_lower = url.lower()
        ats_patterns = {
            "greenhouse": ["greenhouse.io", "boards.greenhouse"],
            "lever": ["jobs.lever.co", "lever.co"],
            "workday": ["myworkdayjobs.com", "workday.com"],
            "icims": ["icims.com"],
            "taleo": ["taleo.net"],
            "smartrecruiters": ["smartrecruiters.com"],
            "brassring": ["brassring.com"],
            "successfactors": ["successfactors.com"],
            "jobvite": ["jobvite.com"],
            "ashby": ["ashbyhq.com"],
        }
        for ats, patterns in ats_patterns.items():
            if any(p in url_lower for p in patterns):
                return ats
        return ""


# =====================================================================
# BOARD-SPECIFIC SCRAPERS
# =====================================================================

class IndeedScraper(BoardScraper):
    board_name = "indeed"

class LinkedInScraper(BoardScraper):
    board_name = "linkedin"
    max_pages = 3  # LinkedIn is aggressive with rate limiting

class GlassdoorScraper(BoardScraper):
    board_name = "glassdoor"

class ZipRecruiterScraper(BoardScraper):
    board_name = "ziprecruiter"

class MonsterScraper(BoardScraper):
    board_name = "monster"

class CareerBuilderScraper(BoardScraper):
    board_name = "careerbuilder"

class DiceScraper(BoardScraper):
    board_name = "dice"

class BuiltInScraper(BoardScraper):
    board_name = "builtin"

class WellfoundScraper(BoardScraper):
    board_name = "wellfound"

class BioSpaceScraper(BoardScraper):
    board_name = "biospace"

class USAJobsScraper(BoardScraper):
    board_name = "usajobs"

class ClearanceJobsScraper(BoardScraper):
    board_name = "clearancejobs"

class WeWorkRemotelyScraper(BoardScraper):
    board_name = "weworkremotely"

class RemoteOKScraper(BoardScraper):
    board_name = "remoteok"

class FlexJobsScraper(BoardScraper):
    board_name = "flexjobs"

class YCombinatorScraper(BoardScraper):
    board_name = "ycombinator"

class SimplyHiredScraper(BoardScraper):
    board_name = "simplyhired"

class HigherEdJobsScraper(BoardScraper):
    board_name = "higheredjobs"


# =====================================================================
# API-BASED SCRAPERS
# =====================================================================

class APIBoardScraper(BoardScraper):
    """Base for API-based job boards."""

    async def scrape(self, browser, keyword, location, max_results=50):
        """Fetch jobs via REST API instead of browser scraping."""
        if not HAS_HTTPX:
            print(f"  [{self.board_name}] httpx/requests not available, skipping API board")
            return []

        api_url = self.config.get("api_url", "")
        if not api_url:
            return []

        url = api_url.replace("{query}", quote_plus(keyword))
        url = url.replace("{location}", quote_plus(location))

        if not self.limiter.can_request(self.board_name):
            return []

        self.limiter.wait(self.board_name)

        try:
            if hasattr(httpx, 'AsyncClient'):
                async with httpx.AsyncClient() as client:
                    resp = await client.get(url, headers={"User-Agent": self.limiter.get_random_user_agent()}, timeout=20)
                    data = resp.json()
            else:
                resp = httpx.get(url, headers={"User-Agent": self.limiter.get_random_user_agent()}, timeout=20)
                data = resp.json()

            self.limiter.report_success(self.board_name)
            return self.parse_api_response(data)[:max_results]
        except Exception as e:
            print(f"  [{self.board_name}] API error: {e}")
            self.limiter.report_throttled(self.board_name)
            return []

    def parse_api_response(self, data):
        """Override to parse board-specific API response."""
        return []


class AdzunaScraper(APIBoardScraper):
    board_name = "adzuna"

    def parse_api_response(self, data):
        jobs = []
        for item in data.get("results", []):
            jobs.append(RawJob(
                title=item.get("title", ""),
                company=item.get("company", {}).get("display_name", ""),
                location=item.get("location", {}).get("display_name", ""),
                url=item.get("redirect_url", ""),
                board_source=self.board_name,
                description=item.get("description", ""),
                salary_range=f"${item.get('salary_min', '')} - ${item.get('salary_max', '')}" if item.get("salary_min") else "",
                posted_date=item.get("created", "")[:10],
            ))
        return jobs


class TheMuseScraper(APIBoardScraper):
    board_name = "themuse"

    def parse_api_response(self, data):
        jobs = []
        for item in data.get("results", []):
            locs = item.get("locations", [])
            loc = locs[0].get("name", "") if locs else "Remote"
            jobs.append(RawJob(
                title=item.get("name", ""),
                company=item.get("company", {}).get("name", ""),
                location=loc,
                url=f"https://www.themuse.com/jobs/{item.get('id', '')}",
                board_source=self.board_name,
                description=item.get("contents", ""),
                posted_date=item.get("publication_date", "")[:10],
            ))
        return jobs


# =====================================================================
# CAREER PAGE SCRAPER (for watchlist)
# =====================================================================

class CareerPageScraper(BoardScraper):
    """Scraper for individual company career pages from watchlist."""
    board_name = "career_page"

    async def scrape_career_page(self, browser, company_name, career_url, keywords):
        """Scrape a specific company career page."""
        if not career_url:
            return []

        if not self.limiter.can_request(self.board_name):
            return []

        self.limiter.wait(self.board_name)
        page = await browser.new_page(user_agent=self.limiter.get_random_user_agent())
        jobs = []

        try:
            await page.goto(career_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # Generic extraction: look for links that look like job listings
            links = await page.evaluate("""
                () => {
                    const results = [];
                    const anchors = document.querySelectorAll('a[href]');
                    for (const a of anchors) {
                        const text = a.innerText.trim();
                        const href = a.href;
                        if (text.length > 10 && text.length < 200 &&
                            !href.includes('#') &&
                            (href.includes('job') || href.includes('career') ||
                             href.includes('position') || href.includes('opening') ||
                             href.includes('apply') || href.includes('role'))) {
                            results.push({title: text, url: href});
                        }
                    }
                    return results;
                }
            """)

            for link in links:
                title = link.get("title", "")
                url = link.get("url", "")
                # Filter by keywords if provided
                if keywords:
                    title_lower = title.lower()
                    if not any(kw.lower().split()[0] in title_lower for kw in keywords[:5]):
                        continue

                jobs.append(RawJob(
                    title=title,
                    company=company_name,
                    location="See listing",
                    url=url,
                    board_source=f"career_page:{company_name}",
                    ats_platform=self._detect_ats(url),
                ))

            self.limiter.report_success(self.board_name)
            print(f"  [career_page:{company_name}] Found {len(jobs)} job links")

        except Exception as e:
            print(f"  [career_page:{company_name}] Error: {e}")
            self.limiter.report_throttled(self.board_name)
        finally:
            await page.close()

        return jobs


# =====================================================================
# SCRAPER REGISTRY
# =====================================================================

SCRAPER_CLASSES = {
    "indeed": IndeedScraper,
    "linkedin": LinkedInScraper,
    "glassdoor": GlassdoorScraper,
    "ziprecruiter": ZipRecruiterScraper,
    "monster": MonsterScraper,
    "careerbuilder": CareerBuilderScraper,
    "dice": DiceScraper,
    "builtin": BuiltInScraper,
    "wellfound": WellfoundScraper,
    "biospace": BioSpaceScraper,
    "usajobs": USAJobsScraper,
    "clearancejobs": ClearanceJobsScraper,
    "weworkremotely": WeWorkRemotelyScraper,
    "remoteok": RemoteOKScraper,
    "flexjobs": FlexJobsScraper,
    "ycombinator": YCombinatorScraper,
    "simplyhired": SimplyHiredScraper,
    "higheredjobs": HigherEdJobsScraper,
    "adzuna": AdzunaScraper,
    "themuse": TheMuseScraper,
}


# =====================================================================
# DISCOVERY ENGINE
# =====================================================================

class DiscoveryEngine:
    """Orchestrates multi-board job discovery."""

    def __init__(self, config_manager):
        self.config = config_manager
        self.limiter = get_limiter()
        self.career_scraper = CareerPageScraper({}, self.limiter)

    async def discover(self, boards=None, keywords=None, locations=None,
                       max_per_board=50, include_watchlist=True):
        """Run full discovery across all enabled boards.

        Args:
            boards: Optional list of board names to scrape (None = all enabled)
            keywords: Override keywords (None = from config)
            locations: Override locations (None = from config)
            max_per_board: Max jobs to scrape per board
            include_watchlist: Also scrape career pages from watchlist

        Returns:
            List of RawJob objects
        """
        if not HAS_PLAYWRIGHT:
            print("ERROR: Playwright not installed. Run: pip install playwright && playwright install chromium")
            return []

        all_keywords = keywords or self.config.get_keywords()[:5]
        all_locations = locations or self.config.get_locations()[:3]
        enabled_boards = self.config.get_enabled_boards()

        if boards:
            enabled_boards = [b for b in enabled_boards if b["name"] in boards]

        all_jobs = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n{'='*60}")
        print(f"JOB DISCOVERY ENGINE — {timestamp}")
        print(f"{'='*60}")
        print(f"Boards: {len(enabled_boards)} | Keywords: {len(all_keywords)} | Locations: {len(all_locations)}")
        print(f"{'='*60}\n")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )

            # Scrape each board
            for board_cfg in enabled_boards:
                board_name = board_cfg["name"]
                scraper_cls = SCRAPER_CLASSES.get(board_name)
                if not scraper_cls:
                    print(f"[{board_name}] No scraper class found, skipping")
                    continue

                print(f"\n--- Scraping: {board_name.upper()} ---")
                scraper = scraper_cls(board_cfg, self.limiter)
                board_jobs = []

                for keyword in all_keywords[:3]:  # Top 3 keywords per board
                    for location in all_locations[:2]:  # Top 2 locations
                        try:
                            jobs = await scraper.scrape(
                                context, keyword, location,
                                max_results=max_per_board // (len(all_keywords[:3]) * len(all_locations[:2]))
                            )
                            board_jobs.extend(jobs)
                        except Exception as e:
                            print(f"  [{board_name}] Error with '{keyword}' in '{location}': {e}")

                all_jobs.extend(board_jobs)
                print(f"  [{board_name}] Total: {len(board_jobs)} jobs")

            # Scrape watchlist career pages
            if include_watchlist:
                watchlist = self.config.get_watchlist()
                if watchlist:
                    print(f"\n--- Scraping: CAREER PAGE WATCHLIST ({len(watchlist)} companies) ---")
                    for entry in watchlist:
                        company = entry.get("companyName", "")
                        url = entry.get("careerPageUrl", "")
                        if company and url:
                            jobs = await self.career_scraper.scrape_career_page(
                                context, company, url, all_keywords
                            )
                            all_jobs.extend(jobs)

            await browser.close()

        # Save raw results
        output_file = SCRIPT_DIR / "discovered_jobs_raw.json"
        with open(output_file, 'w') as f:
            json.dump([j.to_dict() for j in all_jobs], f, indent=2)

        print(f"\n{'='*60}")
        print(f"DISCOVERY COMPLETE: {len(all_jobs)} total raw jobs")
        print(f"Saved to: {output_file}")
        print(f"{'='*60}\n")

        return all_jobs


async def run_discovery(config_manager, boards=None, max_per_board=50):
    """Convenience function to run discovery."""
    engine = DiscoveryEngine(config_manager)
    return await engine.discover(boards=boards, max_per_board=max_per_board)
