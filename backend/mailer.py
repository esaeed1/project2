"""
mailer.py: mail a warning postcard to RED homes (the county takes the house
within 6 months) through Lob's print-and-mail API (lob.com). Staff see the list
at /api/staff/red and pick homes to mail at /api/staff/postcards.

Env: LOB_API_KEY  test_... renders a PDF proof and mails nothing; live_... prints and mails
     LOB_FROM     optional return address: an adr_... ID saved in the Lob dashboard

Cards go to "Homeowner" at the house (the parcel file keeps no owner names) and
leave out the amount owed, since anyone who handles a postcard can read it.
"""
import html
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import requests

from lookup import _long, cached_lookup, connect

log = logging.getLogger(__name__)

LOB = "https://api.lob.com/v1/postcards"
MAILING = re.compile(r"(.+), (.+) MI (\d{5})")  # the county's "5661 BRACE, DETROIT MI 48228"
# 4x6 artwork is 6.25 x 4.25 in with bleed; the back's right 3.56 in is Lob's address block.
CARD = ("<html><body style='margin:0;width:6.25in;height:4.25in;position:relative;"
        "font-family:Arial,Helvetica,sans-serif;color:#111'>{}</body></html>")


def mode() -> str | None:
    """'live' (cards are mailed), 'test' (Lob renders a proof, mails nothing) or None (no key)."""
    key = os.environ.get("LOB_API_KEY", "")
    return "live" if key.startswith("live_") else "test" if key else None


def red_homes() -> list[dict]:
    """Every RED home in the lookup cache, soonest deadline first, with its postcard if one was sent."""
    con = connect()
    sent = {r["key"]: {k: r[k] for k in ("id", "url", "expected_delivery", "sent_at")}
            for r in con.execute("SELECT * FROM postcards WHERE mode = ?", (mode() or "test",))}
    homes = []
    for r in con.execute("SELECT key, result FROM lookups"):
        res = json.loads(r["result"])
        if res["level"] == "red":
            homes.append({"key": r["key"], "address": res["address"], "parcel_id": res.get("parcel_id"),
                          "total_due": res["total_due"], "deadline": res["deadline"],
                          "days_left": (date.fromisoformat(res["deadline"]) - date.today()).days,
                          "checked_at": res["checked_at"], "postcard": sent.get(r["key"])})
    con.close()
    return sorted(homes, key=lambda h: (h["deadline"], h["address"]))


def card(result: dict) -> tuple[str, str]:
    """(front, back) HTML for a 4x6 postcard to one RED home."""
    street = html.escape(result["address"].split(",")[0].title())
    deadline = _long(date.fromisoformat(result["deadline"]))
    front = (
        "<div style='padding:.45in'>"
        "<div style='font-size:13pt;font-weight:bold;color:#b91c1c'>Important: property tax deadline</div>"
        f"<div style='font-size:30pt;font-weight:bold;margin:.08in 0 .12in'>{deadline}</div>"
        "<div style='font-size:15pt;line-height:1.35'>Wayne County records show unpaid property "
        f"taxes on {street}. If they are not paid or put on a payment plan by {deadline}, the "
        "county can take ownership of the house. Free help is available. "
        "<b>Call today: numbers on the back.</b></div></div>")
    lines = "".join(
        f"<p style='margin:0 0 .12in'><b>{html.escape(h['phone'] or h['url'].removeprefix('https://').rstrip('/'))}"
        f"</b><br>{html.escape(h['name'])}</p>" for h in result.get("help", []))
    back = ("<div style='position:absolute;left:.35in;top:.35in;width:2.05in;font-size:9.5pt;line-height:1.3'>"
            f"<p style='font-size:13pt;font-weight:bold;margin:0 0 .14in'>Free help</p>{lines}</div>")
    return CARD.format(front), CARD.format(back)


def send_postcard(result: dict) -> dict:
    key = os.environ.get("LOB_API_KEY")
    if not key:
        return {"ok": False, "error": "LOB_API_KEY not set"}
    m = MAILING.fullmatch(result.get("address") or "")
    if not m:
        return {"ok": False, "error": "The county record has no mailing address."}
    front, back = card(result)
    body = {"to": {"name": "Homeowner", "address_line1": m[1], "address_city": m[2].title(),
                   "address_state": "MI", "address_zip": m[3]},
            "front": front, "back": back, "size": "4x6", "use_type": "operational",
            "description": f"Tax foreclosure warning: {result['address']}"[:255]}
    if os.environ.get("LOB_FROM"):
        body["from"] = os.environ["LOB_FROM"]
    resp = requests.post(LOB, auth=(key, ""), json=body, timeout=30, headers={
        # A double click or a retry within 24 h returns the same card instead of mailing two.
        "Idempotency-Key": re.sub(r"[^A-Za-z0-9]+", "-", f"{result['address']} {result['deadline']}")})
    if resp.status_code == 200:
        d = resp.json()
        return {"ok": True, "postcard": {"id": d["id"], "url": d.get("url"),
                                         "expected_delivery": d.get("expected_delivery_date")}}
    log.error("Lob error %s: %s", resp.status_code, resp.text)
    try:
        return {"ok": False, "error": resp.json()["error"]["message"]}
    except (ValueError, KeyError, TypeError):
        return {"ok": False, "error": f"Lob answered {resp.status_code}"}


def mail_postcards(keys: list[str]) -> list[dict]:
    """Mail a postcard to each listed RED home (by key) that is still RED and hasn't had one."""
    homes = {h["key"]: h for h in red_homes()}

    def one(key):
        home = homes.get(key)
        if not home:
            return {"key": key, "ok": False, "error": "Not on the RED list."}
        if home["postcard"]:
            return {"key": key, "address": home["address"], "ok": False, "error": "Already mailed."}
        try:
            res = cached_lookup(home["address"], max_age_hours=24)  # don't mail someone who just paid
            if res["level"] != "red":
                return {"key": key, "address": home["address"], "ok": False,
                        "error": f"No longer RED (now {res['level']})."}
            return {"key": key, "address": home["address"], **send_postcard(res)}
        except Exception as exc:  # noqa: BLE001  one bad home must not lose the cards already mailed
            return {"key": key, "address": home["address"], "ok": False, "error": str(exc)}

    with ThreadPoolExecutor(5) as pool:
        results = list(pool.map(one, dict.fromkeys(keys)))
    con = connect()
    con.executemany("INSERT OR REPLACE INTO postcards (key, mode, address, id, url, expected_delivery) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [(r["key"], mode(), r["address"], r["postcard"]["id"], r["postcard"]["url"],
                      r["postcard"]["expected_delivery"]) for r in results if r["ok"]])
    con.commit()
    con.close()
    return results
