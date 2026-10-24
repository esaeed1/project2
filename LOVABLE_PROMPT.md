# Prompt for Lovable

Paste everything below the line into Lovable. Replace `API_URL` with the public
URL of the Flask backend (see README, "Expose the API").

---

Build a mobile-first, single-page web app called **"Keep Your Home Detroit"**: a
foreclosure early-warning tool for Detroit homeowners. It warns people who owe
back property taxes **before** Wayne County takes their house, and connects them
to free help. Audience: older Detroit homeowners on phones. Use plain language,
large text (18px+ body), high contrast and big tap targets. Tone: calm and
helpful, not scary. No login.

All data comes from an existing JSON API. Put the base URL in one constant,
`src/config.ts`: `export const API_URL = "API_URL";`. Every endpoint allows CORS.
While the API is unreachable, show a friendly error ("We can't reach the tax
records right now. Try again in a minute.") and never crash.

## Page layout (top to bottom)

1. **Hero + address lookup.** Headline: "Is your house at risk of tax foreclosure?"
   One input ("Your street address, e.g. 1234 Example St") and a "Check my
   house" button. Call `GET {API_URL}/api/lookup?address=<urlencoded>`. It can
   take up to 5 seconds, so show a spinner reading "Checking Wayne County tax records…".
2. **Result card** (shown after a lookup). See "Result card".
3. **Map** of risk by neighborhood. See "Map".
4. **Get alerts** sign-up form. See "Alerts".
5. **Free help**: three cards from `GET {API_URL}/api/help`.
6. Footer: "Data: Wayne County Treasurer and City of Detroit Open Data. Not legal
   advice. Open source." and a link to the GitHub repo.

A language switch in the header (English / Español / العربية) sets `lang` = `en` | `es` | `ar`.
For Arabic, set `dir="rtl"` on the page. Translate the UI strings; the API's
`message` stays in English, and the translated version comes from the letter endpoint.

## Result card: `GET /api/lookup?address=...`

Response:

```json
{
  "query": "1234 example st",
  "found": true,
  "address": "1234 EXAMPLE, DETROIT MI 48223",
  "parcel_id": "22000000.",
  "at_risk": true,
  "level": "red",
  "total_due": 2140.0,
  "pay_by": "10/31/2026",
  "oldest_year": 2024,
  "deadline": "2027-03-31",
  "days_left": 158,
  "years": [
    {"year": 2024, "tax": 938.53, "interest_fees": 609.10, "due": 1547.63, "status": "SUBJECT TO FORECLOSURE"},
    {"year": 2025, "tax": 450.00, "interest_fees": 142.37, "due": 592.37, "status": "DELINQUENT"}
  ],
  "message": "You owe $2,140.00 in back property taxes (2024, 2025). If the 2024 taxes are not paid or put on a payment plan by March 31, 2027, Wayne County will take ownership of this house. That is 158 days from today.",
  "help": [{"name": "...", "phone": "313-224-5990", "url": "https://...", "note": "..."}],
  "checked_at": "2026-10-24T11:02:13"
}
```

`level` drives the card's color and headline:

| level | color | headline |
|---|---|---|
| `red` | #b91c1c | "Act now: foreclosure deadline in {days_left} days" |
| `orange` | #c2410c | "Your taxes are forfeited" |
| `yellow` | #a16207 | "You have unpaid back taxes" |
| `none` | #15803d | "No back taxes found" (`at_risk` is false) |
| `unknown` | gray | show `message` (`found` is false: address not in county records) |

When `at_risk` is true, show:
- a large countdown: **{days_left} days** until {deadline formatted as "March 31, 2027"}
- "You owe **${total_due}** (if paid by {pay_by})"
- `message` as the main paragraph
- a small table of `years` (Year, Tax, Interest & fees, Amount due, Status)
- primary button **"Get alerts for this house"**, which scrolls to the Alerts form with the address filled in
- secondary button **"Explain this in plain language"**, which calls the letter endpoint in the current language
- the help cards from `help`, with `tel:` links on phone numbers

## Plain-language letter: `GET /api/letter?address=...&lang=en|es|ar`

```json
{"lang": "es", "model": "llama3.1:8b", "letter": "Estimado propietario: ..."}
```

The letter is written by an open-source AI model, which can take 10–30 seconds,
so show a spinner. Render `letter` as paragraphs (split on blank lines). If
`model` is set, show a small caption: "Written by {model}, an open-source AI
model. Check the amounts above." If `fallback` is true, show the letter with no
caption.

## Map: `GET /api/map`

Returns a GeoJSON FeatureCollection of Detroit neighborhoods, plus a top-level `summary`:

```json
{
  "type": "FeatureCollection",
  "features": [{
    "type": "Feature",
    "geometry": {"type": "Polygon", "coordinates": [[[-83.27, 42.40], "..."]]},
    "properties": {"name": "Example Park", "checked": 25, "at_risk": 9, "red": 4,
                   "orange": 0, "yellow": 5, "pct_at_risk": 36, "pct_red": 16,
                   "total_owed": 14200, "color": "#fb6a4a"}
  }],
  "summary": {"neighborhoods": 30, "checked": 750, "at_risk": 210, "red": 95,
              "total_owed": 512000,
              "legend": [{"min_pct_red": 30, "color": "#a50f15"}, {"min_pct_red": 20, "color": "#de2d26"},
                         {"min_pct_red": 10, "color": "#fb6a4a"}, {"min_pct_red": 5, "color": "#fcae91"},
                         {"min_pct_red": 0, "color": "#fee5d9"}]}
}
```

- Use **react-leaflet** with OpenStreetMap tiles (no API key), centered on Detroit
  `[42.36, -83.10]`, zoom 11, about 420px tall on mobile.
- Draw `features` with `fillColor = properties.color`, `fillOpacity 0.7`, a white 1px border.
- On tap, show a popup: **{name}**, "{pct_red}% of homes checked face foreclosure
  within 6 months", "{pct_at_risk}% owe back taxes", "${total_owed} owed among {checked} homes checked".
- Above the map, a stat row from `summary`: homes checked, owe back taxes,
  deadline within 6 months, total owed.
- Legend from `summary.legend`: "% of homes facing foreclosure within 6 months".
- Caption: "Based on a sample of owner-occupied homes. Shown by neighborhood
  only, never by house, to protect privacy." **Never draw individual houses or pins.**

## Alerts: `POST /api/signup`

Form fields: address (prefilled from the lookup), mobile phone, email (phone or
email is required), and a required consent checkbox: "Text or email me about this
address's tax status. Msg & data rates may apply. Reply STOP to opt out."

Request body: `{"address": "1234 Example St", "phone": "3135550100", "email": "", "lang": "en"}`

Success (200):
```json
{"ok": true, "status": { "...same shape as /api/lookup..." }, "sent": {"sms": true, "email": false}}
```
Show: "You're signed up. We'll text you if anything changes and as the deadline
gets close." If `sent.sms` or `sent.email` is true, add: "We just sent your first alert."

Errors (400 / 404 / 502) return `{"error": "human-readable message"}`; show `error`
under the form.

## Help: `GET /api/help`

```json
[{"name": "Wayne County Treasurer: pay or start a payment plan", "phone": "313-224-5990",
  "url": "https://pta.waynecounty.com/", "note": "Owner-occupants can get IRSPA (5-year plan, 6% interest) or REGSPA."}]
```
Render each as a card: name, note, a "Call" button (`tel:`) when `phone` is set, and a "Website" link.
