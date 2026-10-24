"""
lookup.py: Wayne County delinquent-tax status for a Detroit address, and the
foreclosure deadline that status implies.

Source: the Treasurer's public search (same request as property_monitor's
back_taxes()):
  POST https://pta.waynecounty.com/Home/SearchResult   (form-encoded)
    MUN_CD=01 (Detroit)  PARCEL_ID  searchByAddressInd=ParcelSearch
    or                   PROP_STREET_NBR  PROP_STREET_NM  searchByAddressInd=AddressSearch
  The address search misses ~7% of homes the parcel search finds, so the
  parcel ID is looked up in data/parcels.csv (fetch_parcels.py) first.
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
import calendar
import csv
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
# The search form's MUN_CD options (Twp/City dropped where people don't type them).
MUNICIPALITIES = {
    "ALLEN PARK": "30", "BELLEVILLE": "31", "BROWNSTOWN": "70", "CANTON": "71", "DEARBORN": "32",
    "DEARBORN HEIGHTS": "33", "DETROIT": "01", "ECORSE": "34", "FLAT ROCK": "58",
    "GARDEN CITY": "35", "GIBRALTAR": "36", "GROSSE ILE": "73", "GROSSE POINTE": "37",
    "GROSSE POINTE FARMS": "38", "GROSSE POINTE PARK": "39", "GROSSE POINTE WOODS": "40",
    "HAMTRAMCK": "41", "HARPER WOODS": "42", "HIGHLAND PARK": "43", "HURON": "75", "INKSTER": "44",
    "LINCOLN PARK": "45", "LIVONIA": "46", "MELVINDALE": "47", "NORTHVILLE": "48", "PLYMOUTH": "49",
    "REDFORD": "79", "RIVER ROUGE": "50", "RIVERVIEW": "51", "ROCKWOOD": "52", "ROMULUS": "80",
    "SOUTHGATE": "53", "SUMPTER": "81", "TAYLOR": "60", "TRENTON": "54", "VAN BUREN": "83",
    "WAYNE": "55", "WESTLAND": "56", "WOODHAVEN": "59", "WYANDOTTE": "57",
}
TIMEOUT = 40
MIN_GAP = 0.5            # seconds between PTA requests, across all threads
CACHE_HOURS = 12

DATA = Path(__file__).resolve().parent.parent / "data"
DB = DATA / "app.db"
PARCELS = DATA / "parcels.csv"

HOPE_DEADLINE = date(2026, 11, 6)   # detroitmi.gov/hope: 2026 applications due 4:30 pm

HELP = [
    {"name": "Wayne County Treasurer: pay or start a payment plan",
     "phone": "313-224-5990", "url": "https://pta.waynecounty.com/",
     "note": "Owner-occupants can get IRSPA (5-year plan, 6% interest) or REGSPA. Hardship? "
             "Ask about DOOE, an extension, and Pay As You Stay (PAYS), which lowers back taxes."},
    {"name": "Detroit HOPE poverty tax exemption",
     "phone": None, "url": "https://detroitmi.gov/hope",
     "note": "Can cut current taxes to $0. 2026 applications due Nov 6, 2026. "
             "Qualifying also opens Pay As You Stay, which reduces back taxes."},
    {"name": "United Community Housing Coalition (UCHC): free help",
     "phone": "313-963-3310", "url": "https://www.uchcdetroit.org/",
     "note": "Free counseling for Detroiters facing tax foreclosure."},
]

# Notice of intent to claim money left over after a tax-foreclosure sale (MCL 211.78t).
FORM_5743 = "https://www.michigan.gov/taxes/-/media/Project/Websites/taxes/Forms/Property-Tax/5743.pdf"

_MCL = "https://www.legislature.mi.gov/Laws/MCL?objectName=mcl-211-"
# The General Property Tax Act sections behind each step, in plain language.
LAWS = [
    {"cite": "MCL 211.78a", "url": _MCL + "78a",
     "rule": "Taxes still unpaid on March 1 after the year they were billed go to the county as "
             "delinquent, with a 4% fee and 1% interest a month."},
    {"cite": "MCL 211.78g", "url": _MCL + "78g",
     "rule": "After a year delinquent, the house is forfeited to the county on March 1: a $175 fee "
             "is added and interest goes up by 1/2% a month. You still own it and can still pay."},
    {"cite": "MCL 211.78k", "url": _MCL + "78k",
     "rule": "If the taxes are not paid by the March 31 after the court's foreclosure judgment, "
             "the county takes the title and you can no longer pay to keep the house."},
    {"cite": "MCL 211.78t", "url": _MCL + "78t",
     "rule": "If the county sells the house for more than you owed (plus its costs and a 5% fee), "
             "you can claim the rest, but only if you file a notarized Form 5743 by the July 1 "
             "after the foreclosure."},
    {"cite": "MCL 211.7u", "url": _MCL + "7u",
     "rule": "Low-income homeowners can apply to their city for a poverty exemption (HOPE in "
             "Detroit) that lowers or erases their property taxes."},
]

# Made-up Detroit houses (address_key -> level) for showing each result card in a demo.
# lookup() answers them itself, so they work offline and never point at a real home.
EXAMPLES = {"1 EXAMPLE": "red", "2 EXAMPLE": "yellow", "3 EXAMPLE": "none", "4 EXAMPLE": "unknown"}

SUFFIXES = {"ST", "STREET", "AVE", "AV", "AVENUE", "RD", "ROAD", "DR", "DRIVE", "BLVD",
            "BOULEVARD", "CT", "COURT", "PL", "PLACE", "LN", "LANE", "HWY", "HIGHWAY",
            "PKWY", "PARKWAY", "TER", "TERRACE", "CIR", "CIRCLE"}
DIRECTIONS = {"NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}

_lock = threading.Lock()
_last = 0.0
_parcels: dict[str, str] | None = None
_parcels_lock = threading.Lock()


def address_key(addr: str) -> str:
    """'17427 Oakland St., Apt 2, Detroit' -> '17427 OAKLAND' (from check_my_addresses.py)."""
    street = addr.upper().split(",")[0]
    street = re.split(r"\s(?:APT|UNIT|#)", street)[0]
    words = re.sub(r"[^A-Z0-9 ]", " ", street).split()
    words = [DIRECTIONS.get(w, w) for w in words]
    while len(words) > 2 and words[-1] in SUFFIXES:
        words.pop()
    return " ".join(words)


def split_city(addr: str) -> tuple[str, str]:
    """'52 Bartlett St Highland Park, MI 48203' -> ('52 BARTLETT ST', '43'). Detroit by default.

    The city is only taken from after a comma or the end of the street part, since
    many streets share a city's name (4305 Trenton is in Detroit).
    """
    street, _, rest = addr.upper().partition(",")
    words = re.sub(r"[^A-Z0-9 ]", " ", street).split()
    rest = f" {' '.join(re.sub(r'[^A-Z0-9 ]', ' ', rest).split())} "
    while len(words) > 2 and (words[-1] in ("MI", "MICHIGAN") or re.fullmatch(r"\d{5}", words[-1])):
        words.pop()
    for name in sorted(MUNICIPALITIES, key=len, reverse=True):
        if f" {name} " in rest:
            return " ".join(words), MUNICIPALITIES[name]
        n = name.split()
        left = words[:-len(n)]
        if (words[-len(n):] == n and len(left) >= 2
                and left[-1] not in ("N", "S", "E", "W", "NORTH", "SOUTH", "EAST", "WEST")):
            return " ".join(left), MUNICIPALITIES[name]
    return " ".join(words), DETROIT


def _money(v: str) -> float:
    return float(re.sub(r"[^0-9.]", "", v or "") or 0)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parcel_for(key: str) -> str | None:
    """Detroit parcel ID for an address_key(), from data/parcels.csv (loaded once)."""
    global _parcels
    with _parcels_lock:
        if _parcels is None:
            _parcels = {}
            if PARCELS.exists():
                with open(PARCELS, newline="", encoding="utf-8") as f:
                    for p in csv.DictReader(f):
                        _parcels.setdefault(address_key(p["address"]), p["parcel_id"])
    return _parcels.get(key)


def _fetch(form: dict, retries: int = 2) -> str:
    global _last
    with _lock:
        wait = MIN_GAP - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.time()
    try:
        resp = requests.post(PTA, data={
            "MUN_CD": DETROIT, "PARCEL_ID": "", "PARCEL_SEARCH_MSG": "",
            "PROP_STREET_NBR": "", "PROP_STREET_NM": "", "frequency": "on", **form,
        }, headers={"User-Agent": "Mozilla/5.0"}, timeout=TIMEOUT)
    except requests.ConnectionError:  # the county's server resets ~1-2% of connections
        if not retries:
            raise
        time.sleep(2)
        return _fetch(form, retries - 1)
    resp.raise_for_status()
    return resp.text


def parse(page: str) -> dict:
    """The county's result page -> {found, address, parcel_id, years, total_due, pay_by}."""
    addr = re.search(r'<label id="PROP_STREET_NBR"[^>]*>([^<]*)</label>', page)
    if not addr:
        return {"found": False}
    parcel = re.search(r"Parcel ID.*?<label[^>]*>\s*([^<]+)", page, re.S)
    owner = re.search(r'<label id="lblTaxPayer1">([^<]*)</label>', page)

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
        "owner": _text(owner.group(1)) or None if owner else None,  # taxpayer; staff/mail only
        "years": years,
        "total_due": _money(total.group(2)) if total else round(sum(y["due"] for y in years), 2),
        "pay_by": total.group(1) if total else None,
    }


