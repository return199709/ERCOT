"""Authenticated ERCOT clients built from .env.

Credential values are never logged, printed, or included in exception
messages -- only variable *names* are ever surfaced.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

REQUIRED_VARS = (
    "ERCOT_API_USERNAME",
    "ERCOT_API_PASSWORD",
    "ERCOT_PUBLIC_API_SUBSCRIPTION_KEY",
)

# Be gentler than the library default (0.2s) to stay well clear of throttling
# during long backfills.
DEFAULT_SLEEP_SECONDS = 0.5
DEFAULT_MAX_RETRIES = 5


class MissingCredentialsError(RuntimeError):
    """Raised when .env is absent or incomplete. Names only, never values."""


def load_credentials() -> None:
    """Load .env and verify the required variables are set and non-empty."""
    load_dotenv()
    missing = [name for name in REQUIRED_VARS if not os.getenv(name)]
    if missing:
        raise MissingCredentialsError(
            "Missing or empty ERCOT credentials: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill it in. "
            "Do not put real values in .env.example -- it is tracked by git."
        )


def get_ercot_api(
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
):
    """Return an authenticated ErcotAPI client.

    Note the import path: gridstatus does not re-export ErcotAPI at the
    package top level, despite what some docs imply.
    """
    from gridstatus.ercot_api.ercot_api import ErcotAPI

    load_credentials()
    return ErcotAPI(sleep_seconds=sleep_seconds, max_retries=max_retries)


def get_ercot():
    """Return the public-report Ercot client (system load, SP mapping).

    This one reads ERCOT's public MIS reports and needs no credentials, but
    it does need outbound access to www.ercot.com.
    """
    from gridstatus import Ercot

    return Ercot()
