"""Payment collection agent — deterministic state machine."""
from __future__ import annotations
import re
from enum import Enum, auto
from validators import (
    extract_account_id, validate_dob, parse_aadhaar_last4, parse_pincode,
    validate_card_number, validate_cvv, validate_expiry, validate_amount,
)
import tools
from tools import APIError
from llm import extract_fields


class State(Enum):
    AWAIT_ACCOUNT_ID    = auto()
    AWAIT_NAME          = auto()
    AWAIT_SECONDARY     = auto()
    AWAIT_AMOUNT        = auto()
    AWAIT_CARD_NUMBER   = auto()
    AWAIT_CVV           = auto()
    AWAIT_EXPIRY        = auto()
    AWAIT_CARDHOLDER    = auto()
    CONFIRM_PAYMENT     = auto()
    DONE                = auto()
    LOCKED              = auto()
    CANCELLED           = auto()
    AWAIT_SAME_OR_NEW   = auto()
    AWAIT_SAME_CARD     = auto()


MAX_VERIFY_ATTEMPTS = 3
MAX_CARD_ATTEMPTS   = 3

CANCEL_WORDS  = {"cancel", "exit", "quit", "stop"}
YES_WORDS     = {"yes", "y", "confirm", "ok", "proceed", "sure", "yep", "yeah"}
NO_WORDS      = {"no", "n", "cancel", "stop"}
SAME_WORDS    = {"same", "yes", "y", "this", "that"}
ANOTHER_WORDS = {"yes", "y", "sure", "another", "more", "again"}

GREETING = (
    "Welcome to PayAssist. I'm here to help you settle your outstanding balance. "
    "To get started, please share your account ID."
)
LOCKED_MSG = (
    "We were unable to verify your identity after multiple attempts. "
    "For security reasons, this session has been locked. "
    "Please contact our support team for assistance."
)
CANCEL_MSG = "Session cancelled. Thank you for contacting us."


