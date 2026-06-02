"""
Load environment variables from a project-root .env file.
"""

from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_LOADED = False


def load_env() -> None:
    """Load .env from project root; does not override existing env vars."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    from dotenv import load_dotenv

    load_dotenv(_PROJECT_ROOT / ".env")
    _ENV_LOADED = True
