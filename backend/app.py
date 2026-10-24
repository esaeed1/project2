"""
app.py: JSON API for the Lovable front end.

  GET  /api/lookup?address=14390 Dolphin           risk for one address
  GET  /api/letter?address=...&lang=en|es|ar        plain-language letter (open-weight LLM)
  GET  /api/map                                     neighborhoods GeoJSON with risk stats
  POST /api/signup {address, phone?, email?, lang?} save an alert sign-up and send the first alert
  GET  /api/help                                    help links

    python app.py          # http://localhost:5000  (PORT overrides)
"""
import os
import re

import requests
from flask import Flask, jsonify, request

from build_map import map_data
from letter import letter
from lookup import HELP, cached_lookup, connect, parcel_for
from notify import notify

app = Flask(__name__)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.after_request
def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


@app.errorhandler(requests.RequestException)
def county_down(exc):
    return jsonify(error="Wayne County's tax site didn't answer. Try again in a minute."), 502


def _phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    digits = "1" + digits if len(digits) == 10 else digits
    return "+" + digits if len(digits) == 11 and digits[0] == "1" else None


@app.get("/api/lookup")
def api_lookup():
    address = request.args.get("address", "").strip()
    if not address:
        return jsonify(error="address is required"), 400
    return jsonify(cached_lookup(address))


@app.get("/api/letter")
def api_letter():
    address = request.args.get("address", "").strip()
    if not address:
        return jsonify(error="address is required"), 400
    return jsonify(letter(cached_lookup(address), request.args.get("lang", "en")))


@app.get("/api/map")
def api_map():
    return jsonify(map_data())


@app.get("/api/help")
def api_help():
    return jsonify(HELP)


@app.post("/api/signup")
def api_signup():
    body = request.get_json(silent=True) or {}
    address = (body.get("address") or "").strip()
    phone = _phone(body.get("phone") or "") if body.get("phone") else None
    email = (body.get("email") or "").strip() or None
    if body.get("phone") and not phone:
        return jsonify(error="Enter a 10-digit US phone number."), 400
    if email and not EMAIL.match(email):
        return jsonify(error="Enter a valid email address."), 400
    if not address or not (phone or email):
        return jsonify(error="An address and a phone number or email are required."), 400

    result = cached_lookup(address)
    if not result.get("found"):
        return jsonify(error=result["message"]), 404
    con = connect()
    con.execute("INSERT INTO signups (address, phone, email, lang, last_level) VALUES (?, ?, ?, ?, ?)",
                (result["address"], phone, email, body.get("lang", "en"), result["level"]))
    con.commit()
    con.close()
    sent = notify(phone, email, result)
    return jsonify(ok=True, status=result, sent={k: v.get("success") for k, v in sent.items()})


if __name__ == "__main__":
    parcel_for("")  # load the parcel index now, not on the first visitor's lookup
    app.run(port=int(os.environ.get("PORT", 5000)))
