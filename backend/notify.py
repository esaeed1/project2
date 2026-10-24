"""
notify.py: send foreclosure alerts by SMS (Twilio, via property_monitor's
twilio_helper) and email (Resend, same call as the property reports).

Env: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_PHONE, RESEND_API_KEY, FROM_EMAIL

Run on a schedule to re-check every sign-up and alert when the status changes
or the deadline gets close:
    python notify.py
"""
import logging
import os

import requests

from lookup import cached_lookup, connect
from twilio_helper import send_sms

log = logging.getLogger(__name__)

REMIND_AT_DAYS = {120, 90, 60, 30, 14, 7, 3, 1}


def alert_text(result: dict) -> str:
    return (f"Detroit tax alert for {result.get('address') or result['query']}: {result['message']} "
            f"Free help: UCHC 313-963-3310. Payment plans: Wayne County Treasurer 313-224-5990. "
            f"Reply STOP to opt out.")


def send_email(to: str, subject: str, body: str) -> dict:
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        return {"success": False, "error": "RESEND_API_KEY not set"}
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"from": os.environ.get("FROM_EMAIL", "alerts@resend.dev"), "to": [to],
              "subject": subject, "text": body},
        timeout=15,
    )
    if resp.status_code in (200, 201):
        return {"success": True, "id": resp.json().get("id")}
    log.error("Resend error %s: %s", resp.status_code, resp.text)
    return {"success": False, "error": resp.text}


def notify(phone: str | None, email: str | None, result: dict) -> dict:
    text = alert_text(result)
    sent = {}
    if phone:
        sent["sms"] = send_sms(text, to_phone=phone)
    if email:
        sent["email"] = send_email(email, "Property tax alert: " + (result.get("address") or ""), text)
    return sent


def check_signups() -> None:
    con = connect()
    for s in con.execute("SELECT * FROM signups").fetchall():
        result = cached_lookup(s["address"], max_age_hours=0)
        changed = result["level"] != s["last_level"]
        if changed or result.get("days_left") in REMIND_AT_DAYS:
            log.info("alert %s: %s -> %s", s["address"], s["last_level"], result["level"])
            notify(s["phone"], s["email"], result)
            con.execute("UPDATE signups SET last_level = ? WHERE id = ?", (result["level"], s["id"]))
            con.commit()
    con.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    check_signups()
