#!/usr/bin/env python3
"""
JobPilotAI — Security Module

Central security utilities used by all modules. Provides input sanitization,
path validation, secret management, and safe logging.

IMPORTANT: This module must have ZERO external dependencies beyond the
Python standard library so it can be imported by any other module safely.
"""

import html
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# XSS / HTML Sanitization
# ---------------------------------------------------------------------------

def sanitize_html(text: str) -> str:
    """Escape HTML entities to prevent XSS injection.

    Use this on ANY user-supplied string before rendering in HTML context.
    """
    if not isinstance(text, str):
        text = str(text)
    return html.escape(text, quote=True)


def strip_html_tags(text: str) -> str:
    """Remove all HTML tags from a string, keeping only text content."""
    if not isinstance(text, str):
        return str(text)
    return re.sub(r'<[^>]+>', '', text)


# ---------------------------------------------------------------------------
# Path Traversal Prevention
# ---------------------------------------------------------------------------

def validate_file_path(path: str, base_dir: str = None, must_exist: bool = False) -> Path:
    """Validate a file path is within the allowed base directory.

    Prevents path traversal attacks (e.g., '../../etc/passwd').

    Args:
        path: The file path to validate.
        base_dir: The allowed base directory. Defaults to current working dir.
        must_exist: If True, raises ValueError if the file doesn't exist.

    Returns:
        Resolved Path object.

    Raises:
        ValueError: If path escapes base_dir or fails validation.
    """
    if not path or not isinstance(path, str):
        raise ValueError("File path must be a non-empty string")

    base = Path(base_dir or ".").resolve()
    resolved = (base / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()

    # Check path is within base directory
    try:
        resolved.relative_to(base)
    except ValueError:
        raise ValueError(
            f"Path '{path}' resolves outside allowed directory '{base}'. "
            "This may be a path traversal attempt."
        )

    if must_exist and not resolved.exists():
        raise ValueError(f"File does not exist: {resolved}")

    return resolved


def sanitize_filename(name: str, max_length: int = 100) -> str:
    """Sanitize a string for safe use as a filename.

    Removes path separators, null bytes, and other dangerous characters.
    Used for screenshot filenames, export files, etc.

    Args:
        name: The raw filename or component (e.g., company name).
        max_length: Maximum allowed filename length.

    Returns:
        Safe filename string.
    """
    if not isinstance(name, str):
        name = str(name)

    # Normalize unicode
    name = unicodedata.normalize('NFKD', name)

    # Remove null bytes
    name = name.replace('\x00', '')

    # Replace path separators and other dangerous chars
    name = re.sub(r'[/\\:*?"<>|;\n\r\t]', '_', name)

    # Remove leading dots (hidden files) and spaces
    name = name.lstrip('. ')

    # Collapse multiple underscores
    name = re.sub(r'_+', '_', name)

    # Truncate
    name = name[:max_length].rstrip('_. ')

    return name or "unnamed"


# ---------------------------------------------------------------------------
# URL Validation
# ---------------------------------------------------------------------------

def validate_url(url: str, require_https: bool = False) -> str:
    """Validate and normalize a URL.

    Args:
        url: The URL to validate.
        require_https: If True, reject non-HTTPS URLs.

    Returns:
        The validated URL string.

    Raises:
        ValueError: If URL is malformed or violates policy.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string")

    url = url.strip()

    parsed = urlparse(url)

    if not parsed.scheme:
        url = f"https://{url}"
        parsed = urlparse(url)

    if parsed.scheme not in ('http', 'https'):
        raise ValueError(f"Invalid URL scheme: {parsed.scheme}")

    if require_https and parsed.scheme != 'https':
        raise ValueError(f"HTTPS required, got: {parsed.scheme}")

    if not parsed.netloc:
        raise ValueError(f"Invalid URL (no host): {url}")

    # Reject URLs with credentials embedded
    if parsed.username or parsed.password:
        raise ValueError("URLs must not contain embedded credentials")

    return url


# ---------------------------------------------------------------------------
# Secret Management
# ---------------------------------------------------------------------------

def load_secret(key: str, fallback: str = None) -> str:
    """Load a secret from environment variables.

    NEVER loads secrets from JSON config files. All secrets must come from
    environment variables (typically via .env file loaded by python-dotenv).

    Args:
        key: The environment variable name (e.g., 'SMTP_PASS').
        fallback: Default value if env var is not set. Use None to require it.

    Returns:
        The secret value.

    Raises:
        EnvironmentError: If key is required (no fallback) and not set.
    """
    value = os.environ.get(key)
    if value is not None:
        return value
    if fallback is not None:
        return fallback
    raise EnvironmentError(
        f"Required secret '{key}' not found in environment variables. "
        f"Set it in your .env file or export it: export {key}=your_value"
    )


def mask_credential(value: str, visible_chars: int = 4) -> str:
    """Mask a credential for safe logging.

    Example: 'my_secret_password' → 'my_s***'

    Args:
        value: The credential to mask.
        visible_chars: How many leading characters to show.

    Returns:
        Masked string safe for logging.
    """
    if not value or not isinstance(value, str):
        return "[EMPTY]"
    if len(value) <= visible_chars:
        return "***"
    return value[:visible_chars] + "***"


# ---------------------------------------------------------------------------
# Input Validation Helpers
# ---------------------------------------------------------------------------

_EMAIL_PATTERN = re.compile(
    r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
)

_PHONE_PATTERNS = [
    re.compile(r'^\+?\d{1,4}[\s.-]?\(?\d{1,4}\)?[\s.-]?\d{1,4}[\s.-]?\d{1,9}$'),  # International
    re.compile(r'^\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}$'),  # US/CA
]


def validate_email(email: str) -> bool:
    """Validate email format."""
    return bool(_EMAIL_PATTERN.match(email.strip())) if email else False


def validate_phone(phone: str) -> bool:
    """Validate phone number format (US and international)."""
    if not phone:
        return False
    phone = phone.strip()
    return any(p.match(phone) for p in _PHONE_PATTERNS)


def sanitize_log_message(message: str) -> str:
    """Remove potential credential leaks from log messages.

    Redacts patterns that look like secrets (password=..., token=..., etc.)
    """
    if not isinstance(message, str):
        return str(message)

    # Redact key=value patterns for sensitive keys
    sensitive_keys = r'(?:password|passwd|secret|token|api[_-]?key|credentials?|auth)'
    message = re.sub(
        rf'({sensitive_keys})\s*[=:]\s*["\']?[^\s"\'&]+["\']?',
        r'\1=[REDACTED]',
        message,
        flags=re.IGNORECASE
    )

    # Redact Bearer tokens
    message = re.sub(
        r'Bearer\s+[A-Za-z0-9._-]+',
        'Bearer [REDACTED]',
        message
    )

    return message
