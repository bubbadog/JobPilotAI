#!/bin/bash
# ============================================================
# JobPilotAI v4.1 — Setup & Bootstrap Script
# ============================================================
# Usage:
#   chmod +x setup.sh && ./setup.sh
#
# What this does:
#   1. Checks Python 3.9+ is installed
#   2. Creates a virtual environment
#   3. Installs all dependencies
#   4. Installs Playwright browsers
#   5. Creates data directories
#   6. Parses your resume (if found)
#   7. Runs a test discovery scan
# ============================================================

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔══════════════════════════════════════════════════╗"
echo "║   JobPilotAI v4.1 — Setup          ║"
echo "║   Mass Discovery & Auto-Apply Engine             ║"
echo "╚══════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── Step 1: Check Python ──
echo -e "${YELLOW}[1/7] Checking Python...${NC}"
if command -v python3 &> /dev/null; then
    PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
    PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 9 ]; then
        echo -e "${GREEN}  ✓ Python $PY_VERSION found${NC}"
    else
        echo -e "${RED}  ✗ Python 3.9+ required (found $PY_VERSION)${NC}"
        echo "  Install from: https://www.python.org/downloads/"
        exit 1
    fi
else
    echo -e "${RED}  ✗ Python 3 not found${NC}"
    echo "  Install from: https://www.python.org/downloads/"
    exit 1
fi

# ── Step 2: Create virtual environment ──
echo -e "${YELLOW}[2/7] Setting up virtual environment...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}  ✓ Virtual environment created${NC}"
else
    echo -e "${GREEN}  ✓ Virtual environment already exists${NC}"
fi

# Activate venv
source venv/bin/activate
echo -e "${GREEN}  ✓ Virtual environment activated${NC}"

# ── Step 3: Install dependencies ──
echo -e "${YELLOW}[3/7] Installing Python dependencies...${NC}"
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo -e "${GREEN}  ✓ All dependencies installed${NC}"

# ── Step 4: Install Playwright browsers ──
echo -e "${YELLOW}[4/7] Installing Playwright Chromium browser...${NC}"
playwright install chromium
echo -e "${GREEN}  ✓ Chromium browser installed${NC}"

# ── Step 5: Create data directories ──
echo -e "${YELLOW}[5/7] Creating data directories...${NC}"
mkdir -p data
mkdir -p data/screenshots
mkdir -p data/exports
mkdir -p logs
echo -e "${GREEN}  ✓ Directories created: data/, data/screenshots/, data/exports/, logs/${NC}"

# ── Step 6: Parse resume (if found) ──
echo -e "${YELLOW}[6/7] Looking for resume...${NC}"
RESUME_FOUND=false
for f in *.pdf *.docx; do
    if [ -f "$f" ] && echo "$f" | grep -iq "resume\|cv"; then
        echo -e "${GREEN}  Found: $f${NC}"
        echo -e "  Parsing resume to build your profile..."
        python3 main.py resume --file "$f" 2>/dev/null && echo -e "${GREEN}  ✓ Resume parsed! Profile saved to resume_profile.json${NC}" || echo -e "${YELLOW}  ⚠ Resume parse had issues — you can retry manually: python main.py resume --file \"$f\"${NC}"
        RESUME_FOUND=true
        break
    fi
done
if [ "$RESUME_FOUND" = false ]; then
    echo -e "${YELLOW}  ⚠ No resume found. Place your resume PDF/DOCX in this folder and run:${NC}"
    echo "     python main.py resume --file your_resume.pdf"
fi

# ── Step 7: Verify installation ──
echo -e "${YELLOW}[7/7] Verifying installation...${NC}"
python3 -c "
import importlib
modules = ['playwright', 'pdfplumber', 'PyPDF2', 'docx', 'schedule']
ok = True
for m in modules:
    try:
        importlib.import_module(m)
        print(f'  ✓ {m}')
    except ImportError:
        print(f'  ✗ {m} — MISSING')
        ok = False
if ok:
    print()
    print('  All dependencies verified!')
"

# ── Done! ──
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Setup complete! Here's what to do next:        ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BLUE}Activate the virtual environment:${NC}"
echo "    source venv/bin/activate"
echo ""
echo -e "  ${BLUE}Run your first discovery scan:${NC}"
echo "    python main.py discover"
echo ""
echo -e "  ${BLUE}Run a full cycle (discover → score → dedup → queue):${NC}"
echo "    python main.py full-cycle --strategy balanced"
echo ""
echo -e "  ${BLUE}Start the background scheduler:${NC}"
echo "    python main.py schedule"
echo ""
echo -e "  ${BLUE}Check status anytime:${NC}"
echo "    python main.py status"
echo ""
echo -e "  ${BLUE}Export for dashboard import:${NC}"
echo "    python main.py export"
echo ""
echo -e "  ${YELLOW}Tip: Open Job_Search_Command_Center.html in your browser,"
echo -e "  then click 'Import Engine Data' to pull in discovered jobs.${NC}"
echo ""