class Agent:
    def __init__(self):
        self._state           = State.AWAIT_ACCOUNT_ID
        self._account_data    = None
        self._account_id      = None
        self._verify_attempts = 0
        self._card_attempts   = 0
        self._payment_amount  = None
        self._card            = {}
        self._reuse_card      = False

    # ------------------------------------------------------------------
    def next(self, user_input: str) -> dict:
        text = user_input.strip()

        # Bootstrap turn (server sends "" to fetch the greeting)
        if not text and self._state == State.AWAIT_ACCOUNT_ID and self._account_data is None:
            return {"message": GREETING}

        # Global cancel
        if text.lower() in CANCEL_WORDS and self._state not in {State.CANCELLED, State.LOCKED}:
            self._state = State.CANCELLED
            return {"message": CANCEL_MSG}

        # Terminal states — short-circuit before dispatch
        if self._state == State.LOCKED:
            return {"message": LOCKED_MSG}
        if self._state == State.CANCELLED:
            return {"message": CANCEL_MSG}

        handler = {
            State.AWAIT_ACCOUNT_ID:  self._handle_account_id,
            State.AWAIT_NAME:        self._handle_name,
            State.AWAIT_SECONDARY:   self._handle_secondary,
            State.AWAIT_AMOUNT:      self._handle_amount,
            State.AWAIT_CARD_NUMBER: self._handle_card_number,
            State.AWAIT_CVV:         self._handle_cvv,
            State.AWAIT_EXPIRY:      self._handle_expiry,
            State.AWAIT_CARDHOLDER:  self._handle_cardholder,
            State.CONFIRM_PAYMENT:   self._handle_confirm,
            State.DONE:              self._handle_done,
            State.AWAIT_SAME_OR_NEW: self._handle_same_or_new,
            State.AWAIT_SAME_CARD:   self._handle_same_card,
        }[self._state]
        return handler(text)

    # ------------------------------------------------------------------
    def _handle_account_id(self, text: str) -> dict:
        account_id = extract_account_id(text)
        if not account_id:
            return {"message": "Please share your account ID to get started (format: ACC followed by digits, e.g. ACC1001)."}
        try:
            data = tools.lookup_account(account_id)
        except APIError as e:
            if e.code == "account_not_found":
                return {"message": f"No account found for ID '{account_id}'. Please double-check and try again."}
            return {"message": f"I'm having trouble connecting to the server right now — {e.message}. Would you like to retry?"}

        self._account_data = data
        self._account_id   = data["account_id"]

        if float(data.get("balance", 0)) <= 0:
            self._state = State.DONE
            return {"message": "Your account has a zero balance — there's nothing to pay at this time. Is there anything else I can help you with?"}

        self._state = State.AWAIT_NAME
        return {"message": "To verify your identity, please share your full name as it appears on the account."}

    # ------------------------------------------------------------------
    def _handle_name(self, text: str) -> dict:
        if len(text) < 2:
            return {"message": "Please share your full name."}
        if text != self._account_data["full_name"]:
            return self._verification_failed("name")
        self._state = State.AWAIT_SECONDARY
        return {"message": (
            "Thanks. Now please provide one of: "
            "date of birth (YYYY-MM-DD or e.g. 29 Feb 1988), "
            "Aadhaar last 4 digits, or pincode."
        )}

    def _handle_secondary(self, text: str) -> dict:
        # Pure digit input → Aadhaar (4) or pincode (6). Everything else → DOB via LLM.
        # This handles every date format the LLM understands — YYYY-MM-DD, "14 May 1990",
        # "february 29 1988", etc. — without us maintaining a month-name regex.
        dob = aadhaar = pincode = None
        is_just_digits = text.replace(" ", "").isdigit()

        if is_just_digits:
            stripped = text.replace(" ", "")
            aadhaar = parse_aadhaar_last4(stripped)
            pincode = parse_pincode(stripped)
        else:
            extracted = extract_fields(text, ["dob"], context="Extract date of birth only.")
            raw_dob = extracted.get("dob")
            if raw_dob and validate_dob(raw_dob):
                dob = raw_dob

        if not (dob or aadhaar or pincode):
            return {"message": (
                "I couldn't read that as a valid date or code. "
                "Please provide your date of birth (e.g. 1990-05-14 or 14 May 1990), "
                "Aadhaar last 4 digits, or 6-digit pincode."
            )}

        if dob and dob == self._account_data.get("dob"):
            return self._verification_passed()
        if aadhaar and aadhaar == self._account_data.get("aadhaar_last4"):
            return self._verification_passed()
        if pincode and pincode == self._account_data.get("pincode"):
            return self._verification_passed()

        return self._verification_failed("secondary")

    def _verification_passed(self) -> dict:
        self._state = State.AWAIT_AMOUNT
        balance = float(self._account_data["balance"])
        return {"message": (
            f"Identity verified successfully. Your outstanding balance is ₹{balance:.2f}. "
            f"We accept credit or debit cards only. "
            f"How much would you like to pay today? (up to ₹{balance:.2f})"
        )}

    def _verification_failed(self, which: str) -> dict:
        """Stay on the failing step so the user only re-enters what was wrong.
        `which` is 'name' or 'secondary'."""
        self._verify_attempts += 1
        remaining = MAX_VERIFY_ATTEMPTS - self._verify_attempts
        if remaining <= 0:
            self._state = State.LOCKED
            return {"message": LOCKED_MSG}

        if which == "name":
            self._state = State.AWAIT_NAME
            msg = (f"That name doesn't match our records. "
                   f"You have {remaining} attempt(s) remaining. "
                   "Please share your full name exactly as it appears on the account.")
        else:
            self._state = State.AWAIT_SECONDARY
            msg = (f"That doesn't match our records. "
                   f"You have {remaining} attempt(s) remaining. "
                   "Please provide your date of birth, Aadhaar last 4, or pincode.")
        return {"message": msg}

    # ------------------------------------------------------------------
    def _handle_amount(self, text: str) -> dict:
        balance = float(self._account_data["balance"])
        ok, amount, err = validate_amount(text, balance)
        if not ok:
            return {"message": f"{err} Please enter an amount up to ₹{balance:.2f}."}
        self._payment_amount = amount
        if self._reuse_card and self._card.get("number"):
            self._reuse_card = False
            self._state = State.CONFIRM_PAYMENT
            return {"message": (
                f"I'll process a payment of ₹{amount:.2f} on your card ending "
                f"in {self._card['number'][-4:]}. Shall I proceed? (yes / no)"
            )}
        self._state = State.AWAIT_CARD_NUMBER
        return {"message": "Please enter your card number."}

    def _handle_card_number(self, text: str) -> dict:
        ok, clean = validate_card_number(text)
        if not ok:
            return {"message": f"I didn't quite catch that. {clean}"}
        self._card["number"] = clean
        self._state = State.AWAIT_CVV
        return {"message": "Please enter your CVV."}

    def _handle_cvv(self, text: str) -> dict:
        ok, clean = validate_cvv(text, self._card.get("number", ""))
        if not ok:
            return {"message": f"I didn't quite catch that. {clean}"}
        self._card["cvv"] = clean
        self._state = State.AWAIT_EXPIRY
        return {"message": "Please enter your card expiry — month and year (e.g. 12 2027)."}

    def _handle_expiry(self, text: str) -> dict:
        # Fast path: numeric formats like "12 2027", "12/27", "12-2027"
        month = year = None
        m = re.search(r"(\d{1,2})[/\s-](\d{2,4})", text)
        if m:
            month = int(m.group(1))
            yr    = int(m.group(2))
            year  = yr + 2000 if yr < 100 else yr
        else:
            # Fallback: let the LLM handle natural language ("dec 2030", "December 27")
            extracted = extract_fields(text, ["expiry_month", "expiry_year"],
                                       context="User is providing card expiry month and year.")
            try:
                month = int(extracted.get("expiry_month"))
                year  = int(extracted.get("expiry_year"))
                if year < 100:
                    year += 2000
            except (TypeError, ValueError):
                month = year = None

        if month is None or year is None:
            return {"message": "I didn't quite catch that. Please enter expiry as month and year, e.g. 12 2027 or December 2027."}

        ok, err = validate_expiry(month, year)
        if not ok:
            return {"message": f"I didn't quite catch that. {err}"}
        self._card["expiry_month"] = month
        self._card["expiry_year"]  = year
        self._state = State.AWAIT_CARDHOLDER
        return {"message": "Please enter the cardholder name as it appears on the card."}

    def _handle_cardholder(self, text: str) -> dict:
        if len(text) < 2:
            return {"message": "I didn't quite catch that. Please enter the cardholder name."}
        self._card["cardholder_name"] = text
        self._state = State.CONFIRM_PAYMENT
        return {"message": (
            f"I'll process a payment of ₹{self._payment_amount:.2f} on your card ending "
            f"in {self._card['number'][-4:]}. Shall I proceed? (yes / no)"
        )}

    def _handle_confirm(self, text: str) -> dict:
        t = text.lower()
        if t in YES_WORDS:
            return self._process_payment()
        if t in NO_WORDS:
            self._state = State.CANCELLED
            return {"message": CANCEL_MSG}
        return {"message": (
            f"Please reply 'yes' to confirm the ₹{self._payment_amount:.2f} payment, "
            "or 'no' to cancel."
        )}

    def _process_payment(self) -> dict:
        try:
            result = tools.process_payment(
                account_id      = self._account_id,
                amount          = self._payment_amount,
                card_number     = self._card["number"],
                cvv             = self._card["cvv"],
                expiry_month    = self._card["expiry_month"],
                expiry_year     = self._card["expiry_year"],
                cardholder_name = self._card["cardholder_name"],
            )
            self._state = State.DONE
            return {"message": (
                f"Payment of ₹{self._payment_amount:.2f} processed successfully. "
                f"Your transaction ID is {result.get('transaction_id', '')}. "
                "Please save this for your records. Would you like to make another payment? (yes / no)"
            )}
        except APIError as e:
            retryable = e.code in {"invalid_card", "invalid_cvv", "invalid_expiry"}
            self._card_attempts += 1
            if retryable and self._card_attempts < MAX_CARD_ATTEMPTS:
                self._state = State.AWAIT_CARD_NUMBER
                self._card  = {}
                return {"message": (
                    f"The payment didn't go through — {e.message}. "
                    "Would you like to try again with different card details?"
                )}
            self._state = State.DONE
            return {"message": (
                f"The payment could not be processed — {e.message}. "
                "Please contact support or try again later."
            )}

    # ------------------------------------------------------------------
    # Repeat-payment flow
    # ------------------------------------------------------------------
    def _handle_done(self, text: str) -> dict:
        t = text.lower()
        if t in ANOTHER_WORDS:
            self._state = State.AWAIT_SAME_OR_NEW
            return {"message": "Would you like to pay with the same account or a different one? (same / new)"}
        if t in NO_WORDS or t in {"thanks", "thank you", "bye", "goodbye"}:
            return {"message": "Thank you for using PayAssist. Have a great day!"}
        return {"message": "Would you like to make another payment? Please reply 'yes' or 'no'."}

    def _handle_same_or_new(self, text: str) -> dict:
        if text.lower() in SAME_WORDS and self._account_data:
            self._card_attempts = 0
            balance = float(self._account_data["balance"])
            if self._card.get("number"):
                last4 = self._card["number"][-4:]
                self._state = State.AWAIT_SAME_CARD
                return {"message": (
                    f"Your balance is ₹{balance:.2f}. "
                    f"Use the same card ending in {last4}, or a different one? (same / new)"
                )}
            self._state = State.AWAIT_AMOUNT
            return {"message": f"Your balance is ₹{balance:.2f}. How much would you like to pay?"}

        # Reset for a fresh account
        self._account_data = self._account_id = None
        self._verify_attempts = self._card_attempts = 0
        self._payment_amount = None
        self._card = {}
        self._state = State.AWAIT_ACCOUNT_ID
        return {"message": "Please share the account ID you'd like to pay for."}

    def _handle_same_card(self, text: str) -> dict:
        balance = float(self._account_data["balance"])
        if text.lower() in SAME_WORDS:
            self._reuse_card = True
        else:
            self._card = {}
        self._state = State.AWAIT_AMOUNT
        return {"message": f"How much would you like to pay? (up to ₹{balance:.2f})"}