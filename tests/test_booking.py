import unittest, tempfile, os, contextlib, sqlite3, io, json, concurrent.futures
from datetime import datetime
from unittest.mock import patch
from cryptography.fernet import Fernet
from backend import app


class BookingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "PUBLIC_ORIGIN": "https://test.example",
                "BOOKING_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "SMTP_HOST": "test",
                "SMTP_USER": "test",
                "SMTP_PASSWORD": "test",
                "SMTP_FROM": "test@example.com",
                "STAFF_EMAILS": "doctor@example.com,assistant@example.com",
                "STAFF_SMS": "",
                "GOOGLE_CALENDAR_ID": "",
                "GOOGLE_SERVICE_ACCOUNT_FILE": "",
            },
        )
        self.env.start()
        self.a = patch.multiple(
            app, DATA=app.Path(self.tmp.name), LIVE=True, ORIGIN="https://test.example"
        )
        self.a.start()
        self.n = patch.object(
            app, "now", return_value=datetime(2026, 11, 1, 12, tzinfo=app.TZ)
        )
        self.n.start()
        with contextlib.closing(app.db()):
            pass

    def tearDown(self):
        self.n.stop()
        self.a.stop()
        self.env.stop()
        self.tmp.cleanup()

    def payload(self, req="a" * 32):
        return {
            "name": "Pacjent Testowy",
            "phone": "123456789",
            "email": "test@example.com",
            "questions": "Pytanie testowe",
            "slot": app.allowed_slots()[0].isoformat(),
            "request_id": req,
            "terms": True,
        }

    def test_only_fridays_two_times(self):
        slots = app.allowed_slots()
        self.assertEqual(len(slots), 10)
        self.assertTrue(all(s.weekday() == 4 and s.hour in (16, 17) for s in slots))

    def test_saturday_rejected(self):
        d = self.payload()
        d["slot"] = "2026-11-07T16:00:00+01:00"
        with self.assertRaises(ValueError):
            app.book(d, "ip")

    def test_atomic_booking_and_outbox(self):
        ident = app.book(self.payload(), "ip")
        with contextlib.closing(app.db()) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 3)
            row = c.execute("SELECT * FROM bookings").fetchone()
            self.assertEqual(row["status"], "pending")
            self.assertNotIn(b"Pacjent", bytes(row["payload"]))
            self.assertEqual(
                json.loads(app.secret().decrypt(row["payload"]))["name"],
                "Pacjent Testowy",
            )
        self.assertNotIn(
            self.payload()["slot"], [s.isoformat() for s in app.available()]
        )

    def test_calendar_only_booking(self):
        with (
            patch.dict(
                os.environ,
                {
                    "SMTP_HOST": "",
                    "SMTP_USER": "",
                    "SMTP_PASSWORD": "",
                    "SMTP_FROM": "",
                    "STAFF_EMAILS": "",
                    "GOOGLE_CALENDAR_ID": "calendar",
                    "GOOGLE_SERVICE_ACCOUNT_FILE": "/credentials.json",
                },
            ),
            patch.object(app, "google_busy", return_value=[]),
        ):
            ident = app.book(self.payload(), "ip")

        with contextlib.closing(app.db()) as connection:
            jobs = connection.execute(
                "SELECT kind,recipient FROM jobs WHERE booking_id=?", (ident,)
            ).fetchall()

        self.assertEqual(
            [(job["kind"], job["recipient"]) for job in jobs], [("google", "calendar")]
        )

    def test_same_request_id_no_duplicates(self):
        a = app.book(self.payload(), "ip")
        b = app.book(self.payload(), "ip")
        self.assertEqual(a, b)

    def test_changed_payload_same_id_rejected(self):
        app.book(self.payload(), "ip")
        d = self.payload()
        d["name"] = "Inna Osoba"
        with self.assertRaises(ValueError):
            app.book(d, "ip")

    def test_duplicate_slot_rejected(self):
        app.book(self.payload(), "ip")
        with self.assertRaises(ValueError):
            app.book(self.payload("b" * 32), "other")

    def test_parallel_booking_only_one_success(self):
        def run(i):
            try:
                return app.book(self.payload(str(i) * 32), "ip" + str(i))
            except ValueError:
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            r = list(pool.map(run, [1, 2]))
        self.assertEqual(sum(x is not None for x in r), 1)

    def test_terms_and_honeypot(self):
        for field, value in [("terms", False), ("website", "bot")]:
            d = self.payload()
            d[field] = value
            with self.assertRaises(ValueError):
                app.book(d, "ip")

    def test_worker_retry_then_success(self):
        app.book(self.payload(), "ip")
        with patch.object(app, "deliver", side_effect=RuntimeError):
            app.worker()
        with contextlib.closing(app.db()) as c:
            self.assertEqual(
                c.execute("SELECT SUM(attempts) FROM jobs").fetchone()[0], 3
            )
            c.execute("UPDATE jobs SET retry_at=0")
            c.commit()
        with patch.object(app, "deliver"):
            app.worker()
        with contextlib.closing(app.db()) as c:
            self.assertEqual(
                c.execute("SELECT COUNT(*) FROM jobs WHERE state='sent'").fetchone()[0],
                3,
            )

    def test_cross_origin_rejected(self):
        statuses = []
        r = app.application(
            {
                "PATH_INFO": "/api/book",
                "REQUEST_METHOD": "POST",
                "HTTP_ORIGIN": "https://evil.example",
            },
            lambda s, h: statuses.append(s),
        )
        self.assertEqual(statuses, ["403 Forbidden"])

    def test_calendar_failure_does_not_accept(self):
        with patch.object(app, "google_busy", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                app.book(self.payload(), "ip")
        with contextlib.closing(app.db()) as c:
            self.assertEqual(
                c.execute("SELECT COUNT(*) FROM bookings").fetchone()[0], 0
            )

    def test_google_busy_removes_slot(self):
        s = app.allowed_slots()[0]
        with patch.object(
            app, "google_busy", return_value=[(s, s + app.timedelta(minutes=30))]
        ):
            self.assertNotIn(s, app.available())

    def synced_booking(self):
        ident = app.book(self.payload(), "ip")
        with contextlib.closing(app.db()) as c:
            c.execute(
                "INSERT INTO jobs(booking_id,kind,recipient,state) VALUES(?,?,?,'sent')",
                (ident, "google", "cal"),
            )
            c.commit()
        return ident

    def test_google_delete_releases_booking(self):
        ident = self.synced_booking()
        with patch.dict(os.environ, {"GOOGLE_CALENDAR_ID": "cal"}), patch.object(
            app, "google_token", return_value="test"
        ), patch.object(
            app, "http_json", return_value={"status": "cancelled"}
        ), contextlib.closing(
            app.db()
        ) as c:
            app.sync_calendar(c)
            self.assertEqual(
                c.execute(
                    "SELECT status FROM bookings WHERE id=?", (ident,)
                ).fetchone()[0],
                "cancelled",
            )

    def test_google_move_updates_slot_and_confirmation(self):
        ident = self.synced_booking()
        new = app.allowed_slots()[1].isoformat()
        with patch.dict(os.environ, {"GOOGLE_CALENDAR_ID": "cal"}), patch.object(
            app, "google_token", return_value="test"
        ), patch.object(
            app,
            "http_json",
            return_value={"start": {"dateTime": new}, "summary": "POTWIERDZONA · test"},
        ), contextlib.closing(
            app.db()
        ) as c:
            app.sync_calendar(c)
            r = c.execute(
                "SELECT slot,status FROM bookings WHERE id=?", (ident,)
            ).fetchone()
            self.assertEqual(r["slot"], new)
            self.assertEqual(r["status"], "confirmed")

    def test_google_lookup_error_keeps_booking(self):
        ident = self.synced_booking()
        with patch.dict(os.environ, {"GOOGLE_CALENDAR_ID": "cal"}), patch.object(
            app, "google_token", return_value="test"
        ), patch.object(app, "http_json", side_effect=RuntimeError), contextlib.closing(
            app.db()
        ) as c:
            with self.assertRaises(RuntimeError):
                app.sync_calendar(c)
            self.assertEqual(
                c.execute(
                    "SELECT status FROM bookings WHERE id=?", (ident,)
                ).fetchone()[0],
                "pending",
            )

    def test_calendar_description_includes_contact_and_questions_private(self):
        ident = app.book(self.payload(), "ip")
        with contextlib.closing(app.db()) as c:
            b = c.execute("SELECT * FROM bookings WHERE id=?", (ident,)).fetchone()
        with patch.object(app, "google_token", return_value="test"), patch.object(
            app, "http_json"
        ) as post:
            app.deliver({"kind": "google", "recipient": "calendar"}, b)
            event = post.call_args.args[1]
            self.assertIn("Pacjent Testowy", event["description"])
            self.assertIn("Pytanie testowe", event["description"])
            self.assertIn("test@example.com", event["description"])
            self.assertIn("123456789", event["description"])
            self.assertEqual(event["visibility"], "private")
            self.assertNotIn("attendees", event)
            self.assertNotIn("Pacjent Testowy", event["summary"])


if __name__ == "__main__":
    unittest.main()
