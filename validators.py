"""Pure validation functions — no API calls, no LLM, just logic."""
from __future__ import annotations
import re
from datetime import date
from typing import Optional

# ── Account ID ────────────────────────────────────────────────────────

def extract_account_id(text: str) -> Optional[str]:
    m = re.search(r'ACC\d{3,8}', text.upper())
    return m.group(0) if m else None

# ── Date of birth ─────────────────────────────────────────────────────

def validate_dob(dob_str: str) -> bool:
    """Check that a YYYY-MM-DD string from the LLM is a real date."""
    try:
        y, mo, d = dob_str.split("-")
        date(int(y), int(mo), int(d))
        return True
    except (ValueError, AttributeError):
        return False

# ── Secondary factors ─────────────────────────────────────────────────

def extract_digits(text: str, length: int) -> Optional[str]:
    """Extract a standalone number of exactly `length` digits."""
    m = re.search(rf"\b(\d{{{length}}})\b", text)
    return m.group(1) if m else None

def parse_aadhaar_last4(text: str) -> Optional[str]: return extract_digits(text, 4)
def parse_pincode(text: str)       -> Optional[str]: return extract_digits(text, 6)

# ── Card validation ───────────────────────────────────────────────────

def luhn_check(card_number: str) -> bool:
    """Validate card number using Luhn algorithm."""
    digits = [int(c) for c in card_number if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def validate_card_number(number: str) -> tuple[bool, str]:
    clean = re.sub(r"\s|-", "", number)
    if not clean.isdigit():
        return False, "Card number must contain only digits."
    if not luhn_check(clean):
        return False, "Card number is invalid."
    return True, clean


def validate_cvv(cvv: str, card_number: str = "") -> tuple[bool, str]:
    clean = cvv.strip()
    expected = 4 if card_number.startswith(("34", "37")) else 3
    if not clean.isdigit() or len(clean) != expected:
        return False, f"CVV must be {expected} digits."
    return True, clean


def validate_expiry(month: int, year: int) -> tuple[bool, str]:
    today = date.today()
    if not (1 <= month <= 12):
        return False, "Expiry month must be between 1 and 12."
    if year < today.year or (year == today.year and month < today.month):
        return False, "This card has expired."
    return True, ""


def validate_amount(amount_str: str, balance: float) -> tuple[bool, float, str]:
    try:
        amount = float(amount_str.replace(",", "").replace("₹", "").strip())
    except ValueError:
        return False, 0, "Please enter a valid number."
    if amount <= 0:
        return False, 0, "Amount must be greater than zero."
    if round(amount, 2) != amount:
        return False, 0, "Amount can have at most 2 decimal places."
    if amount > balance:
        return False, 0, f"Amount exceeds your outstanding balance of ₹{balance:.2f}."
    return True, amount, ""