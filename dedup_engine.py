#!/usr/bin/env python3
"""
Deduplication Engine — Cross-board fuzzy matching to merge duplicate job listings.
Keeps the richest listing (longest description, most metadata, most apply options).
"""

import re
import hashlib
from difflib import SequenceMatcher
from urllib.parse import urlparse
from collections import defaultdict


# =====================================================================
# NORMALIZATION
# =====================================================================

def normalize_title(title):
    """Normalize a job title for comparison."""
    t = title.lower().strip()
    # Remove common suffixes/prefixes
    t = re.sub(r'\s*[-–—|]\s*(remote|hybrid|onsite|on-site|full-time|part-time|contract).*$', '', t)
    # Remove level numbers
    t = re.sub(r'\s*(i{1,3}|iv|v|vi|1|2|3|4|5|senior|sr\.?|junior|jr\.?|lead|principal|staff)\s*$', '', t)
    t = re.sub(r'^(senior|sr\.?|junior|jr\.?|lead|principal|staff)\s+', '', t)
    # Remove company name if it appears in the title
    t = re.sub(r'\s*[-–—@]\s*\w+.*$', '', t)
    # Normalize whitespace
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def normalize_company(company):
    """Normalize a company name for comparison."""
    c = company.lower().strip()
    # Remove common suffixes
    c = re.sub(r',?\s*(inc\.?|llc|ltd\.?|corp\.?|co\.?|corporation|company|group|holdings?|technologies|technology|tech)\.?\s*$', '', c)
    c = re.sub(r'\s+', ' ', c).strip()
    return c


def normalize_url(url):
    """Normalize a URL for deduplication."""
    if not url:
        return ""
    parsed = urlparse(url)
    # Remove tracking parameters
    path = parsed.path.rstrip('/')
    # Remove common tracking params
    clean = f"{parsed.netloc}{path}".lower()
    # Remove www prefix
    clean = re.sub(r'^www\.', '', clean)
    return clean


def fuzzy_match(s1, s2, threshold=0.85):
    """Check if two strings are fuzzy matches above threshold."""
    if not s1 or not s2:
        return False
    return SequenceMatcher(None, s1, s2).ratio() >= threshold


# =====================================================================
# RICHNESS SCORING
# =====================================================================

def richness_score(job_dict):
    """Score how 'rich' a job listing is (more data = higher score)."""
    score = 0
    if job_dict.get("description"):
        score += min(len(job_dict["description"]), 5000) / 100  # Up to 50 points for description length
    if job_dict.get("salary_range"):
        score += 20
    if job_dict.get("posted_date"):
        score += 10
    if job_dict.get("easy_apply"):
        score += 15
    if job_dict.get("ats_platform"):
        score += 5
    if job_dict.get("job_type"):
        score += 5
    if job_dict.get("url"):
        score += 5
    return score


# =====================================================================
# DEDUPLICATION ENGINE
# =====================================================================

class DeduplicationEngine:
    """Deduplicate jobs across multiple board sources."""

    def __init__(self, title_threshold=0.85, company_threshold=0.80):
        self.title_threshold = title_threshold
        self.company_threshold = company_threshold
        self.stats = {
            "total_input": 0,
            "duplicates_found": 0,
            "unique_output": 0,
            "cross_board_merges": 0,
        }

    def deduplicate(self, jobs):
        """Deduplicate a list of job dicts.

        Args:
            jobs: List of RawJob.to_dict() or similar dicts

        Returns:
            List of deduplicated job dicts with added 'sources' field
        """
        self.stats["total_input"] = len(jobs)
        if not jobs:
            return []

        # Phase 1: Exact URL dedup
        url_groups = defaultdict(list)
        no_url = []
        for job in jobs:
            norm_url = normalize_url(job.get("url", ""))
            if norm_url:
                url_groups[norm_url].append(job)
            else:
                no_url.append(job)

        # Merge URL groups
        merged = []
        for url, group in url_groups.items():
            merged.append(self._merge_group(group))

        # Phase 2: Fuzzy title + company dedup on remaining
        all_candidates = merged + no_url
        clusters = []
        used = set()

        for i, job_a in enumerate(all_candidates):
            if i in used:
                continue

            cluster = [job_a]
            used.add(i)
            norm_title_a = normalize_title(job_a.get("title", ""))
            norm_company_a = normalize_company(job_a.get("company", ""))

            for j, job_b in enumerate(all_candidates):
                if j in used or j <= i:
                    continue

                norm_title_b = normalize_title(job_b.get("title", ""))
                norm_company_b = normalize_company(job_b.get("company", ""))

                # Match if both title and company are similar
                title_match = fuzzy_match(norm_title_a, norm_title_b, self.title_threshold)
                company_match = fuzzy_match(norm_company_a, norm_company_b, self.company_threshold)

                if title_match and company_match:
                    cluster.append(job_b)
                    used.add(j)
                    if job_a.get("board_source") != job_b.get("board_source"):
                        self.stats["cross_board_merges"] += 1

            clusters.append(cluster)

        # Merge each cluster
        result = []
        for cluster in clusters:
            if len(cluster) == 1:
                job = cluster[0]
                job["sources"] = [job.get("board_source", "unknown")]
                result.append(job)
            else:
                merged_job = self._merge_group(cluster)
                result.append(merged_job)
                self.stats["duplicates_found"] += len(cluster) - 1

        self.stats["unique_output"] = len(result)

        print(f"Dedup: {self.stats['total_input']} input → {self.stats['unique_output']} unique "
              f"({self.stats['duplicates_found']} duplicates, {self.stats['cross_board_merges']} cross-board merges)")

        return result

    def _merge_group(self, group):
        """Merge a group of duplicate jobs, keeping the richest listing."""
        if len(group) == 1:
            job = group[0]
            job["sources"] = [job.get("board_source", "unknown")]
            return job

        # Sort by richness, pick the best
        group.sort(key=lambda j: richness_score(j), reverse=True)
        best = {**group[0]}

        # Collect all sources
        sources = list(set(j.get("board_source", "unknown") for j in group))
        best["sources"] = sources

        # Fill in missing fields from other listings
        for job in group[1:]:
            if not best.get("description") and job.get("description"):
                best["description"] = job["description"]
            if not best.get("salary_range") and job.get("salary_range"):
                best["salary_range"] = job["salary_range"]
            if not best.get("posted_date") and job.get("posted_date"):
                best["posted_date"] = job["posted_date"]
            if not best.get("ats_platform") and job.get("ats_platform"):
                best["ats_platform"] = job["ats_platform"]
            if not best.get("job_type") and job.get("job_type"):
                best["job_type"] = job["job_type"]
            # Prefer easy_apply = True
            if job.get("easy_apply"):
                best["easy_apply"] = True
                if job.get("url"):
                    best["easy_apply_url"] = job["url"]

        # Collect all URLs
        best["all_urls"] = list(set(j.get("url", "") for j in group if j.get("url")))

        return best

    def get_stats(self):
        """Return dedup statistics."""
        return {**self.stats}


def deduplicate_jobs(jobs, title_threshold=0.85, company_threshold=0.80):
    """Convenience function for quick deduplication."""
    engine = DeduplicationEngine(title_threshold, company_threshold)
    return engine.deduplicate(jobs)
