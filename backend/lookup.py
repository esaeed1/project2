"""
lookup.py: Wayne County delinquent-tax status for a Detroit address, and the
foreclosure deadline that status implies.

Source: the Treasurer's public search (same request as property_monitor's
back_taxes()):
  POST https://pta.waynecounty.com/Home/SearchResult   (form-encoded)
    MUN_CD=01 (Detroit)  PROP_STREET_NBR  PROP_STREET_NM  searchByAddressInd=AddressSearch
  -> an HTML page. Each delinquent year is one <tr> in #tblTaxGrid carrying
     hidden inputs SearchResult[N].TAX_YEAR / BASE_TAX / INTEREST /
     TOTAL_AMOUNT_DUE, and the status as the name="" of a StatusHelp span.
  Every page also has a Definitions section containing each status word, so
  the status must be read from inside the row, never from the whole page.

Michigan GPTA timeline for taxes levied in year Y:
  delinquent Mar 1 Y+1 -> forfeited Mar 1 Y+2 -> foreclosed if unpaid Mar 31 Y+3.
The oldest unpaid year sets the deadline. Homes the county held back from an
earlier foreclosure still show SUBJECT TO FORECLOSURE for older years; their
deadline is the next March 31.
"""
import html as htmllib
import json
import re
import sqlite3
import threading
import time
from datetime import date
from pathlib import Path

import requests

PTA = "https://pta.waynecounty.com/Home/SearchResult"
DETROIT = "01"
TIMEOUT = 40
MIN_GAP = 0.5            # seconds between PTA requests, across all threads
CACHE_HOURS = 12

DATA = Path(__file__).resolve().parent.parent / "data"
DB = DATA / "app.db"

HOPE_DEADLINE = date(2026, 11, 6)   # detroitmi.gov/hope: 2026 applications due 4:30 pm

HELP = [
    {"name": "Wayne County Treasurer: pay or start a payment plan",
     "phone": "313-224-5990", "url": "https://pta.waynecounty.com/",
     "note": "Owner-occupants can get IRSPA (5-year plan, 6% interest) or REGSPA."},
    {"name": "Detroit HOPE poverty tax exemption",
     "phone": None, "url": "https://detroitmi.gov/hope",
     "note": "Can cut current taxes to $0. 2026 applications due Nov 6, 2026. "
             "Qualifying also opens Pay As You Stay, which reduces back taxes."},
    {"name": "United Community Housing Coalition (UCHC): free help",
     "phone": "313-963-3310", "url": "https://www.uchcdetroit.org/",
     "note": "Free counseling for Detroiters facing tax foreclosure."},
]

SUFFIXES = {"ST", "STREET", "AVE", "AV", "AVENUE", "RD", "ROAD", "DR", "DRIVE", "BLVD",
            "BOULEVARD", "CT", "COURT", "PL", "PLACE", "LN", "LANE", "HWY", "HIGHWAY",
            "PKWY", "PARKWAY", "TER", "TERRACE", "CIR", "CIRCLE"}
