"""
letter.py: turn a lookup result into a short plain-language letter (what you
owe, your deadline, your next step) in English, Spanish or Arabic, written by
an open-weight model through any OpenAI-compatible endpoint.

  LLM_BASE_URL  default http://localhost:11434/v1   (Ollama)
  LLM_MODEL     default qwen2.5:1.5b (Apache-2.0, ~1 GB, handles Arabic; llama3.1:8b writes better)
  LLM_API_KEY   only for hosted endpoints (Groq, Together, Hugging Face router)

If the model can't be reached, returns the rule-based English message so the
page never breaks.
"""
import json
import os

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
            json={"model": model, "temperature": 0.2, "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Write the letter in {LANGS[lang]}.\nFacts:\n"
                                            + json.dumps(facts, indent=1)},
            ]},
            timeout=90,
        )
        resp.raise_for_status()
        return {"lang": lang, "model": model,
                "letter": resp.json()["choices"][0]["message"]["content"].strip()}
    except Exception as exc:  # noqa: BLE001
        lines = [result["message"], ""] + [
            f"- {h['name']}: {h['phone'] or h['url']}" for h in result.get("help", [])]
        return {"lang": "en", "model": None, "fallback": True, "error": str(exc),
                "letter": "\n".join(lines)}
