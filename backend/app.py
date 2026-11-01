import base64
import contextlib
import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet

from backend.config import (
    ROOT,
    calendar_enabled,
    email_enabled,
    require,
    sms_enabled,
)

TZ = ZoneInfo("Europe/Warsaw")
DATA = Path(os.environ.get("BOOKING_DATA_DIR", str(ROOT / "private")))
ORIGIN = os.environ.get("PUBLIC_ORIGIN", "").rstrip("/")
LIVE = os.environ.get("BOOKING_MODE", "preview") == "live"


def now():
    return datetime.now(TZ)


def secret():
    key = os.environ.get("BOOKING_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("BOOKING_ENCRYPTION_KEY missing")
    return Fernet(key.encode())


def db():
    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    connection = sqlite3.connect(DATA / "booking.sqlite", timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=15000")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS bookings(
            id TEXT PRIMARY KEY,
            slot TEXT NOT NULL,
            payload BLOB NOT NULL,
            status TEXT NOT NULL,
            created TEXT NOT NULL,
            idem TEXT UNIQUE NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS active_slot
            ON bookings(slot) WHERE status IN ('pending', 'confirmed');
        CREATE TABLE IF NOT EXISTS jobs(
            id INTEGER PRIMARY KEY,
            booking_id TEXT,
            kind TEXT,
            recipient TEXT,
            state TEXT DEFAULT 'pending',
            attempts INTEGER DEFAULT 0,
            retry_at REAL DEFAULT 0,
            UNIQUE(booking_id, kind, recipient)
        );
        CREATE TABLE IF NOT EXISTS rate(
            key TEXT PRIMARY KEY,
            n INTEGER NOT NULL
        );
        """)
    return connection


def allowed_slots(reference=None):
    reference = reference or now()
    first_friday = reference.replace(hour=12, minute=0, second=0, microsecond=0)
    first_friday += timedelta(days=(4 - first_friday.weekday()) % 7)
    if first_friday.date() == reference.date() and reference.hour >= 17:
        first_friday += timedelta(days=7)
    return [
        first_friday.replace(hour=hour) + timedelta(weeks=week)
        for week in range(5)
        for hour in (16, 17)
        if first_friday.replace(hour=hour) + timedelta(weeks=week) > reference
    ]


def http_json(url, data=None, headers=None, method=None):
    body = json.dumps(data).encode() if data is not None else None
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    with urllib.request.urlopen(
        urllib.request.Request(url, data=body, headers=request_headers, method=method),
        timeout=15,
    ) as response:
        return json.load(response)


def google_token():
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    account = json.loads(Path(os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"]).read_text())

    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    issued_at = int(time.time())
    claims = {
        "iss": account["client_email"],
        "scope": "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.freebusy",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": issued_at,
        "exp": issued_at + 3600,
    }
    message = (
        encode(b'{"alg":"RS256","typ":"JWT"}')
        + "."
        + encode(json.dumps(claims).encode())
    )
    key = serialization.load_pem_private_key(
        account["private_key"].encode(), password=None
    )
    assertion = (
        message
        + "."
        + encode(key.sign(message.encode(), padding.PKCS1v15(), hashes.SHA256()))
    )
    body = urllib.parse.urlencode(
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }
    ).encode()
    with urllib.request.urlopen(
        urllib.request.Request("https://oauth2.googleapis.com/token", data=body),
        timeout=15,
    ) as response:
        return json.load(response)["access_token"]


def google_busy():
    if not os.environ.get("GOOGLE_CALENDAR_ID"):
        return []
    slots = allowed_slots()
    if not slots:
        return []
    calendar_id = os.environ["GOOGLE_CALENDAR_ID"]
    response = http_json(
        "https://www.googleapis.com/calendar/v3/freeBusy",
        {
            "timeMin": slots[0].isoformat(),
            "timeMax": (slots[-1] + timedelta(hours=1)).isoformat(),
            "items": [{"id": calendar_id}],
        },
        {"Authorization": "Bearer " + google_token()},
    )
    calendar = response.get("calendars", {}).get(calendar_id, {})
    if "errors" in calendar or "busy" not in calendar:
        raise RuntimeError("Calendar unavailable")
    return [
        (
            datetime.fromisoformat(b["start"].replace("Z", "+00:00")),
            datetime.fromisoformat(b["end"].replace("Z", "+00:00")),
        )
        for b in calendar["busy"]
    ]


def available():
    with contextlib.closing(db()) as c:
        occupied = {
            r[0]
            for r in c.execute(
                "SELECT slot FROM bookings WHERE status IN ('pending','confirmed')"
            )
        }
    busy = google_busy()
    return [
        s
        for s in allowed_slots()
        if s.isoformat() not in occupied
        and not any(s < e and s + timedelta(minutes=30) > b for b, e in busy)
    ]


def config_check():
    local_origins = ("http://127.0.0.1", "http://localhost")
    if not ORIGIN.startswith(("https://", *local_origins)):
        raise RuntimeError("PUBLIC_ORIGIN must use HTTPS")
    secret()
    if email_enabled():
        require(
            [
                "SMTP_HOST",
                "SMTP_USER",
                "SMTP_PASSWORD",
                "SMTP_FROM",
                "STAFF_EMAILS",
            ],
            "Email",
        )
        if os.environ.get("SMTP_TLS_MODE", "starttls") not in ["starttls", "ssl"]:
            raise RuntimeError("SMTP_TLS_MODE must be starttls or ssl")
        if not all(
            re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", address)
            for address in os.environ["STAFF_EMAILS"].split(",")
        ):
            raise RuntimeError("Invalid STAFF_EMAILS address")
    if sms_enabled():
        require(["SMSAPI_TOKEN"], "SMS")
    if calendar_enabled():
        require(
            ["GOOGLE_CALENDAR_ID", "GOOGLE_SERVICE_ACCOUNT_FILE"],
            "Google Calendar",
        )


def book(data, ip):
    if not LIVE:
        raise ValueError("Rezerwacje są wyłączone.")
    config_check()
    if data.get("website"):
        raise ValueError("Nieprawidłowe zgłoszenie.")
    if data.get("terms") is not True:
        raise ValueError("Potwierdź zapoznanie z regulaminem i polityką prywatności.")
    fields = {
        k: str(data.get(k, "")).strip()
        for k in ["name", "email", "phone", "questions", "slot", "request_id"]
    }
    if (
        not 2 <= len(fields["name"]) <= 160
        or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", fields["email"])
        or len(fields["email"]) > 254
    ):
        raise ValueError("Sprawdź imię, nazwisko i e-mail.")
    if (
        not re.fullmatch(r"[+0-9 ()-]{7,30}", fields["phone"])
        or len(fields["questions"]) > 6000
    ):
        raise ValueError("Sprawdź telefon lub skróć pytania.")
    if not re.fullmatch(r"[a-f0-9]{32}", fields["request_id"]):
        raise ValueError("Odśwież stronę i spróbuj ponownie.")
    idem = fields.pop("request_id")
    with contextlib.closing(db()) as c:
        existing = c.execute(
            "SELECT id,payload FROM bookings WHERE idem=?", (idem,)
        ).fetchone()
        if existing:
            old = json.loads(secret().decrypt(existing["payload"]))
            if old != fields:
                raise ValueError("Zmieniono dane zgłoszenia. Odśwież stronę.")
            return existing["id"]
    if fields["slot"] not in {s.isoformat() for s in available()}:
        raise ValueError("Termin nie jest już dostępny. Wybierz inny.")
    ident = secrets.token_hex(12)
    payload = secret().encrypt(json.dumps(fields, ensure_ascii=False).encode())
    with contextlib.closing(db()) as c:
        try:
            c.execute("BEGIN IMMEDIATE")
            ratekey = hmac.new(
                os.environ["BOOKING_ENCRYPTION_KEY"].encode(),
                (ip + "|" + str(int(time.time() // 3600))).encode(),
                hashlib.sha256,
            ).hexdigest()
            c.execute(
                "INSERT INTO rate(key,n) VALUES(?,1) ON CONFLICT(key) DO UPDATE SET n=n+1",
                (ratekey,),
            )
            if (
                c.execute("SELECT n FROM rate WHERE key=?", (ratekey,)).fetchone()[0]
                > 5
            ):
                raise ValueError("Zbyt wiele zgłoszeń. Skontaktuj się z asystentką.")
            c.execute(
                "INSERT INTO bookings VALUES(?,?,?,?,?,?)",
                (ident, fields["slot"], payload, "pending", now().isoformat(), idem),
            )
            if email_enabled():
                for recipient in os.environ["STAFF_EMAILS"].split(","):
                    c.execute(
                        "INSERT INTO jobs(booking_id,kind,recipient) VALUES(?,?,?)",
                        (ident, "staff_email", recipient),
                    )
                c.execute(
                    "INSERT INTO jobs(booking_id,kind,recipient) VALUES(?,?,?)",
                    (ident, "patient_email", fields["email"]),
                )
            for recipient in filter(None, os.environ.get("STAFF_SMS", "").split(",")):
                c.execute(
                    "INSERT INTO jobs(booking_id,kind,recipient) VALUES(?,?,?)",
                    (ident, "sms", recipient),
                )
            if os.environ.get("GOOGLE_CALENDAR_ID"):
                c.execute(
                    "INSERT INTO jobs(booking_id,kind,recipient) VALUES(?,?,?)",
                    (ident, "google", os.environ["GOOGLE_CALENDAR_ID"]),
                )
            c.execute(
                "DELETE FROM rate WHERE rowid NOT IN (SELECT rowid FROM rate ORDER BY rowid DESC LIMIT 10000)"
            )
            c.commit()
        except sqlite3.IntegrityError:
            c.rollback()
            same = c.execute("SELECT id FROM bookings WHERE idem=?", (idem,)).fetchone()
            if same:
                return same["id"]
            raise ValueError("Termin został właśnie zarezerwowany. Wybierz inny.")
    return ident


def send_mail(to, subject, body):
    m = EmailMessage()
    m["From"] = os.environ["SMTP_FROM"]
    m["To"] = to
    m["Subject"] = subject
    m.set_content(body)
    mode = os.environ.get("SMTP_TLS_MODE", "starttls")
    port = int(os.environ.get("SMTP_PORT", "465" if mode == "ssl" else "587"))
    if mode == "ssl":
        s = smtplib.SMTP_SSL(
            os.environ["SMTP_HOST"],
            port,
            timeout=20,
            context=ssl.create_default_context(),
        )
    else:
        s = smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=20)
        s.ehlo()
        s.starttls(context=ssl.create_default_context())
        s.ehlo()
    with s:
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(m)


def deliver(job, b):
    p = json.loads(secret().decrypt(b["payload"]))
    ref = b["id"]
    s = datetime.fromisoformat(b["slot"])
    when = s.strftime("%d.%m.%Y, %H:%M")
    if job["kind"] == "staff_email":
        send_mail(
            job["recipient"],
            "Nowa rezerwacja " + ref,
            "Nowa rezerwacja wstępna: "
            + ref
            + "\nTermin: "
            + when
            + " (czas polski)\n"
            + p["name"]
            + "\nTelefon: "
            + p["phone"]
            + "\nE-mail: "
            + p["email"]
            + "\n\nPytania pacjenta:\n"
            + (p["questions"] or "Nie podano.")
            + "\n\nOddzwoń, potwierdź termin i ustal płatność oraz dokumentację. Status zmieniaj poleceniem obsługi rezerwacji. Nie przesyłaj tej wiadomości osobom nieupoważnionym.",
        )
    elif job["kind"] == "patient_email":
        send_mail(
            job["recipient"],
            "Otrzymaliśmy rezerwację wstępną",
            "Otrzymaliśmy zgłoszenie nr "
            + ref
            + ".\nTermin: "
            + when
            + " (czas polski).\nKonsultacja online: 600 zł, 30 minut rozmowy, przygotowanie i pisemne zalecenia.\n\nAsystentka oddzwoni w najbliższym możliwym terminie, aby potwierdzić konsultację oraz przekazać informacje dotyczące płatności i przygotowania dokumentacji.\nMożesz również zadzwonić: 577 169 800, codziennie 8:00–17:00.\n\nTo rezerwacja wstępna, nie potwierdzenie opłaconej wizyty. Nie odpowiadaj dokumentacją na ten automatyczny e-mail; sposób przekazania ustali asystentka.",
        )
    elif job["kind"] == "sms":
        token = os.environ["SMSAPI_TOKEN"]
        payload = {
            "to": job["recipient"],
            "message": "Nowa rezerwacja konsultacji. Szczegoly wyslano e-mailem.",
            "format": "json",
        }
        if os.environ.get("SMSAPI_SENDER"):
            payload["from"] = os.environ["SMSAPI_SENDER"]
        req = urllib.request.Request(
            "https://api.smsapi.pl/sms.do",
            data=urllib.parse.urlencode(payload).encode(),
            headers={"Authorization": "Bearer " + token},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            out = json.load(r)
        if "error" in out or not out.get("list"):
            raise RuntimeError("SMS rejected")
    elif job["kind"] == "google":
        token = google_token()
        url = (
            "https://www.googleapis.com/calendar/v3/calendars/"
            + urllib.parse.quote(job["recipient"], safe="")
            + "/events"
        )
        event = {
            "id": "b" + ref,
            "summary": (
                "Konsultacja potwierdzona · "
                if b["status"] == "confirmed"
                else "Rezerwacja wstępna · "
            )
            + ref,
            "description": (
                "Numer rezerwacji: "
                + ref
                + "\nPacjent: "
                + p["name"]
                + "\nTelefon: "
                + p["phone"]
                + "\nE-mail: "
                + p["email"]
                + "\n\nPytania pacjenta:\n"
                + (p["questions"] or "Nie podano.")
                + "\n\nKonsultacja online · 600 zł · 30 minut.\nDostęp wyłącznie z konta lekarza oraz przez uprawnioną integrację techniczną. Nie dodawaj gości.\nUsuń wydarzenie, aby odwołać rezerwację, lub przesuń je na inną godzinę. Synchronizacja zwykle do minuty. Aby oznaczyć potwierdzenie, rozpocznij tytuł od POTWIERDZONA. O zmianie poinformuj pacjenta osobno."
            ),
            "start": {"dateTime": s.isoformat(), "timeZone": "Europe/Warsaw"},
            "end": {
                "dateTime": (s + timedelta(minutes=30)).isoformat(),
                "timeZone": "Europe/Warsaw",
            },
            "transparency": "opaque",
            "visibility": "private",
            "guestsCanInviteOthers": False,
            "guestsCanSeeOtherGuests": False,
            "reminders": {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": 60}],
            },
        }
        try:
            http_json(url, event, {"Authorization": "Bearer " + token}, "POST")
        except urllib.error.HTTPError as e:
            if e.code != 409:
                raise


def sync_calendar(c):
    cid = os.environ.get("GOOGLE_CALENDAR_ID")
    if not cid:
        return
    token = google_token()
    hdr = {"Authorization": "Bearer " + token}
    rows = c.execute(
        "SELECT b.* FROM bookings b WHERE b.status IN ('pending','confirmed') AND b.slot>=? AND EXISTS(SELECT 1 FROM jobs j WHERE j.booking_id=b.id AND j.kind='google' AND j.state='sent')",
        ((now() - timedelta(days=1)).isoformat(),),
    ).fetchall()
    for b in rows:
        url = (
            "https://www.googleapis.com/calendar/v3/calendars/"
            + urllib.parse.quote(cid, safe="")
            + "/events/b"
            + b["id"]
        )
        try:
            event = http_json(url, headers=hdr)
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                event = {"status": "cancelled"}
            else:
                raise
        if event.get("status") == "cancelled":
            c.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (b["id"],))
            c.execute(
                "UPDATE jobs SET state='skipped' WHERE booking_id=? AND state='pending'",
                (b["id"],),
            )
            c.commit()
            continue
        raw = event.get("start", {}).get("dateTime")
        if not raw:
            print("Calendar change needs review:", b["id"])
            continue
        newslot = (
            datetime.fromisoformat(raw.replace("Z", "+00:00"))
            .astimezone(TZ)
            .isoformat()
        )
        confirmed = (
            event.get("summary", "")
            .casefold()
            .startswith(("potwierdzona", "konsultacja potwierdzona"))
        )
        try:
            c.execute(
                "UPDATE bookings SET slot=?,status=? WHERE id=?",
                (newslot, "confirmed" if confirmed else b["status"], b["id"]),
            )
            c.commit()
        except sqlite3.IntegrityError:
            c.rollback()
            print("Conflicting calendar move; contact administrator:", b["id"])


def worker():
    import fcntl

    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (DATA / "worker.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with contextlib.closing(db()) as c:
            try:
                sync_calendar(c)
            except Exception:
                print("Calendar synchronization failed; retry next run.")
            jobs = c.execute(
                "SELECT * FROM jobs WHERE state='pending' AND retry_at<=? AND attempts<10 ORDER BY id LIMIT 100",
                (time.time(),),
            ).fetchall()
            for j in jobs:
                b = c.execute(
                    "SELECT * FROM bookings WHERE id=?", (j["booking_id"],)
                ).fetchone()
                if not b or b["status"] == "cancelled":
                    c.execute("UPDATE jobs SET state='skipped' WHERE id=?", (j["id"],))
                    c.commit()
                    continue
                try:
                    deliver(j, b)
                except Exception:
                    c.execute(
                        "UPDATE jobs SET attempts=attempts+1,retry_at=? WHERE id=?",
                        (time.time() + min(3600, 60 * 2 ** j["attempts"]), j["id"]),
                    )
                    print("Delivery retry required:", j["id"], j["kind"])
                else:
                    c.execute("UPDATE jobs SET state='sent' WHERE id=?", (j["id"],))
                c.commit()


def application(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET")

    def response(status, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        start_response(
            status,
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"),
            ],
        )
        return [raw]

    try:
        if path == "/api/availability" and method == "GET":
            if not LIVE:
                return response("200 OK", {"mode": "preview"})
            config_check()
            return response(
                "200 OK",
                {"mode": "live", "slots": [s.isoformat() for s in available()]},
            )
        if path == "/api/book" and method == "POST":
            if environ.get("HTTP_ORIGIN") != ORIGIN:
                return response(
                    "403 Forbidden", {"error": "Niedozwolone źródło zgłoszenia."}
                )
            if "application/json" not in environ.get("CONTENT_TYPE", ""):
                return response(
                    "415 Unsupported Media Type", {"error": "Nieprawidłowy format."}
                )
            size = int(environ.get("CONTENT_LENGTH") or 0)
            if not 0 < size <= 20000:
                return response(
                    "413 Payload Too Large", {"error": "Zbyt duże zgłoszenie."}
                )
            data = json.loads(environ["wsgi.input"].read(size))
            ident = book(
                data,
                (
                    environ.get("HTTP_X_REAL_IP", environ.get("REMOTE_ADDR", "unknown"))
                    if environ.get("REMOTE_ADDR") in ("127.0.0.1", "::1")
                    else environ.get("REMOTE_ADDR", "unknown")
                ),
            )
            return response("201 Created", {"id": ident, "status": "pending"})
        return response("404 Not Found", {"error": "Nie znaleziono."})
    except ValueError as e:
        return response("400 Bad Request", {"error": str(e)})
    except Exception:
        return response(
            "503 Service Unavailable",
            {
                "error": "Rezerwacja online jest chwilowo niedostępna. Zadzwoń: 577 169 800."
            },
        )


if __name__ == "__main__":
    import sys

    if sys.argv[-1] == "worker":
        worker()
    else:
        print("Production: gunicorn --bind 127.0.0.1:8010 backend.app:application")
