#!/usr/bin/env python3
"""
Form Filler — ATS platform detection and intelligent form field mapping.
Detects Greenhouse, Lever, Workday, iCIMS, Taleo, SmartRecruiters, BrassRing
and fills application forms using resume profile + Q&A bank.
"""

import re
import asyncio
from pathlib import Path
from datetime import datetime

try:
    from playwright.async_api import Page, Locator, TimeoutError as PlaywrightTimeout
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

from qa_bank import QABank
from resume_parser import load_profile

SCRIPT_DIR = Path(__file__).parent

# =====================================================================
# ATS DETECTION
# =====================================================================

ATS_PATTERNS = {
    "greenhouse": {
        "url_patterns": ["boards.greenhouse.io", "greenhouse.io/"],
        "dom_signals": ["#application_form", "[data-source='greenhouse']", ".greenhouse-application"],
        "field_map": {
            "first_name": "#first_name",
            "last_name": "#last_name",
            "email": "#email",
            "phone": "#phone",
            "resume": "input[type='file'][name*='resume'], input[type='file'][id*='resume']",
            "cover_letter": "input[type='file'][name*='cover'], textarea[name*='cover']",
            "linkedin": "input[name*='linkedin'], input[id*='linkedin']",
            "website": "input[name*='website'], input[id*='portfolio']",
            "location": "input[name*='location'], #location",
            "submit": "input[type='submit'], button[type='submit']",
        }
    },
    "lever": {
        "url_patterns": ["jobs.lever.co"],
        "dom_signals": [".application-form", ".lever-application-form", "[data-qa='application-form']"],
        "field_map": {
            "full_name": "input[name='name'], input[name='fullName']",
            "email": "input[name='email']",
            "phone": "input[name='phone']",
            "resume": "input[type='file']",
            "linkedin": "input[name*='linkedin'], input[name='urls[LinkedIn]']",
            "website": "input[name*='website'], input[name='urls[Portfolio]']",
            "current_company": "input[name='org']",
            "submit": "button[type='submit'], .postings-btn-submit",
        }
    },
    "workday": {
        "url_patterns": ["myworkdayjobs.com", ".wd5.myworkdayjobs.com", "workday.com/en-US/"],
        "dom_signals": ["[data-automation-id]", ".css-1dbjc4n", "[data-uxi-widget-type]"],
        "multi_step": True,
        "field_map": {
            "email": "[data-automation-id='email'] input, input[aria-label*='Email']",
            "first_name": "[data-automation-id='legalNameSection_firstName'] input",
            "last_name": "[data-automation-id='legalNameSection_lastName'] input",
            "phone": "[data-automation-id='phone'] input, input[aria-label*='Phone']",
            "resume": "input[type='file'], [data-automation-id='file-upload-input-ref']",
            "country": "[data-automation-id='countryDropdown']",
            "next_btn": "[data-automation-id='bottom-navigation-next-button'], button[aria-label='Next']",
            "submit": "[data-automation-id='bottom-navigation-next-button']",
        }
    },
    "icims": {
        "url_patterns": ["icims.com", ".icims.com"],
        "dom_signals": ["#iCIMS_MainWrapper", ".iCIMS_JobsTable", "[class*='icims']"],
        "field_map": {
            "first_name": "#firstName, input[name='firstName']",
            "last_name": "#lastName, input[name='lastName']",
            "email": "#email, input[name='email']",
            "phone": "#phone, input[name='phone']",
            "resume": "input[type='file']",
            "submit": "#submit, button[type='submit']",
        }
    },
    "taleo": {
        "url_patterns": ["taleo.net"],
        "dom_signals": ["#requisitionDescriptionInterface", ".taleo-form", "#ftlform"],
        "field_map": {
            "first_name": "input[id*='FirstName'], input[name*='firstName']",
            "last_name": "input[id*='LastName'], input[name*='lastName']",
            "email": "input[id*='Email'], input[name*='email']",
            "phone": "input[id*='Phone'], input[name*='phone']",
            "resume": "input[type='file']",
            "submit": "input[type='submit'], button.submit",
        }
    },
    "smartrecruiters": {
        "url_patterns": ["smartrecruiters.com", "jobs.smartrecruiters.com"],
        "dom_signals": [".smart-application", "[data-test='application-form']"],
        "field_map": {
            "first_name": "input[name='firstName']",
            "last_name": "input[name='lastName']",
            "email": "input[name='email']",
            "phone": "input[name='phoneNumber']",
            "resume": "input[type='file']",
            "linkedin": "input[name*='linkedin']",
            "submit": "button[type='submit']",
        }
    },
    "ashby": {
        "url_patterns": ["ashbyhq.com", "jobs.ashbyhq.com"],
        "dom_signals": ["[class*='ashby']", ".ashby-application-form"],
        "field_map": {
            "first_name": "input[name='_systemfield_name']",
            "email": "input[name='_systemfield_email']",
            "phone": "input[name='_systemfield_phone']",
            "resume": "input[type='file']",
            "linkedin": "input[name*='linkedin']",
            "submit": "button[type='submit']",
        }
    },
    "brassring": {
        "url_patterns": ["brassring.com"],
        "dom_signals": ["#PB_Container", ".PB_Content"],
        "field_map": {
            "first_name": "input[id*='FirstName']",
            "last_name": "input[id*='LastName']",
            "email": "input[id*='Email']",
            "phone": "input[id*='Phone']",
            "resume": "input[type='file']",
            "submit": "input[type='submit']",
        }
    },
}

