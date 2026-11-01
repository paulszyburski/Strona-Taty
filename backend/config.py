import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def enabled(name):
    return bool(os.environ.get(name, "").strip())


def require(names, integration):
    missing = [name for name in names if not enabled(name)]
    if missing:
        raise RuntimeError(f"{integration} configuration missing: {', '.join(missing)}")


def email_enabled():
    return enabled("SMTP_HOST") or enabled("STAFF_EMAILS")


def sms_enabled():
    return enabled("STAFF_SMS")


def calendar_enabled():
    return enabled("GOOGLE_CALENDAR_ID") or enabled("GOOGLE_SERVICE_ACCOUNT_FILE")