def _example(key: str, today: date | None = None) -> dict:
    """parse()-shaped result for an EXAMPLES address, its tax years picked so it lands on its level.

    red needs the next March 31 within 6 months, so it is only red from October to March.
    """
    today = today or date.today()
    level = EXAMPLES[key]
    if level == "unknown":
        return {"found": False}
    judgment = today.year + (today > date(today.year, 3, 31))  # year of the next foreclosure date
    rows = {"red": [(judgment - 3, 1180.40, 742.15, "SUBJECT TO FORECLOSURE"),
                    (judgment - 2, 1205.10, 289.22, "DELINQUENT")],
            "yellow": [(judgment - 2, 612.75, 98.04, "DELINQUENT")],
            "none": []}[level]
    years = [{"year": y, "tax": t, "interest_fees": i, "due": round(t + i, 2), "status": s}
             for y, t, i, s in rows]
    month_end = calendar.monthrange(today.year, today.month)[1]
    return {"found": True, "address": f"{key} ST, DETROIT MI 48201", "parcel_id": None,
            "years": years, "total_due": round(sum(y["due"] for y in years), 2),
            "pay_by": f"{today:%m}/{month_end}/{today.year}" if years else None}


def _long(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


def assess(result: dict, today: date | None = None, detroit: bool = True) -> dict:
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

    claim_by = date(deadline.year, 7, 1)  # MCL 211.78t: July 1 after the foreclosure
    msg = (f"You owe {owed} in back property taxes ({listed}). Under Michigan law (MCL 211.78k), "
           f"if the {oldest} taxes are not paid or put on a payment plan by {_long(deadline)}, "
           f"Wayne County will take ownership of this house. That is {days} days from today.")
    if level != "red" and not forfeited:
        msg += f" Paying before {_long(date(oldest + 2, 3, 1))} avoids extra forfeiture fees."
    if not detroit:
        msg += (" If money is tight, ask your city about its poverty tax exemption and "
                "Pay As You Stay (PAYS), which lowers back taxes.")
    elif today <= HOPE_DEADLINE:
        msg += (f" If money is tight, apply for the HOPE tax exemption by {_long(HOPE_DEADLINE)}; "
                "qualifying also opens Pay As You Stay (PAYS), which lowers back taxes.")
    else:
        msg += " If money is tight, ask about Pay As You Stay (PAYS), which lowers back taxes."
    msg += (" If you own and live here, ask the Wayne County Treasurer (313-224-5990) about IRSPA, "
            "a payment plan with interest cut to 6%."
            f" If you can't pay at all, file a notarized Form 5743 with the Wayne County Treasurer "
            f"by {_long(claim_by)} ({FORM_5743}): if the county sells the house for more than you "
            f"owe, Michigan law (MCL 211.78t) lets you claim the rest.")

    return {**result, "at_risk": True, "level": level, "oldest_year": oldest,
            "deadline": deadline.isoformat(), "days_left": days,
            "surplus_claim_by": claim_by.isoformat(), "surplus_claim_form": FORM_5743,
            "laws": LAWS, "message": msg}


def _cache_key(address: str) -> str:
    street, mun = split_city(address)
    key = address_key(street)
    return key if mun == DETROIT else f"{mun} {key}"


def lookup(address: str) -> dict:
    """Live lookup: address -> assessed result with help links. Raises on network errors."""
    street, mun = split_city(address)
    key = address_key(street)
    detroit = mun == DETROIT
    help_links = HELP if detroit else [h for h in HELP if "HOPE" not in h["name"]]
    m = re.match(r"^(\d{1,6})\s+(.+)$", key)
    if not m:
        return {"query": address, "found": False, "level": "unknown", "at_risk": None,
                "message": "Enter a street address with a house number, like 14390 Dolphin.",
                "help": help_links}
    if detroit and key in EXAMPLES:
        return {"query": address, **assess(_example(key)), "city": "Detroit", "help": help_links,
                "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    parcel = parcel_for(key) if detroit else None  # parcels.csv is Detroit only
    form = ({"PARCEL_ID": parcel, "searchByAddressInd": "ParcelSearch"} if parcel else
            {"MUN_CD": mun, "PROP_STREET_NBR": m.group(1), "PROP_STREET_NM": m.group(2),
             "searchByAddressInd": "AddressSearch"})
    page = _fetch(form)
    result = parse(page)
    if not result["found"]:
        # Several parcels share the address: the county answers with a pick list
        # (JSON in the page). Open each match and keep the one with the most owed.
        grid = re.search(r"var searchGridArray = (\[.*?\]);", page, re.S)
        rows = [r for r in json.loads(grid.group(1))
                if address_key(r.get("PROP_STREET_NM") or "") == key] if grid else []
        pages = [parse(_fetch({"MUN_CD": mun, "PARCEL_ID": r["PARCEL_ID"],
                               "searchByAddressInd": "ParcelSearch"})) for r in rows[:3]]
        result = max(pages, key=lambda r: (r["found"], r.get("total_due") or 0), default=result)
    result = assess(result, detroit=detroit)
    city = next(name for name, code in MUNICIPALITIES.items() if code == mun).title()
    return {"query": address, **result, "city": city, "help": help_links,
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
        CREATE TABLE IF NOT EXISTS postcards (key TEXT, mode TEXT, address TEXT, id TEXT, url TEXT,
                                              expected_delivery TEXT,
                                              sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
                                              PRIMARY KEY (key, mode));
    """)
    return con


def cached_lookup(address: str, max_age_hours: float = CACHE_HOURS) -> dict:
    """lookup() through the SQLite cache, so the demo and the map build don't re-hit the county."""
    key = _cache_key(address)
    con = connect()
    try:
        row = con.execute("SELECT result, checked_at FROM lookups WHERE key = ?", (key,)).fetchone()
        if row and time.time() - row["checked_at"] < max_age_hours * 3600:
            return {**json.loads(row["result"]), "query": address}
        result = lookup(address)
        if result.get("found") and key not in EXAMPLES:  # examples are re-dated on every lookup
            con.execute("INSERT OR REPLACE INTO lookups VALUES (?, ?, ?)",
                        (key, json.dumps(result), time.time()))
            con.commit()
        return result
    finally:
        con.close()


if __name__ == "__main__":
    import sys
    print(json.dumps(lookup(" ".join(sys.argv[1:]) or "14390 Dolphin"), indent=2))