DIRECTIONS = {"NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}

_lock = threading.Lock()
_last = 0.0


def address_key(addr: str) -> str:
    """'17427 Oakland St., Apt 2, Detroit' -> '17427 OAKLAND' (from check_my_addresses.py)."""
    street = addr.upper().split(",")[0]
    street = re.split(r"\s(?:APT|UNIT|#)", street)[0]
    words = re.sub(r"[^A-Z0-9 ]", " ", street).split()
    words = [DIRECTIONS.get(w, w) for w in words]
    while len(words) > 2 and words[-1] in SUFFIXES:
        words.pop()
    return " ".join(words)


def _money(v: str) -> float:
    return float(re.sub(r"[^0-9.]", "", v or "") or 0)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _fetch(number: str, street: str) -> str:
    global _last
    with _lock:
        wait = MIN_GAP - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.time()
    resp = requests.post(PTA, data={
        "MUN_CD": DETROIT, "PARCEL_ID": "", "PARCEL_SEARCH_MSG": "",
        "PROP_STREET_NBR": number, "PROP_STREET_NM": street,
        "frequency": "on", "searchByAddressInd": "AddressSearch",
    }, headers={"User-Agent": "Mozilla/5.0"}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.text


def parse(page: str) -> dict:
    """The county's result page -> {found, address, parcel_id, years, total_due, pay_by}."""
    addr = re.search(r'<label id="PROP_STREET_NBR"[^>]*>([^<]*)</label>', page)
    if not addr:
        return {"found": False}
    parcel = re.search(r"Parcel ID.*?<label[^>]*>\s*([^<]+)", page, re.S)

    grid = page[page.find('id="tblTaxGrid"'):]
    grid = grid[grid.find("</thead>"):grid.find("</table>")]
    years = []
    for row in re.findall(r"<tr>(.*?)</tr>", grid, re.S):
        def field(name):
            m = re.search(rf'\.{name}"[^>]*value="([^"]*)"', row)
            return m.group(1) if m else ""
        if not field("TAX_YEAR"):
            continue
        status = re.search(r'class="StatusHelp"[^>]*name="([^"]+)"', row)
        years.append({
            "year": int(field("TAX_YEAR")),
            "tax": _money(field("BASE_TAX")),
            "interest_fees": _money(field("INTEREST")),
            "due": _money(field("TOTAL_AMOUNT_DUE")),
            "status": status.group(1).strip().upper() if status else "",
        })

    total = re.search(r"on or before\s*([\d/]+)\s*:\s*\$?([\d,.]+)",
                      _text(page[page.find('id="tblTotalTax"'):][:2000]))
    return {
        "found": True,
        "address": _text(addr.group(1)),
        "parcel_id": parcel.group(1).strip() if parcel else None,
        "years": years,
        "total_due": _money(total.group(2)) if total else round(sum(y["due"] for y in years), 2),
        "pay_by": total.group(1) if total else None,
    }


def _long(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


def assess(result: dict, today: date | None = None) -> dict:
    """Add risk level, deadline and a plain-language message to a parsed result.

    level: none | yellow (delinquent) | orange (forfeited) | red (deadline within 6 months or past)
    """
    today = today or date.today()
    years = result.get("years", [])
    if not result.get("found"):
        return {**result, "at_risk": None, "level": "unknown",
                "message": "We couldn't find that address in Wayne County's tax records. "
                           "Check the house number and street name."}
    if not years:
        return {**result, "at_risk": False, "level": "none", "deadline": None, "days_left": None,
                "message": "Good news: Wayne County shows no unpaid back taxes for this address."}

    oldest = min(y["year"] for y in years)
    deadline = date(oldest + 3, 3, 31)
    if deadline < today:  # held over from an earlier foreclosure: next judgment date
        deadline = date(today.year + (today > date(today.year, 3, 31)), 3, 31)
    forfeited = today >= date(oldest + 2, 3, 1)
    days = (deadline - today).days
    level = "red" if days <= 183 else "orange" if forfeited else "yellow"
    owed = f"${result['total_due']:,.2f}"
    listed = ", ".join(str(y["year"]) for y in sorted(years, key=lambda y: y["year"]))

    msg = (f"You owe {owed} in back property taxes ({listed}). If the {oldest} taxes are not "
           f"paid or put on a payment plan by {_long(deadline)}, Wayne County will take "
           f"ownership of this house. That is {days} days from today.")
    if level != "red" and not forfeited:
        msg += f" Paying before {_long(date(oldest + 2, 3, 1))} avoids extra forfeiture fees."
    if today <= HOPE_DEADLINE:
        msg += (f" If money is tight, apply for the HOPE tax exemption by {_long(HOPE_DEADLINE)}.")

    return {**result, "at_risk": True, "level": level, "oldest_year": oldest,
            "deadline": deadline.isoformat(), "days_left": days, "message": msg}


def lookup(address: str) -> dict:
    """Live lookup: address -> assessed result with help links. Raises on network errors."""
    key = address_key(address)
    m = re.match(r"^(\d{1,6})\s+(.+)$", key)
    if not m:
        return {"query": address, "found": False, "level": "unknown", "at_risk": None,
                "message": "Enter a street address with a house number, like 14390 Dolphin.",
                "help": HELP}
    result = assess(parse(_fetch(m.group(1), m.group(2))))
    return {"query": address, **result, "help": HELP,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def connect() -> sqlite3.Connection:
    DATA.mkdir(exist_ok=True)
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS lookups (key TEXT PRIMARY KEY, result TEXT, checked_at REAL);
        CREATE TABLE IF NOT EXISTS homes (parcel_id TEXT PRIMARY KEY, key TEXT, neighborhood TEXT,
                                          lat REAL, lon REAL);
        CREATE TABLE IF NOT EXISTS signups (id INTEGER PRIMARY KEY, address TEXT, phone TEXT,
                                            email TEXT, lang TEXT, last_level TEXT,
                                            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    """)
    return con


def cached_lookup(address: str, max_age_hours: float = CACHE_HOURS) -> dict:
    """lookup() through the SQLite cache, so the demo and the map build don't re-hit the county."""
    key = address_key(address)
    con = connect()
    try:
        row = con.execute("SELECT result, checked_at FROM lookups WHERE key = ?", (key,)).fetchone()
        if row and time.time() - row["checked_at"] < max_age_hours * 3600:
            return {**json.loads(row["result"]), "query": address}
        result = lookup(address)
        if result.get("found"):
            con.execute("INSERT OR REPLACE INTO lookups VALUES (?, ?, ?)",
                        (key, json.dumps(result), time.time()))
            con.commit()
        return result
    finally:
        con.close()


if __name__ == "__main__":
    import sys
    print(json.dumps(lookup(" ".join(sys.argv[1:]) or "14390 Dolphin"), indent=2))
