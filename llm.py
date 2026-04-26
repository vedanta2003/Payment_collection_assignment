"""Thin OpenAI wrapper.

Single responsibility: extract_fields parses free-form user text into
structured fields. Used for date-of-birth normalization (e.g. "29 Feb 1988"
→ "1988-02-29") and natural-language card expiry parsing (e.g. "Dec 2027").

Business logic (state, verification, retries) never touches this file.
Account data never enters any prompt.
"""
from __future__ import annotations
import json
import os
import logging
from openai import OpenAI

log = logging.getLogger("payassist")

MODEL = "gpt-4o-mini"

_client = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable not set.")
        _client = OpenAI(api_key=api_key)
    return _client


def extract_fields(user_input: str, expected_fields: list[str], context: str = "") -> dict:
    """Extract structured fields from free-form user text.

    Returns a dict with keys from `expected_fields`.
    Missing fields are None. Never raises — returns empty dict on failure.

    Currently called for two purposes:
      - DOB normalization: caller has already determined the input is date-shaped
        (contains non-digit characters), and just needs YYYY-MM-DD output.
      - Expiry parsing: caller's regex couldn't match, so the input is likely
        natural language like "december 2027" or "Dec 27".
    """
    fields_desc = ", ".join(expected_fields)
    prompt = f"""Extract the following fields from the user message below.
Return ONLY a valid JSON object with these keys: {fields_desc}
If a field is not present or unclear, use null.

Rules:
- dob: a date of birth in any format (e.g. "1990-05-14", "14 May 1990", "29 Feb 1988").
  Return as YYYY-MM-DD. Return null if the date is not a real calendar date —
  for example, 29 Feb in a non-leap year, or month > 12.
- expiry_month: integer 1-12. Accept month names ("December" → 12, "Jan" → 1).
- expiry_year: 4-digit integer. Expand 2-digit years ("27" → 2027).

{f"Context: {context}" if context else ""}

User message: "{user_input}"

Return only the JSON object, no explanation, no markdown."""

    try:
        log.info(f"[LLM] extract_fields → fields: {fields_desc}")
        resp = get_client().chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=80,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw.strip("```json").strip("```").strip()
        result = json.loads(raw)
        non_null = {k: v for k, v in result.items() if v is not None}
        log.info(f"[LLM] extracted → {non_null or 'nothing useful'}")
        return result
    except Exception as e:
        log.info(f"[LLM] extract_fields failed: {e}")
        return {}