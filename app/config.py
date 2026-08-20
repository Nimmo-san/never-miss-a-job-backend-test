"""
Central place to read configuration from the environment.

Loaded once via python-dotenv so both `uvicorn app.main:app` and any ad-hoc
script/test importing `app.config` pick up values from a local `.env` file
without every module needing its own `load_dotenv()` call.
"""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("never_miss_a_job.config")


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Ignoring non-integer %s=%r, using default %s", name, raw, default)
        return default


# --- Numbers -----------------------------------------------------------
# v1 SIMPLIFICATION: one tradesperson, configured via a single env var.
# TODO (before onboarding a 2nd client): replace this with per-client config,
# e.g. a small `clients` table keyed by the dedicated Twilio number Twilio
# reports in the webhook's "To" field, so each dedicated number routes to a
# different tradesperson instead of everything pointing at one global number.
TRADESPERSON_NUMBER = os.getenv("TRADESPERSON_NUMBER", "")

# The dedicated "Never Miss a Job" Twilio number. Used as the caller ID when
# dialling the tradesperson, so it never looks like a call from a stranger.
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER", "")

# --- Call handling -------------------------------------------------------
# Ring timeout before Twilio treats the dial as unanswered. ~15-20s (4-5
# rings) is a reasonable default -- tunable, not a fixed requirement.
RING_TIMEOUT_SECONDS = _get_int("RING_TIMEOUT_SECONDS", 20)

# --- Copy (all tunable, not fixed requirements) ---------------------------
WHISPER_MESSAGE = os.getenv(
    "WHISPER_MESSAGE",
    "You have a tracked business enquiry call from Never Miss a Job. Connecting you now.",
)
MISSED_CALL_CALLER_MESSAGE = os.getenv(
    "MISSED_CALL_CALLER_MESSAGE",
    "Sorry, we can't take your call right now. We've logged your call and will be in touch shortly.",
)
SMS_PLACEHOLDER_REPLY = os.getenv(
    "SMS_PLACEHOLDER_REPLY",
    "Thanks for your message. We've received it and will get back to you shortly.",
)

# --- Storage ---------------------------------------------------------------
DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/app.db")

if not TRADESPERSON_NUMBER:
    logger.warning(
        "TRADESPERSON_NUMBER is not set -- inbound calls will be logged but "
        "cannot be dialled out until it's configured in .env"
    )
