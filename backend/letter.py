"""
letter.py: turn a lookup result into a short plain-language letter (what you
owe, your deadline, your next step) in English, Spanish or Arabic, written by
an open-weight model through any OpenAI-compatible endpoint.

  LLM_BASE_URL  default http://localhost:11434/v1   (Ollama)
  LLM_MODEL     default qwen2.5:1.5b (Apache-2.0, ~1 GB, handles Arabic; llama3.1:8b writes better)
  LLM_API_KEY   only for hosted endpoints (Groq, Together, Hugging Face router)

If the model can't be reached, or writes a dollar amount or phone number that
isn't in the facts, returns the rule-based English message so the page never
breaks or misleads.
"""
import json
import os
import re

import requests

LANGS = {"en": "English", "es": "Spanish", "ar": "Arabic"}

SYSTEM = (
    "You write short, warm letters to Detroit homeowners about unpaid property taxes, at a "
    "6th-grade reading level. Use ONLY the facts given; never invent amounts, dates, names, laws "
    "or phone numbers. Say what they owe and the date the county takes the house if nothing is "
    "done, naming the Michigan law behind that date. Then the next steps: call the Wayne County "
    "Treasurer for a payment plan (IRSPA if they live in the house), apply for the Detroit HOPE "
    "exemption if money is tight (it also opens Pay As You Stay, which lowers back taxes), and "
    "call UCHC for free help. If surplus_claim_by is given, end with: if they can't pay at all, "
    "file the notarized Form 5743 (link: surplus_claim_form) with the Wayne County Treasurer by "
    "that date, so they can claim any money left over if the county sells the house. "
    "Under 200 words. No subject line, no placeholders like [Name]."
)


MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)")
PHONE = re.compile(r"\(?\b(\d{3})\)?[-.\s]?(\d{3})[-.\s](\d{4})\b")


def _invented(text: str, result: dict) -> list[str]:
    """Dollar amounts and phone numbers in the letter that aren't in the lookup result."""
    amounts = {round(result.get("total_due") or 0, 2)} | {
        round(y[k], 2) for y in result.get("years", []) for k in ("tax", "interest_fees", "due")}
    amounts |= {round(float(a.replace(",", "")), 2) for a in MONEY.findall(result.get("message", ""))}
    phones = {re.sub(r"\D", "", h["phone"]) for h in result.get("help", []) if h.get("phone")}
    phones |= {"".join(p) for p in PHONE.findall(result.get("message", ""))}
    return ([f"${a}" for a in MONEY.findall(text) if round(float(a.replace(",", "")), 2) not in amounts]
            + ["-".join(p) for p in PHONE.findall(text) if "".join(p) not in phones])


def letter(result: dict, lang: str = "en") -> dict:
    lang = lang if lang in LANGS else "en"
    facts = {k: result.get(k) for k in
             ("address", "at_risk", "total_due", "years", "deadline", "days_left",
              "surplus_claim_by", "surplus_claim_form", "message")}
    facts["laws"] = [{k: law[k] for k in ("cite", "rule")} for law in result.get("laws", [])]
    facts["help"] = [{k: h[k] for k in ("name", "phone", "url", "note")} for h in result.get("help", [])]
    model = os.environ.get("LLM_MODEL", "qwen2.5:1.5b")
    try:
        resp = requests.post(
            os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {os.environ.get('LLM_API_KEY', 'ollama')}"},
            json={"model": model, "temperature": 0.2, "max_tokens": 600, "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Write the letter in {LANGS[lang]}.\nFacts:\n"
                                            + json.dumps(facts, indent=1)},
            ]},
            timeout=120,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        # small models still write "Dear [Name]" / "[Your Name]" lines: drop them
        text = "\n".join(l for l in text.splitlines() if not re.search(r"\[[^\]]+\]", l)).strip()
        bad = _invented(text, result)
        if bad:
            raise ValueError(f"model wrote amounts or phone numbers not in the record: {bad}")
        return {"lang": lang, "model": model, "letter": text}
    except Exception as exc:  # noqa: BLE001
        lines = [result["message"], ""] + [
            f"- {h['name']}: {h['phone'] or h['url']}" for h in result.get("help", [])]
        return {"lang": "en", "model": None, "fallback": True, "error": str(exc),
                "letter": "\n".join(lines)}
