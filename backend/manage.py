import contextlib
import json
import sys
import urllib.error
import urllib.parse

from backend import app


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit("list | show ID | confirm ID | cancel ID | deliveries | retry")
    with contextlib.closing(app.db()) as c:
        if args[0] == "list":
            for b in c.execute("SELECT id,slot,status FROM bookings ORDER BY slot"):
                print(b["id"], b["slot"], b["status"])
        elif args[0] == "deliveries":
            for j in c.execute(
                "SELECT id,booking_id,kind,state,attempts FROM jobs WHERE state!='sent'"
            ):
                print(dict(j))
        elif args[0] == "retry":
            c.execute("UPDATE jobs SET attempts=0,retry_at=0 WHERE state='pending'")
            c.commit()
        elif args[0] == "show" and len(args) == 2:
            b = c.execute("SELECT * FROM bookings WHERE id=?", (args[1],)).fetchone()
            if not b:
                raise SystemExit("Unknown ID")
            print(
                json.dumps(
                    json.loads(app.secret().decrypt(b["payload"])),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args[0] in ["confirm", "cancel"] and len(args) == 2:
            b = c.execute("SELECT * FROM bookings WHERE id=?", (args[1],)).fetchone()
            if not b:
                raise SystemExit("Unknown ID")
            target = "confirmed" if args[0] == "confirm" else "cancelled"
            if b["status"] == "cancelled" and target == "confirmed":
                raise SystemExit(
                    "Cancelled booking cannot be reactivated; create a new booking."
                )
            if app.os.environ.get("GOOGLE_CALENDAR_ID"):
                cid = urllib.parse.quote(app.os.environ["GOOGLE_CALENDAR_ID"], safe="")
                url = (
                    "https://www.googleapis.com/calendar/v3/calendars/"
                    + cid
                    + "/events/b"
                    + b["id"]
                )
                hdr = {"Authorization": "Bearer " + app.google_token()}
                try:
                    if target == "cancelled":
                        req = app.urllib.request.Request(
                            url, headers=hdr, method="DELETE"
                        )
                        with app.urllib.request.urlopen(req, timeout=15):
                            pass
                    else:
                        app.http_json(
                            url,
                            {"summary": "Konsultacja potwierdzona · " + b["id"]},
                            hdr,
                            "PATCH",
                        )
                except urllib.error.HTTPError as e:
                    if e.code not in (404, 410):
                        raise
            c.execute("UPDATE bookings SET status=? WHERE id=?", (target, b["id"]))
            if target == "cancelled":
                c.execute(
                    "UPDATE jobs SET state='skipped' WHERE booking_id=? AND state='pending'",
                    (b["id"],),
                )
            c.commit()
            print(
                "Status:",
                target,
                "— inform the patient separately. No refund or email was executed.",
            )
        else:
            raise SystemExit("Invalid command")


if __name__ == "__main__":
    import fcntl

    app.DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (app.DATA / "worker.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        main()