# Field labels that map to resume profile fields
LABEL_TO_PROFILE = {
    "first name": "first_name",
    "last name": "last_name",
    "full name": "full_name",
    "email": "email",
    "phone": "phone",
    "linkedin": "linkedin",
    "website": "website",
    "city": "city",
    "state": "state",
    "zip": "zip_code",
    "address": "address",
    "current company": "current_company",
    "current title": "current_title",
}


class FormFiller:
    """Intelligent form filler with ATS detection."""

    def __init__(self, config_dir=None):
        self.config_dir = Path(config_dir) if config_dir else SCRIPT_DIR
        self.qa_bank = QABank(self.config_dir)
        self.profile = load_profile(self.config_dir) or {}
        self.resume_path = self._find_resume()
        self.fill_log = []

    def _find_resume(self):
        """Find the resume file to upload."""
        for ext in ["pdf", "docx", "doc"]:
            for pattern in [f"resume*.{ext}", f"Resume*.{ext}", f"*resume*.{ext}", f"*Resume*.{ext}"]:
                matches = list(self.config_dir.glob(pattern))
                if matches:
                    return matches[0]
        return None

    def detect_ats(self, url):
        """Detect which ATS platform a URL belongs to."""
        if not url:
            return None, None

        url_lower = url.lower()
        for ats_name, ats_config in ATS_PATTERNS.items():
            for pattern in ats_config.get("url_patterns", []):
                if pattern in url_lower:
                    return ats_name, ats_config

        return None, None

    async def detect_ats_from_page(self, page):
        """Detect ATS from page DOM if URL detection fails."""
        for ats_name, ats_config in ATS_PATTERNS.items():
            for signal in ats_config.get("dom_signals", []):
                try:
                    el = page.locator(signal)
                    if await el.count() > 0:
                        return ats_name, ats_config
                except Exception:
                    continue
        return None, None

    async def fill_application(self, page, job_context, dry_run=False,
                               resume_variant_id=None, cover_letter_variant_id=None):
        """Fill an application form on the current page.

        Args:
            page: Playwright Page object on the application form
            job_context: Dict with job details (title, company, etc.)
            dry_run: If True, fill but don't submit
            resume_variant_id: v4.1 A/B — which resume variant to use (optional)
            cover_letter_variant_id: v4.1 A/B — which CL variant to use (optional)

        Returns:
            Dict with fill results: fields_filled, fields_skipped, errors, screenshot_path
        """
        result = {
            "fields_filled": [],
            "fields_skipped": [],
            "errors": [],
            "ats_detected": None,
            "screenshot_path": None,
            "submitted": False,
            "resume_variant_used": resume_variant_id or "",
            "cl_variant_used": cover_letter_variant_id or "",
        }

        # v4.1: Resolve variant file paths if provided
        self._active_resume_path = None
        self._active_cl_text = None
        if resume_variant_id or cover_letter_variant_id:
            try:
                from material_manager import MaterialManager
                from security import validate_file_path
                mat_mgr = MaterialManager(self.config_dir)
                if resume_variant_id:
                    rv = mat_mgr.get_resume_variant(resume_variant_id)
                    if rv and rv.get("file_path"):
                        try:
                            validated = validate_file_path(rv["file_path"], str(self.config_dir))
                            self._active_resume_path = str(validated)
                        except ValueError:
                            pass  # Invalid path — skip variant, use default resume
                if cover_letter_variant_id:
                    cv = mat_mgr.get_cover_letter_variant(cover_letter_variant_id)
                    if cv and cv.get("template_text"):
                        self._active_cl_text = cv["template_text"]
            except ImportError:
                pass  # material_manager not available

        # Detect ATS
        url = page.url
        ats_name, ats_config = self.detect_ats(url)
        if not ats_config:
            ats_name, ats_config = await self.detect_ats_from_page(page)

        result["ats_detected"] = ats_name or "unknown"

        if ats_config:
            # Use ATS-specific field mapping
            await self._fill_ats_fields(page, ats_config, job_context, result)
        else:
            # Generic form filling: find all input fields and try to fill them
            await self._fill_generic_fields(page, job_context, result)

        # Handle custom questions (textareas, additional fields)
        await self._fill_custom_questions(page, job_context, result)

        # Upload resume if file input found (uses variant path if set)
        await self._upload_resume(page, result)

        # Take screenshot before submit
        if not dry_run:
            screenshot_dir = self.config_dir / "screenshots"
            screenshot_dir.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            try:
                from security import sanitize_filename
                company = sanitize_filename(job_context.get("company", "unknown"))
            except ImportError:
                company = re.sub(r'[^\w]', '_', job_context.get("company", "unknown"))
            screenshot_path = screenshot_dir / f"app_{company}_{ts}.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)
            result["screenshot_path"] = str(screenshot_path)

        return result

    async def _fill_ats_fields(self, page, ats_config, job_context, result):
        """Fill fields using ATS-specific selectors."""
        field_map = ats_config.get("field_map", {})
        profile_data = self._get_profile_data(job_context)

        for field_name, selector in field_map.items():
            if field_name in ("submit", "next_btn", "resume", "cover_letter"):
                continue

            value = profile_data.get(field_name, "")
            if not value:
                result["fields_skipped"].append(field_name)
                continue

            try:
                el = page.locator(selector).first
                if await el.is_visible():
                    await el.fill(str(value))
                    result["fields_filled"].append({"field": field_name, "value": str(value)[:50]})
                    self.fill_log.append(f"Filled {field_name}: {str(value)[:50]}")
                else:
                    result["fields_skipped"].append(field_name)
            except Exception as e:
                result["errors"].append({"field": field_name, "error": str(e)[:100]})

    async def _fill_generic_fields(self, page, job_context, result):
        """Fill fields using generic label detection."""
        profile_data = self._get_profile_data(job_context)

        # Find all visible input fields
        inputs = page.locator("input[type='text'], input[type='email'], input[type='tel'], input[type='url'], input[type='number']")
        count = await inputs.count()

        for i in range(count):
            try:
                inp = inputs.nth(i)
                if not await inp.is_visible():
                    continue

                # Get label or placeholder
                label = await self._get_field_label(inp, page)
                if not label:
                    continue

                # Match label to profile field
                value = self._match_label_to_value(label, profile_data, job_context)
                if value:
                    await inp.fill(str(value))
                    result["fields_filled"].append({"field": label, "value": str(value)[:50]})
                else:
                    result["fields_skipped"].append(label)
            except Exception:
                continue

    async def _fill_custom_questions(self, page, job_context, result):
        """Fill custom question fields using Q&A bank."""
        # Find textareas and labeled question sections
        textareas = page.locator("textarea:visible")
        count = await textareas.count()

        for i in range(count):
            try:
                ta = textareas.nth(i)
                label = await self._get_field_label(ta, page)
                if not label:
                    continue

                # Check Q&A bank
                qa_result = self.qa_bank.get_answer(label, job_context)
                if qa_result and qa_result["confidence"] >= 0.4:
                    await ta.fill(qa_result["answer"])
                    result["fields_filled"].append({
                        "field": label[:50],
                        "value": qa_result["answer"][:50] + "...",
                        "confidence": qa_result["confidence"],
                    })
                else:
                    result["fields_skipped"].append(f"Q: {label[:50]}")
            except Exception:
                continue

        # Handle select/dropdown fields
        selects = page.locator("select:visible")
        count = await selects.count()

        for i in range(count):
            try:
                sel = selects.nth(i)
                label = await self._get_field_label(sel, page)
                if not label:
                    continue

                qa_result = self.qa_bank.get_answer(label, job_context)
                if qa_result and qa_result["confidence"] >= 0.4:
                    # Try to select by visible text
                    try:
                        await sel.select_option(label=qa_result["answer"])
                        result["fields_filled"].append({"field": label[:50], "value": qa_result["answer"][:50]})
                    except Exception:
                        # Try by value
                        try:
                            await sel.select_option(value=qa_result["answer"])
                            result["fields_filled"].append({"field": label[:50], "value": qa_result["answer"][:50]})
                        except Exception:
                            result["fields_skipped"].append(f"Select: {label[:50]}")
            except Exception:
                continue

    async def _upload_resume(self, page, result):
        """Upload resume to file input."""
        if not self.resume_path or not self.resume_path.exists():
            result["errors"].append({"field": "resume", "error": "No resume file found"})
            return

        file_inputs = page.locator("input[type='file']")
        count = await file_inputs.count()

        for i in range(count):
            try:
                fi = file_inputs.nth(i)
                label = await self._get_field_label(fi, page)
                label_lower = (label or "").lower()

                # Is this a resume upload or cover letter?
                if any(w in label_lower for w in ["resume", "cv", "upload"]):
                    await fi.set_input_files(str(self.resume_path))
                    result["fields_filled"].append({"field": "resume", "value": self.resume_path.name})
                    break
            except Exception as e:
                result["errors"].append({"field": "resume_upload", "error": str(e)[:100]})

    async def _get_field_label(self, element, page):
        """Get the label text for a form field."""
        try:
            # Check aria-label
            aria = await element.get_attribute("aria-label")
            if aria:
                return aria

            # Check placeholder
            placeholder = await element.get_attribute("placeholder")
            if placeholder:
                return placeholder

            # Check associated label via id
            el_id = await element.get_attribute("id")
            if el_id:
                label = page.locator(f"label[for='{el_id}']")
                if await label.count() > 0:
                    return await label.first.inner_text()

            # Check parent label
            parent_label = element.locator("xpath=ancestor::label")
            if await parent_label.count() > 0:
                return await parent_label.first.inner_text()

            # Check nearby label (sibling or parent child)
            name = await element.get_attribute("name")
            if name:
                return name.replace("_", " ").replace("-", " ").title()

        except Exception:
            pass
        return ""

    def _get_profile_data(self, job_context=None):
        """Build a flat dict of field values from profile."""
        contact = self.profile.get("contact", {})
        name_parts = (contact.get("name") or "").split()

        data = {
            "first_name": name_parts[0] if name_parts else "",
            "last_name": name_parts[-1] if len(name_parts) > 1 else "",
            "full_name": contact.get("name", ""),
            "email": contact.get("email", ""),
            "phone": contact.get("phone", ""),
            "linkedin": contact.get("linkedin", ""),
            "website": contact.get("website", ""),
            "location": contact.get("location", ""),
            "city": "",
            "state": "",
            "zip_code": "",
            "current_company": "",
            "current_title": "",
        }

        # Parse location into parts
        loc = contact.get("location", "")
        if "," in loc:
            parts = loc.split(",")
            data["city"] = parts[0].strip()
            data["state"] = parts[1].strip() if len(parts) > 1 else ""

        # Get current role from experience
        exp = self.profile.get("experience", [])
        if exp:
            first_exp = exp[0] if isinstance(exp[0], dict) else {}
            data["current_company"] = first_exp.get("company", "")
            data["current_title"] = first_exp.get("title", "")

        return data

    def _match_label_to_value(self, label, profile_data, job_context):
        """Match a field label to the appropriate value."""
        label_lower = label.lower().strip()

        # Direct mapping
        for pattern, field in LABEL_TO_PROFILE.items():
            if pattern in label_lower:
                return profile_data.get(field, "")

        # Check Q&A bank for other questions
        qa_result = self.qa_bank.get_answer(label, job_context)
        if qa_result and qa_result["confidence"] >= 0.5:
            return qa_result["answer"]

        return None
