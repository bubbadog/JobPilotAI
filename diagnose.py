#!/usr/bin/env python3
"""Quick diagnostic — run this to find out why discovery returns 0 jobs."""

import sys, os
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

print("=" * 60)
print("JobPilotAI DIAGNOSTICS")
print("=" * 60)

# 1. Check .env file
print("\n[1] .env file")
env_file = SCRIPT_DIR / ".env"
if env_file.exists():
    lines = env_file.read_text().splitlines()
    for line in lines:
        if "=" in line and not line.startswith("#"):
            key = line.split("=", 1)[0].strip()
            val = line.split("=", 1)[1].strip()
            if val:
                print(f"  {key} = SET ({len(val)} chars)")
            else:
                print(f"  {key} = EMPTY")
else:
    print("  ❌ .env file NOT FOUND at", env_file)

# 2. Load env vars manually (like brave_search.py does)
print("\n[2] API key loading")
brave_key = os.environ.get("BRAVE_API_KEY", "")
if not brave_key and env_file.exists():
    for line in env_file.read_text().splitlines():
        if line.startswith("BRAVE_API_KEY="):
            brave_key = line.split("=", 1)[1].strip().strip('"').strip("'")
print(f"  BRAVE_API_KEY: {'SET (' + str(len(brave_key)) + ' chars)' if brave_key else 'NOT SET ❌'}")

# 3. Check config
print("\n[3] Config loading")
try:
    from config_manager import ConfigManager
    cm = ConfigManager(str(SCRIPT_DIR))
    kw = cm.get_keywords()
    loc = cm.get_locations()
    boards = cm.get_enabled_boards()
    print(f"  Keywords: {len(kw)} — {kw[:3]}...")
    print(f"  Locations: {len(loc)} — {loc[:3]}...")
    print(f"  Enabled boards: {[b['name'] for b in boards]}")
except Exception as e:
    print(f"  ❌ Config error: {e}")

# 4. Check modules
print("\n[4] Required modules")
for mod in ["requests", "playwright", "feedparser"]:
    try:
        __import__(mod)
        print(f"  {mod}: ✅ installed")
    except ImportError:
        print(f"  {mod}: ❌ NOT installed")

# 5. Test Brave Search API
print("\n[5] Brave Search API test")
if brave_key:
    try:
        import requests
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": brave_key,
        }
        params = {"q": "Product Manager jobs San Francisco hiring 2026", "count": 5}
        resp = requests.get("https://api.search.brave.com/res/v1/web/search",
                           headers=headers, params=params, timeout=15)
        print(f"  HTTP status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("web", {}).get("results", [])
            print(f"  Results: {len(results)}")
            for r in results[:3]:
                print(f"    - {r.get('title', '')[:60]}")
            if results:
                print("  ✅ Brave Search is working!")
            else:
                print("  ⚠ Got 200 but no results")
        elif resp.status_code == 401:
            print("  ❌ API key is INVALID (401 Unauthorized)")
        elif resp.status_code == 429:
            print("  ⚠ Rate limited (429) — try again in a minute")
        else:
            print(f"  ❌ Unexpected status: {resp.text[:200]}")
    except Exception as e:
        print(f"  ❌ Connection error: {e}")
else:
    print("  ⏭ Skipped (no API key)")

# 6. Test TheMuse Free API
print("\n[6] TheMuse Free API test")
try:
    import requests
    resp = requests.get("https://www.themuse.com/api/public/jobs?page=0&category=Product",
                       timeout=15)
    print(f"  HTTP status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        results = data.get("results", [])
        print(f"  Results: {len(results)}")
        for j in results[:3]:
            print(f"    - {j.get('name', '')} at {j.get('company', {}).get('name', '')}")
        if results:
            print("  ✅ TheMuse is working!")
    else:
        print(f"  ❌ Error: {resp.text[:200]}")
except Exception as e:
    print(f"  ❌ Connection error: {e}")

# 7. Check if discovery engine sees the API scrapers
print("\n[7] Discovery engine check")
try:
    from job_discovery import SCRAPER_CLASSES
    api_scrapers = ["brave_jobs", "themuse_free"]
    for name in api_scrapers:
        if name in SCRAPER_CLASSES:
            print(f"  {name}: ✅ registered in SCRAPER_CLASSES")
        else:
            print(f"  {name}: ❌ NOT in SCRAPER_CLASSES — you have an OLD version of job_discovery.py!")
except Exception as e:
    print(f"  ❌ Import error: {e}")

# 8. Check Brave Search module
print("\n[8] brave_search.py module")
try:
    from brave_search import BraveSearch, get_searcher
    bs = get_searcher(str(SCRIPT_DIR))
    print(f"  Module imported: ✅")
    print(f"  Enabled: {bs.enabled}")
    print(f"  Has key: {bool(bs.api_key)}")
except ImportError:
    print("  ❌ brave_search.py NOT FOUND — you have an OLD version!")
except Exception as e:
    print(f"  ❌ Error: {e}")

print("\n" + "=" * 60)
print("DIAGNOSIS COMPLETE")
print("=" * 60)
