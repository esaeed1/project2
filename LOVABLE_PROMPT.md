# Prompt for Lovable

Paste everything below the line into Lovable. Replace `API_URL` with the public
URL of the Flask backend (see README, "Expose the API").

Already built it and don't like the look? In the same Lovable project, paste the
"Look and feel" section with this line in front: "Redesign the whole app to match
the spec below. Keep every feature, route, API call, mock mode, translation and
the /staff page working exactly as now. Rebuild the markup and styles from
scratch instead of tweaking the current ones."

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

**Mock mode:** if `API_URL` is an empty string, don't call the network. Return
the example responses below (after a 600 ms delay) so the whole UI can be built
and previewed before the API is online. For the map mock, draw 3 made-up
neighborhood polygons around Detroit with different `color` values.

## Look and feel

It should feel like a trustworthy public notice, like a well-made city newspaper
or a GOV.UK service page. It should not look like a tech startup template.

- **Colors.** Set the shadcn theme variables in `src/index.css`: page background
  warm paper `#FAF7F2`, cards white with a 1px `#E7E1D6` border, text `#1C1917`,
  secondary text `#57534E`. One accent for buttons and links: navy `#1E3A5F`
  (hover `#162C48`). Red, orange, yellow and green mean risk levels only. Never
  use them for decoration.
- **Type.** Headings: "Source Serif 4", weight 600. Body and UI: "Atkinson
  Hyperlegible" (made for low-vision readers), 19px, line-height 1.6. Arabic:
  "Noto Naskh Arabic". Load them from Google Fonts. Amounts and day counts use
  tabular figures.
- **Layout.** One column, max width 680px, centered, 20px side padding; only the
  map may widen to 960px. Separate sections with 64px of space and a thin rule,
  not colored bands. On a 375px-wide phone, the headline, address field and
  button must all show without scrolling. No hero image.
- **Header.** A plain serif wordmark "Keep Your Home Detroit", and the language
  switch as three always-visible text buttons: English · Español · العربية (the
  current one underlined). No hamburger menu.
- **Fields and buttons.** 56px tall, full width on phones, 8px radius. Every
  field has a visible label above it, not just a placeholder. Focus: 3px navy
  outline, 2px offset.
- **Result card.** Make it look like an official notice: a white card with an 8px
  `border-inline-start` in the level color, a small uppercase label in that color
  (ACT NOW, TAXES FORFEITED, UNPAID TAXES, PAID UP), then the headline. Days left
  as a 64px serif number. Show the help cards as a numbered "What you can do"
  list (1, 2, 3) with Call buttons. On phones, show each tax year as a small
  stacked block instead of a sideways-scrolling table.
- **Map.** A stat row of four plain numbers with labels (2×2 on phones, no icons).
- **Icons.** Only where they carry meaning (phone, external link, expand
  chevron): lucide-react, 20px. No emoji.
- **Motion.** Only the spinners and a 150ms fade when the result appears. Respect
  `prefers-reduced-motion`.
- **Don't use:** gradients, glassmorphism, blurred blobs, shadows heavier than
  `0 1px 2px rgba(0,0,0,.06)`, dark mode, purple, stock photos, illustrations,
  testimonials or "trusted by" sections, made-up statistics, animated number
  counters, carousels, or toast popups (show errors inline).
- **Accessibility.** WCAG AA contrast, tap targets of at least 48px,
  `aria-live="polite"` on the result area, `<html lang>` matches the language
  switch. In Arabic the whole layout mirrors.

## Page layout (top to bottom)

1. **Hero + address lookup.** Headline: "Is your house at risk of tax foreclosure?"
   One input ("Your street address, e.g. 1234 Example St") and a "Check my
   house" button. Call `GET {API_URL}/api/lookup?address=<urlencoded>`. It can
   take up to 5 seconds, so show a spinner reading "Checking Wayne County tax records…".
   Under the button, a row of small chips labeled "Try an example:" — **Act now**
   (`1 Example St`), **Unpaid taxes** (`2 Example St`), **Paid up** (`3 Example St`),
   **Not found** (`4 Example St`). Tapping one fills the input with that address and
   runs the same lookup. These are made-up houses the API answers itself.
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
  "surplus_claim_by": "2027-07-01",
  "surplus_claim_form": "https://www.michigan.gov/taxes/-/media/Project/Websites/taxes/Forms/Property-Tax/5743.pdf",
  "laws": [
    {"cite": "MCL 211.78k", "url": "https://www.legislature.mi.gov/Laws/MCL?objectName=mcl-211-78k",
     "rule": "If the taxes are not paid by the March 31 after the court's foreclosure judgment, the county takes the title and you can no longer pay to keep the house."},
    {"cite": "MCL 211.78t", "url": "https://www.legislature.mi.gov/Laws/MCL?objectName=mcl-211-78t",
     "rule": "If the county sells the house for more than you owed (plus its costs and a 5% fee), you can claim the rest, but only if you file a notarized Form 5743 by the July 1 after the foreclosure."}
  ],
  "message": "You owe $2,140.00 in back property taxes (2024, 2025). Under Michigan law (MCL 211.78k), if the 2024 taxes are not paid or put on a payment plan by March 31, 2027, Wayne County will take ownership of this house. That is 158 days from today. If money is tight, apply for the HOPE tax exemption by November 6, 2026; qualifying also opens Pay As You Stay (PAYS), which lowers back taxes. If you own and live here, ask the Wayne County Treasurer (313-224-5990) about IRSPA, a payment plan with interest cut to 6%. If you can't pay at all, file a notarized Form 5743 with the Wayne County Treasurer by July 1, 2027 (https://www.michigan.gov/taxes/-/media/Project/Websites/taxes/Forms/Property-Tax/5743.pdf): if the county sells the house for more than you owe, Michigan law (MCL 211.78t) lets you claim the rest.",
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
- a **"Can't pay at all?"** box: "File Form 5743 by {surplus_claim_by formatted as
  "July 1, 2027"} so you can claim any money left over if the county sells the house.
  It must be notarized and sent to the Wayne County Treasurer by certified mail or
  delivered in person." with a **"Get Form 5743"** button linking to `surplus_claim_form`
