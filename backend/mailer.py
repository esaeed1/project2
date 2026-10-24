"""
mailer.py: mail a warning postcard to RED homes (the county takes the house
within 6 months) through Lob's print-and-mail API (lob.com). Staff see the list
at /api/staff/red and pick homes to mail at /api/staff/postcards.

Env: LOB_API_KEY  test_... renders a PDF proof and mails nothing; live_... prints and mails
     LOB_FROM     optional return address: an adr_... ID saved in the Lob dashboard

Cards go to the taxpayer by name when the county lists a person ("Homeowner" for
companies, trusts and the Land Bank) and leave out the amount owed, since anyone
who handles a postcard can read it.

Language: never guessed from the owner's name. When 5% or more of the residents
of the house's census tract speak Spanish or Arabic and speak English less than
"very well" (ACS table C16001; 5% is HUD's limited-English "safe harbor"), the
card is printed in English and that language. Translations are fixed text, not
model output, because a printed deadline can't carry a model's mistakes.
"""
import html
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import requests

from lookup import DATA, _long, cached_lookup, connect

log = logging.getLogger(__name__)

LOB = "https://api.lob.com/v1/postcards"
MAILING = re.compile(r"(.+), (.+) MI (\d{5})")  # the county's "5661 BRACE, DETROIT MI 48228"
# 4x6 artwork is 6.25 x 4.25 in with bleed; the back's right 3.56 in is Lob's address block.
CARD = ("<html><head><link rel='stylesheet' href='https://fonts.googleapis.com/css2?"
        "family=Noto+Naskh+Arabic&display=swap'></head><body style='margin:0;width:6.25in;"
        "height:4.25in;position:relative;font-family:Arial,Helvetica,\"Noto Naskh Arabic\","
        "sans-serif;color:#111'>{}</body></html>")

# Census Reporter serves the ACS tables without the API key api.census.gov now requires.
ACS = "https://api.censusreporter.org/1.0/data/show/latest?table_ids=C16001&geo_ids=140|05000US26163"
GEOCODER = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
LEP_SHARE = 0.05
NOT_A_PERSON = re.compile(r"\b(LLC|L L C|INC|CORP|CO|COMPANY|BANK|TRUST|TRUSTEE|AUTHORITY|CITY OF|"
                          r"COUNTY|STATE OF|CHURCH|MINISTRIES|ASSOC|ASSOCIATION|PROPERTIES|HOLDINGS|"
                          r"LTD|LP|ESTATE|FUND|MORTGAGE|PUBLIC BODY|HOUSING|INVESTMENTS?|GROUP)\b")

