# Detroit Foreclosure Early-Warning Map

Hack for Humanity: Detroit, Oct 24 2026. Track: neighborhood services / economic mobility / civic data.

Warn Detroit homeowners **before** Wayne County takes their house for unpaid
property taxes, while there's still time to pay, get on a payment plan, or get
the HOPE poverty exemption. A map shows where risk is concentrated (by
neighborhood, never by house), and a lookup with opt-in alerts tells an owner
about *their* house. Outreach staff can also mail a warning postcard to every
RED home through Lob.

## How the deadline works

Michigan's General Property Tax Act: taxes for year Y become delinquent March 1
of Y+1, forfeited March 1 of Y+2, and **the county takes the house on March 31 of
Y+3** if they're still unpaid. So anyone with unpaid 2024 taxes today has until
**March 31, 2027**.

## Layout

| Path | What it does |
|---|---|
| `backend/lookup.py` | Address to Wayne County delinquent-tax rows (pta.waynecounty.com), then risk level, deadline and a plain-language message. Detroit by default; any Wayne County city named in the address (Highland Park, Hamtramck, …) also works. Cached in SQLite. |
| `backend/fetch_parcels.py` | Downloads every Detroit parcel (City of Detroit Open Data) to `data/parcels.csv`. |
| `backend/build_map.py` | Samples owner-occupied homes per neighborhood, looks each up (throttled), and aggregates by neighborhood for the map. |
| `backend/letter.py` | Plain-language letter in English, Spanish or Arabic from an **open-weight model** (Qwen 2.5 via Ollama, or any OpenAI-compatible host). |
| `backend/notify.py` | SMS (Twilio) and email (Resend) alerts. `python notify.py` re-checks every sign-up. |
| `backend/mailer.py` | Staff-only list of RED homes, and warning postcards to them through Lob's print-and-mail API. |
| `backend/app.py` | Flask JSON API used by the front end. |
| `LOVABLE_PROMPT.md` | Front-end spec and API contract to paste into Lovable. |

## Run it

```bash
pip install -r requirements.txt
cd backend
python fetch_parcels.py                 # once: data/parcels.csv
python build_map.py --top 30 --per 25   # ~750 lookups, about 10 minutes
python app.py                           # http://localhost:5000
```

Try it: `http://localhost:5000/api/lookup?address=14325 Rockdale`

For a demo, `1 Example St` through `4 Example St` are made-up houses that show
each result card (act now, unpaid taxes, paid up, not found) without calling the
county. Orange (forfeited) can only happen from April to September: from October
to March every forfeited home is already within 6 months of its March 31 deadline.

### Environment

| Variable | For |
|---|---|
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_PHONE` | SMS alerts |
| `RESEND_API_KEY`, `FROM_EMAIL` | Email alerts |
| `LLM_BASE_URL` (default `http://localhost:11434/v1`), `LLM_MODEL` (default `qwen2.5:1.5b`, run `ollama pull qwen2.5:1.5b`), `LLM_API_KEY` | Plain-language letters. Without a model, the API returns the rule-based message. |
| `STAFF_KEY` | Turns on the staff endpoints (`/api/staff/...`); staff send it as the `X-Staff-Key` header. Unset, they answer 401. |
| `LOB_API_KEY`, `LOB_FROM` (optional) | Postcards. A `test_` key (free at lob.com) makes a PDF proof of each card and mails nothing; a `live_` key prints and mails. `LOB_FROM` is a return address ID (`adr_…`) saved in the Lob dashboard. |

### Mail postcards to RED homes

The staff list holds every RED home checked so far (the map sample plus any
lookup), soonest deadline first. Run `build_map.py` with a bigger `--per` to
check more homes. Before mailing, each home is re-checked (if its record is more
than a day old) so nobody who just paid gets a card, and a home that already got
a card is skipped. Cards go to "Homeowner" at the house, give the deadline and
the free-help numbers, and leave out the amount owed. The Lovable `/staff` page
does all of this; from a terminal:

```bash
curl -H "X-Staff-Key: $STAFF_KEY" http://localhost:5000/api/staff/red
curl -X POST -H "X-Staff-Key: $STAFF_KEY" -H "Content-Type: application/json" -d '{"keys": ["1234 EXAMPLE"]}' http://localhost:5000/api/staff/postcards
```

### Expose the API to the Lovable front end

Lovable runs in the browser on a public https URL, so it needs a public URL for
the API, for example a Cloudflare quick tunnel (free, no account):

```bash
cloudflared tunnel --url http://localhost:5000
```

Put the printed `https://….trycloudflare.com` URL into `src/config.ts` in Lovable.

## Privacy

- The map only shows neighborhood totals from a sample of owner-occupied homes.
  The public API never returns a list of at-risk houses. Only the staff
  endpoints list RED homes, for mailing, and they're off unless `STAFF_KEY` is set.
- Postcards can be read by anyone who handles them, so they go to "Homeowner"
  and don't show the amount owed.
- The parcel file keeps no owner names.
- Lookups return what the county's public site already shows for one address.

## Data sources

- Wayne County Treasurer property tax search: pta.waynecounty.com
- City of Detroit Open Data: parcels (`parcel_file_current`) and neighborhoods (`Current_City_of_Detroit_Neighborhoods`)
- Help: Wayne County Treasurer payment plans (313-224-5990), Detroit HOPE exemption (detroitmi.gov/hope), United Community Housing Coalition (313-963-3310)

## License

MIT. See `LICENSE`.
