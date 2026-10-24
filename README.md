# Detroit Foreclosure Early-Warning Map

Hack for Humanity: Detroit, Oct 24 2026. Track: neighborhood services / economic mobility / civic data.

Warn Detroit homeowners **before** Wayne County takes their house for unpaid
property taxes, while there's still time to pay, get on a payment plan, or get
the HOPE poverty exemption. A map shows where risk is concentrated (by
neighborhood, never by house), and a lookup with opt-in alerts tells an owner
about *their* house.

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

### Environment

| Variable | For |
|---|---|
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_PHONE` | SMS alerts |
| `RESEND_API_KEY`, `FROM_EMAIL` | Email alerts |
| `LLM_BASE_URL` (default `http://localhost:11434/v1`), `LLM_MODEL` (default `qwen2.5:1.5b`, run `ollama pull qwen2.5:1.5b`), `LLM_API_KEY` | Plain-language letters. Without a model, the API returns the rule-based message. |

### Expose the API to the Lovable front end

Lovable runs in the browser on a public https URL, so it needs a public URL for
the API, for example a Cloudflare quick tunnel (free, no account):

```bash
cloudflared tunnel --url http://localhost:5000
```

Put the printed `https://….trycloudflare.com` URL into `src/config.ts` in Lovable.

## Privacy

- The map only shows neighborhood totals from a sample of owner-occupied homes.
  The API never returns a list of at-risk houses.
- The parcel file keeps no owner names.
- Lookups return what the county's public site already shows for one address.

## Data sources

- Wayne County Treasurer property tax search: pta.waynecounty.com
- City of Detroit Open Data: parcels (`parcel_file_current`) and neighborhoods (`Current_City_of_Detroit_Neighborhoods`)
- Help: Wayne County Treasurer payment plans (313-224-5990), Detroit HOPE exemption (detroitmi.gov/hope), United Community Housing Coalition (313-963-3310)

## License

MIT. See `LICENSE`.