MONTHS = {"es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                 "septiembre", "octubre", "noviembre", "diciembre"],
          "ar": ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس",
                 "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]}
TEXT = {
    "en": ("Important: property tax deadline",
           "Wayne County records show unpaid property taxes on {street}. If they are not paid or "
           "put on a payment plan by {deadline}, the county can take ownership of the house. Free "
           "help is available. <b>Call today: numbers on the back.</b>"),
    "es": ("Importante: fecha límite de impuestos",
           "Los registros del condado de Wayne muestran impuestos de propiedad sin pagar en "
           "{street}. Si no se pagan o no se ponen en un plan de pagos antes del {deadline}, el "
           "condado puede quedarse con la casa. Hay ayuda gratuita. "
           "<b>Llame hoy: los números están al reverso.</b>"),
    "ar": ("هام: موعد نهائي لضرائب العقار",
           "تُظهر سجلات مقاطعة واين ضرائب عقارية غير مدفوعة على العقار {street}. إذا لم تُدفع أو "
           "تُوضع في خطة سداد قبل {deadline}، يمكن للمقاطعة أن تأخذ ملكية المنزل. المساعدة "
           "مجانية. <b>اتصل اليوم: الأرقام على ظهر البطاقة.</b>"),
}


def _date(d: date, lang: str) -> str:
    if lang == "es":
        return f"{d.day} de {MONTHS['es'][d.month - 1]} de {d.year}"
    if lang == "ar":
        return f"{d.day} {MONTHS['ar'][d.month - 1]} {d.year}"
    return _long(d)


def owner_name(taxpayer: str | None) -> str | None:
    """'JOHNSON, MARY' -> 'Mary Johnson'. None for companies, trusts, estates and the Land Bank."""
    raw = (taxpayer or "").strip()
    if not raw or NOT_A_PERSON.search(raw.upper()):
        return None
    last, _, first = raw.partition(",")
    return f"{first.strip()} {last.strip()}".strip().title() if first else raw.title()


def _lep_by_tract() -> dict[str, dict[str, float]]:
    """Wayne County tract GEOID -> share of residents 5+ who speak Spanish / Arabic and English
    less than "very well". Fetched once from the Census API and cached in data/."""
    path = DATA / "acs_language.json"
    if not path.exists():
        data = requests.get(ACS, timeout=60, headers={  # Census Reporter asks for a project-specific UA
            "User-Agent": "detroit-foreclosure-early-warning (github.com/saeedconsulting/project2)"}).json()["data"]
        shares = {}
        for geo, tables in data.items():  # "14000US26163544800" -> tract GEOID "26163544800"
            e = tables["C16001"]["estimate"]
            total = max(e["C16001001"] or 0, 1)
            shares[geo[-11:]] = {"es": (e["C16001005"] or 0) / total, "ar": (e["C16001035"] or 0) / total}
        path.write_text(json.dumps(shares), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def card_language(address: str) -> str:
    """'es' or 'ar' when 5%+ of the house's census tract needs that language, else 'en'."""
    try:
        matches = requests.get(GEOCODER, params={
            "address": address, "benchmark": "Public_AR_Current", "vintage": "Current_Current",
            "layers": 8, "format": "json"}, timeout=30).json()["result"]["addressMatches"]
        tract = matches[0]["geographies"]["Census Tracts"][0]["GEOID"]
        lang, share = max(_lep_by_tract().get(tract, {}).items(), key=lambda kv: kv[1], default=("en", 0))
        return lang if share >= LEP_SHARE else "en"
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return "en"


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
                          "owner": res.get("owner"), "mail_to": owner_name(res.get("owner")) or "Homeowner",
                          "total_due": res["total_due"], "deadline": res["deadline"],
                          "days_left": (date.fromisoformat(res["deadline"]) - date.today()).days,
                          "checked_at": res["checked_at"], "postcard": sent.get(r["key"])})
    con.close()
    return sorted(homes, key=lambda h: (h["deadline"], h["address"]))


def card(result: dict, lang: str = "en", name: str | None = None) -> tuple[str, str]:
    """(front, back) HTML for a 4x6 postcard to one RED home; lang 'es'/'ar' adds that language."""
    street = html.escape(result["address"].split(",")[0].title())
    d = date.fromisoformat(result["deadline"])
    two = lang != "en"
    blocks = []
    for code in ("en", lang) if two else ("en",):
        heading, body = TEXT[code]
        rtl = " dir='rtl'" if code == "ar" else ""
        blocks.append(
            f"<div{rtl} style='font-size:{11 if two else 15}pt;line-height:1.3;margin-top:.08in'>"
            f"<b style='color:#b91c1c'>{heading}</b><br>"
            f"{body.format(street=street, deadline=_date(d, code))}</div>")
    greeting = f"<div style='font-size:11pt'>Dear {html.escape(name)},</div>" if name else ""
    front = (f"<div style='padding:{'.3in' if two else '.45in'}'>{greeting}"
             f"<div style='font-size:{24 if two else 30}pt;font-weight:bold'>{_long(d)}</div>"
             + "".join(blocks) + "</div>")
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
    name, lang = owner_name(result.get("owner")), card_language(result["address"])
    front, back = card(result, lang, name)
    body = {"to": {"name": name or "Homeowner", "address_line1": m[1], "address_city": m[2].title(),
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
        return {"ok": True, "mail_to": name or "Homeowner", "lang": lang,
                "postcard": {"id": d["id"], "url": d.get("url"),
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
            res = cached_lookup(home["address"], max_age_hours=0)  # fresh: just paid? owner changed?
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