- a collapsible **"What the law says"** list from `laws`: each `cite` as a link to
  `url`, then `rule`. (The lookup returns five laws; the example above shows two.)

## Plain-language letter: `GET /api/letter?address=...&lang=en|es|ar`

```json
{"lang": "es", "model": "qwen2.5:1.5b", "letter": "Estimado propietario: ..."}
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

- Use **react-leaflet** with the light CARTO Positron basemap so the red shading
  stands out (no API key):
  `https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png`, attribution
  "© OpenStreetMap contributors © CARTO". Center on Detroit `[42.36, -83.10]`,
  zoom 11, about 420px tall on mobile.
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
  "url": "https://pta.waynecounty.com/", "note": "Owner-occupants can get IRSPA (5-year plan, 6% interest) or REGSPA. Hardship? Ask about DOOE, an extension, and Pay As You Stay (PAYS), which lowers back taxes."}]
```
Render each as a card: name, note, a "Call" button (`tel:`) when `phone` is set, and a "Website" link.

## Staff page: `/staff` (never linked from the public page)

A separate route where the outreach team mails warning postcards to RED homes
through Lob, a print-and-mail service. Desktop-first table, same colors.

1. Ask for the staff key (password field "Staff key", button "Open"). Keep it in
   `sessionStorage` and send it as the header `X-Staff-Key` on both calls below.
   On a 401, clear it and ask again ("Wrong staff key").
2. `GET {API_URL}/api/staff/red`:

```json
{
  "mailer": "test",
  "homes": [
    {"key": "1234 EXAMPLE", "address": "1234 EXAMPLE, DETROIT MI 48223", "parcel_id": "22000000.",
     "owner": "SAMPLE, JANE", "mail_to": "Jane Sample",
     "total_due": 2140.0, "deadline": "2027-03-31", "days_left": 158,
     "checked_at": "2026-10-24T11:02:13", "postcard": null},
    {"key": "5678 EXAMPLE", "address": "5678 EXAMPLE, DETROIT MI 48228", "parcel_id": "22000001.",
     "owner": "EXAMPLE HOLDINGS LLC", "mail_to": "Homeowner",
     "total_due": 3410.5, "deadline": "2027-03-31", "days_left": 158,
     "checked_at": "2026-10-24T10:40:02",
     "postcard": {"id": "psc_123", "url": "https://lob-assets.com/...pdf",
                  "expected_delivery": "2026-10-30", "sent_at": "2026-10-24 16:16:20"}}
  ]
}
```

- A banner from `mailer`: `"test"` amber, "Test mode: Lob makes a PDF proof of each
  card and mails nothing."; `"live"` red, "Live: cards are printed and mailed.";
  `null` gray, "No mailer connected. Set LOB_API_KEY on the server.", and disable mailing.
- Above the table: "{homes.length} homes face foreclosure within 6 months · {n} mailed".
- Table columns: checkbox, Mail to, Address, Days left, Owed, Last checked, Postcard.
  Mail to shows `mail_to` in bold (the name printed on the card; "Homeowner" when the
  county lists a company, trust, estate or the Land Bank) with `owner` under it in
  small gray text, as the county lists it. Postcard
  shows "Mailed {sent_at as a date}, arrives about {expected_delivery}" and a
  "View card" link to `postcard.url` (the PDF proof, new tab), or "Not mailed".
  Homes with a postcard can't be selected.
- A "Select all not mailed" checkbox and a sticky button "Mail {n} postcards". It
  asks first: "Mail {n} postcards through Lob?" (live mode adds "Real cards will be
  printed and mailed.").
3. `POST {API_URL}/api/staff/postcards` with body `{"keys": [...]}`, the `key` of each
   selected home. Many homes can take a minute: show "Sending to Lob…".

```json
{"mailer": "test", "results": [
  {"key": "1234 EXAMPLE", "address": "1234 EXAMPLE, DETROIT MI 48223", "ok": true,
   "mail_to": "Jane Sample", "lang": "es",
   "postcard": {"id": "psc_456", "url": "https://lob-assets.com/...pdf", "expected_delivery": "2026-10-30"}},
  {"key": "9012 EXAMPLE", "address": "9012 EXAMPLE, DETROIT MI 48204", "ok": false,
   "error": "No longer RED (now none)."}
]}
```

Show "{ok count} postcards sent" with one line per card: "{address}: to {mail_to},
in {English | English and Spanish | English and Arabic}" (`lang` en / es / ar) and a
"View card" link. List each failure with its address and `error`, then reload the
list. Errors (400 / 401 / 503) return `{"error": "..."}`.

Under the table, a note: "Each card is addressed to the owner by name and never
shows the amount owed. Where 5% or more of the people in the house's census tract
speak Spanish or Arabic and have limited English, the card is printed in English
and that language." Owner names appear only on `/staff`, never on the public page.

In mock mode, return the example list above (with `mailer: "test"`), and answer a
send by marking those homes mailed with `url: "#"`.
