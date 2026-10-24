"""Download every City of Detroit parcel (with a lat/lon centroid) to data/parcels.csv.

Source: City of Detroit "Parcels (Current)" ArcGIS FeatureServer layer
  https://services2.arcgis.com/qvkbeam7Wirps6zC/arcgis/rest/services/parcel_file_current/FeatureServer/0
(the layer behind data.detroitmi.gov). The Hub bulk CSV export has no coordinates and
includes taxpayer names/addresses, so we page the layer instead, asking the server for a
centroid per parcel (returnCentroid, WGS84) and for only the non-private fields below.

Run:  python backend/fetch_parcels.py        (needs `requests`; ~25 min, 4 requests in flight)
"""
import csv
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

LAYER = "https://services2.arcgis.com/qvkbeam7Wirps6zC/arcgis/rest/services/parcel_file_current/FeatureServer/0/query"
OUT = Path(__file__).resolve().parent.parent / "data" / "parcels.csv"
PAGE = 1000  # layer maxRecordCount
WORKERS = 4
RETRIES = 6
FIELDS = [
    "parcel_id", "address", "street_number", "street_prefix", "street_name", "zip_code",
    "neighborhood", "council_district", "property_class", "property_class_description",
    "pct_pre_claimed", "tax_status", "is_improved",
]
COLUMNS = FIELDS + ["lat", "lon"]
session = requests.Session()


def query(params):
    """GET the layer with retries; ArcGIS reports errors as HTTP 200 + {"error": ...}."""
    params = {**params, "f": "json"}
    for attempt in range(RETRIES):
        try:
            r = session.get(LAYER, params=params, timeout=120)
            r.raise_for_status()
            data = r.json()
            if "error" not in data:
                return data
            err = data["error"]
        except (requests.RequestException, ValueError) as e:
            err = e
        if attempt == RETRIES - 1:
            raise RuntimeError(f"query failed after {RETRIES} tries: {err}")
        time.sleep(2 ** attempt)


def fetch_page(offset):
    data = query({
        "where": "1=1",
        "outFields": ",".join(FIELDS),
        "returnGeometry": "false",
        "returnCentroid": "true",
        "outSR": 4326,
        "orderByFields": "object_id",
        "resultOffset": offset,
        "resultRecordCount": PAGE,
    })
    rows = []
    for feat in data["features"]:
        row = dict(feat["attributes"])
        c = feat.get("centroid") or {}
        row["lat"], row["lon"] = c.get("y"), c.get("x")
        rows.append(row)
    return rows


def main():
    total = query({"where": "1=1", "returnCountOnly": "true"})["count"]
    print(f"service reports {total} parcels", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".csv.tmp")
    written = 0
    with open(tmp, "w", newline="", encoding="utf-8") as f, ThreadPoolExecutor(WORKERS) as pool:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for rows in pool.map(fetch_page, range(0, total, PAGE)):
            w.writerows(rows)
            written += len(rows)
            if written % 50000 < PAGE:
                print(f"  {written}/{total}", flush=True)
    tmp.replace(OUT)
    print(f"wrote {written} rows to {OUT}")
    if written != total:
        sys.exit(f"WARNING: row count {written} != service count {total}")


if __name__ == "__main__":
    main()
