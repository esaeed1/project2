"""
build_map.py: sample owner-occupied homes in each neighborhood from
data/parcels.csv (made by fetch_parcels.py), look each one up (throttled, cached
in data/app.db), and aggregate by neighborhood for /api/map. Results are only
shown per neighborhood, never per house, so the map can't be used as a
shopping list by speculators.

    python build_map.py --top 30 --per 25                  # 30 largest neighborhoods
    python build_map.py --neighborhoods Brightmoor Warrendale --per 100
"""
import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests

from lookup import DATA, address_key, cached_lookup, connect

PARCELS = DATA / "parcels.csv"
NEIGHBORHOODS = DATA / "neighborhoods.geojson"
NBHD_URL = ("https://services2.arcgis.com/qvkbeam7Wirps6zC/arcgis/rest/services/"
            "Current_City_of_Detroit_Neighborhoods/FeatureServer/0/query")
# % of sampled homes whose foreclosure deadline is within 6 months -> fill color
COLORS = [(30, "#a50f15"), (20, "#de2d26"), (10, "#fb6a4a"), (5, "#fcae91"), (0, "#fee5d9")]


def owner_occupied_homes() -> dict[str, list[dict]]:
    by_nbhd = defaultdict(list)
    with open(PARCELS, newline="", encoding="utf-8") as f:
        for p in csv.DictReader(f):
            if (str(p["property_class"]).split(".")[0] == "401"
                    and float(p["pct_pre_claimed"] or 0) == 100
                    and p["neighborhood"] and p["address"] and p["lat"]):
                by_nbhd[p["neighborhood"]].append(p)
    return by_nbhd


def sample(names: list[str], per: int, workers: int) -> None:
    con = connect()
    todo = []
    by_nbhd = owner_occupied_homes()
    for name in names:
        homes = by_nbhd.get(name, [])
        for p in random.Random(name).sample(homes, min(per, len(homes))):
            con.execute("INSERT OR IGNORE INTO homes VALUES (?, ?, ?, ?, ?)",
                        (p["parcel_id"], address_key(p["address"]), name, float(p["lat"]), float(p["lon"])))
            todo.append(p["address"])
    con.commit()
    con.close()

    def one(addr):
        try:
            return cached_lookup(addr, max_age_hours=24 * 7)["level"]
        except Exception as exc:  # noqa: BLE001
            return f"error: {exc}"

    with ThreadPoolExecutor(workers) as pool:
        for i, (addr, level) in enumerate(zip(todo, pool.map(one, todo)), 1):
            print(f"[{i}/{len(todo)}] {addr}: {level}", flush=True)


def neighborhood_shapes() -> dict:
    for attempt in range(3):  # ArcGIS sometimes drops the connection; fetched once, then cached
        if NEIGHBORHOODS.exists():
            break
        try:
            resp = requests.get(NBHD_URL, params={
                "where": "1=1", "outFields": "nhood_name", "outSR": 4326,
                "geometryPrecision": 5, "maxAllowableOffset": 0.0001, "f": "geojson"}, timeout=60)
            resp.raise_for_status()
            NEIGHBORHOODS.write_text(resp.text, encoding="utf-8")
        except requests.RequestException:
            if attempt == 2:
                raise
    return json.loads(NEIGHBORHOODS.read_text(encoding="utf-8"))


def map_data() -> dict:
    """Neighborhood polygons with risk stats, as a GeoJSON FeatureCollection."""
    con = connect()
    rows = con.execute("SELECT h.neighborhood, l.result, l.checked_at FROM homes h "
                       "JOIN lookups l ON l.key = h.key").fetchall()
    con.close()
    by_nbhd = defaultdict(list)
    for r in rows:
        by_nbhd[r["neighborhood"]].append(json.loads(r["result"]))

    features = []
    for f in neighborhood_shapes()["features"]:
        name = f["properties"]["nhood_name"]
        homes = by_nbhd.get(name)
        if not homes:
            continue
        n, levels = len(homes), Counter(h["level"] for h in homes)
        pct_red = round(100 * levels["red"] / n)
        features.append({"type": "Feature", "geometry": f["geometry"], "properties": {
            "name": name, "checked": n, "at_risk": n - levels["none"],
            "red": levels["red"], "orange": levels["orange"], "yellow": levels["yellow"],
            "pct_at_risk": round(100 * (n - levels["none"]) / n), "pct_red": pct_red,
            "total_owed": round(sum(h["total_due"] for h in homes if h.get("at_risk"))),
            "color": next(c for t, c in COLORS if pct_red >= t),
        }})

    props = [f["properties"] for f in features]
    return {"type": "FeatureCollection", "features": features, "summary": {
        "neighborhoods": len(features),
        "checked": sum(p["checked"] for p in props),
        "at_risk": sum(p["at_risk"] for p in props),
        "red": sum(p["red"] for p in props),
        "total_owed": sum(p["total_owed"] for p in props),
        "legend": [{"min_pct_red": t, "color": c} for t, c in COLORS],
    }}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--neighborhoods", nargs="+", help="neighborhood names as in parcels.csv")
    ap.add_argument("--top", type=int, default=0, help="or: the N neighborhoods with the most owner-occupied homes")
    ap.add_argument("--per", type=int, default=25, help="homes sampled per neighborhood")
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()
    if args.neighborhoods:
        names = args.neighborhoods
    else:
        homes = owner_occupied_homes()
        names = sorted(homes, key=lambda k: -len(homes[k]))[:args.top or len(homes)]
    sample(names, args.per, args.workers)
    s = map_data()["summary"]
    print(f"\n{s['checked']} homes checked in {s['neighborhoods']} neighborhoods: "
          f"{s['at_risk']} owe back taxes, {s['red']} face foreclosure within 6 months, "
          f"${s['total_owed']:,} owed.")
