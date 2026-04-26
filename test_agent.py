"""
Comprehensive pytest test suite for the PayAssist payment collection agent.
Covers:
  - All validator functions (unit tests)
  - LLM extraction via mocked extract_fields
  - Full conversation flows
  - Identity verification
  - Card collection and payment
  - Edge cases, security, state machine integrity
"""
import pytest
from unittest.mock import patch, MagicMock

# ── Shared mock data ─────────────────────────────────────────────────

MOCK_ACCOUNT = {
    "account_id": "ACC1001",
    "full_name": "Nithin Jain",
    "dob": "1990-05-14",
    "aadhaar_last4": "4321",
    "pincode": "400001",
    "balance": 1250.75,
}

MOCK_ACCOUNT_LEAP = {
    "account_id": "ACC1004",
    "full_name": "Rahul Mehta",
    "dob": "1988-02-29",
    "aadhaar_last4": "7788",
    "pincode": "560001",
    "balance": 500.00,
}

MOCK_ACCOUNT_LONG_NAME = {
    "account_id": "ACC1002",
    "full_name": "Rajarajeswari Balasubramaniam",
    "dob": "1985-11-23",
    "aadhaar_last4": "9876",
    "pincode": "400002",
    "balance": 3000.00,
}

MOCK_PAYMENT_SUCCESS = {
    "success": True,
    "transaction_id": "txn_test_abc123",
}

VALID_CARD   = "4532015112830366"   # Visa, passes Luhn
MASTERCARD   = "5555555555554444"   # Mastercard, passes Luhn
AMEX_CARD    = "378282246310005"    # Amex, passes Luhn
INVALID_CARD = "1234567890123456"   # fails Luhn


# ── Helpers ──────────────────────────────────────────────────────────

def make_agent():
    from agent import Agent
    return Agent()


def drive(agent, inputs):
    """Greet + run all inputs, return all response messages."""
    responses = [agent.next("")]
    for inp in inputs:
        responses.append(agent.next(inp))
    return [r["message"] for r in responses]


def reach_amount_state(mock_lookup_target="tools.lookup_account", account=None):
    """
    Helper context: returns an agent that has completed verification
    and is sitting in AWAIT_AMOUNT state. Uses aadhaar to avoid
    date-parsing interference.
    """
    account = account or MOCK_ACCOUNT
    agent = make_agent()
    with patch(mock_lookup_target, return_value=account):
        agent.next("")
        agent.next(account["account_id"])
        agent.next(account["full_name"])
        agent.next(account["aadhaar_last4"])  # use aadhaar — no date parsing issues
    return agent


# ════════════════════════════════════════════════════════════════════════
# 1. VALIDATOR UNIT TESTS
# ════════════════════════════════════════════════════════════════════════

class TestExtractAccountId:
    def test_plain(self):
        from validators import extract_account_id
        assert extract_account_id("ACC1001") == "ACC1001"

    def test_in_sentence(self):
        from validators import extract_account_id
        assert extract_account_id("my account is acc1001 thanks") == "ACC1001"

    def test_uppercase_normalised(self):
        from validators import extract_account_id
        assert extract_account_id("acc2003") == "ACC2003"

    def test_not_present(self):
        from validators import extract_account_id
        assert extract_account_id("hello there") is None

    def test_partial_no_match(self):
        from validators import extract_account_id
        assert extract_account_id("AC1001") is None

    def test_min_digits(self):
        from validators import extract_account_id
        assert extract_account_id("ACC123") == "ACC123"

    def test_max_digits(self):
        from validators import extract_account_id
        assert extract_account_id("ACC12345678") == "ACC12345678"

    def test_too_many_digits_partial_match(self):
        from validators import extract_account_id
        result = extract_account_id("ACC123456789")
        assert result == "ACC12345678"  # matches max 8 digits


class TestValidateDob:
    def test_valid_normal(self):
        from validators import validate_dob
        assert validate_dob("1990-05-14") is True

    def test_leap_year_valid(self):
        from validators import validate_dob
        assert validate_dob("1988-02-29") is True

    def test_leap_year_invalid(self):
        from validators import validate_dob
        assert validate_dob("1989-02-29") is False

    def test_invalid_month(self):
        from validators import validate_dob
        assert validate_dob("1990-13-01") is False

    def test_invalid_day(self):
        from validators import validate_dob
        assert validate_dob("1990-11-31") is False

    def test_garbage_string(self):
        from validators import validate_dob
        assert validate_dob("not-a-date") is False

    def test_empty_string(self):
        from validators import validate_dob
        assert validate_dob("") is False

    def test_wrong_format_rejected(self):
        from validators import validate_dob
        assert validate_dob("14-05-1990") is False


class TestParseAadhaarAndPincode:
    def test_aadhaar_plain(self):
        from validators import parse_aadhaar_last4
        assert parse_aadhaar_last4("4321") == "4321"

    def test_aadhaar_in_sentence(self):
        from validators import parse_aadhaar_last4
        assert parse_aadhaar_last4("my aadhaar last 4 is 4321") == "4321"

    def test_aadhaar_not_present(self):
        from validators import parse_aadhaar_last4
        assert parse_aadhaar_last4("hello") is None

    def test_pincode_plain(self):
        from validators import parse_pincode
        assert parse_pincode("400001") == "400001"

    def test_pincode_in_sentence(self):
        from validators import parse_pincode
        assert parse_pincode("my pincode is 400001") == "400001"

    def test_pincode_not_present(self):
        from validators import parse_pincode
        assert parse_pincode("hello") is None


class TestLuhnCheck:
    def test_valid_visa(self):
        from validators import luhn_check
        assert luhn_check(VALID_CARD) is True

    def test_valid_mastercard(self):
        from validators import luhn_check
        assert luhn_check(MASTERCARD) is True

    def test_valid_amex(self):
        from validators import luhn_check
        assert luhn_check(AMEX_CARD) is True

    def test_invalid(self):
        from validators import luhn_check
        assert luhn_check(INVALID_CARD) is False

    def test_too_short(self):
        from validators import luhn_check
        assert luhn_check("123456789012") is False

    def test_too_long(self):
        from validators import luhn_check
        assert luhn_check("45320151128303660000") is False


class TestValidateCardNumber:
    def test_valid(self):
        from validators import validate_card_number
        ok, clean = validate_card_number(VALID_CARD)
        assert ok and clean == VALID_CARD

    def test_with_spaces(self):
        from validators import validate_card_number
        ok, clean = validate_card_number("4532 0151 1283 0366")
        assert ok and clean == VALID_CARD

    def test_with_dashes(self):
        from validators import validate_card_number
        ok, clean = validate_card_number("4532-0151-1283-0366")
        assert ok and clean == VALID_CARD

    def test_invalid_luhn(self):
        from validators import validate_card_number
        ok, msg = validate_card_number(INVALID_CARD)
        assert not ok and "invalid" in msg.lower()

    def test_non_digits(self):
        from validators import validate_card_number
        ok, msg = validate_card_number("abcd1234efgh5678")
        assert not ok and "digits" in msg.lower()


class TestValidateCvv:
    def test_valid_3_digit(self):
        from validators import validate_cvv
        ok, clean = validate_cvv("123", VALID_CARD)
        assert ok and clean == "123"

    def test_valid_4_digit_amex(self):
        from validators import validate_cvv
        ok, clean = validate_cvv("1234", AMEX_CARD)
        assert ok and clean == "1234"

    def test_wrong_length_for_visa(self):
        from validators import validate_cvv
        ok, msg = validate_cvv("1234", VALID_CARD)
        assert not ok and "3" in msg

    def test_wrong_length_for_amex(self):
        from validators import validate_cvv
        ok, msg = validate_cvv("123", AMEX_CARD)
        assert not ok and "4" in msg

    def test_non_digits(self):
        from validators import validate_cvv
        ok, _ = validate_cvv("abc", VALID_CARD)
        assert not ok


class TestValidateExpiry:
    def test_future_date(self):
        from validators import validate_expiry
        ok, _ = validate_expiry(12, 2099)
        assert ok is True

    def test_expired(self):
        from validators import validate_expiry
        ok, err = validate_expiry(1, 2000)
        assert not ok and "expired" in err.lower()

    def test_invalid_month_zero(self):
        from validators import validate_expiry
        ok, _ = validate_expiry(0, 2099)
        assert not ok

    def test_invalid_month_13(self):
        from validators import validate_expiry
        ok, _ = validate_expiry(13, 2099)
        assert not ok


class TestValidateAmount:
    def test_valid(self):
        from validators import validate_amount
        ok, amt, _ = validate_amount("500", 1250.75)
        assert ok and amt == 500.0

    def test_exact_balance(self):
        from validators import validate_amount
        ok, amt, _ = validate_amount("1250.75", 1250.75)
        assert ok and amt == 1250.75

    def test_exceeds_balance(self):
        from validators import validate_amount
        ok, _, err = validate_amount("9999", 1250.75)
        assert not ok and "balance" in err.lower()

    def test_zero(self):
        from validators import validate_amount
        ok, _, _ = validate_amount("0", 1250.75)
        assert not ok

    def test_negative(self):
        from validators import validate_amount
        ok, _, _ = validate_amount("-100", 1250.75)
        assert not ok

    def test_with_rupee_symbol(self):
        from validators import validate_amount
        ok, amt, _ = validate_amount("₹500", 1250.75)
        assert ok and amt == 500.0

    def test_with_commas(self):
        from validators import validate_amount
        ok, amt, _ = validate_amount("1,000", 1250.75)
        assert ok and amt == 1000.0

    def test_too_many_decimals(self):
        from validators import validate_amount
        ok, _, err = validate_amount("100.999", 1250.75)
        assert not ok and "decimal" in err.lower()

    def test_non_numeric(self):
        from validators import validate_amount
        ok, _, err = validate_amount("abc", 1250.75)
        assert not ok and "valid" in err.lower()


# ════════════════════════════════════════════════════════════════════════
# 2. LLM EXTRACTION TESTS
# ════════════════════════════════════════════════════════════════════════

class TestLLMExtraction:

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_llm_returns_nothing_for_account_id(self, mock_lookup):
        """When no ACC pattern found, agent asks again."""
        agent = make_agent()
        agent.next("")
        with patch("agent.extract_fields", return_value={}):
            resp = agent.next("I forgot my number")
        assert "acc" in resp["message"].lower() or "account" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_aadhaar_verified_directly(self, mock_lookup):
        """Aadhaar last 4 is parsed deterministically — no LLM needed.
        Sending '4321' directly after name should verify successfully."""
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        agent.next("Nithin Jain")
        resp = agent.next("4321")
        assert "verified" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_aadhaar_in_sentence_verified(self, mock_lookup):
        """Aadhaar embedded in natural text is still parsed deterministically."""
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        agent.next("Nithin Jain")
        resp = agent.next("my last 4 aadhaar digits are 4321")
        assert "verified" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_pincode_verified_directly(self, mock_lookup):
        """Pincode is parsed deterministically — no LLM needed."""
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        agent.next("Nithin Jain")
        resp = agent.next("400001")
        assert "verified" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_pincode_in_sentence_verified(self, mock_lookup):
        """Pincode embedded in natural text is still parsed deterministically."""
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        agent.next("Nithin Jain")
        resp = agent.next("my pincode is 400001")
        assert "verified" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_llm_returns_invalid_dob(self, mock_lookup):
        """Agent rejects an invalid date even if LLM returned it."""
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        agent.next("Nithin Jain")
        with patch("agent.extract_fields", return_value={"dob": "1989-02-29"}):
            resp = agent.next("29 feb 1989")
        msg = resp["message"].lower()
        assert "valid" in msg or "invalid" in msg or "attempt" in msg or "match" in msg

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_amount_accepted_directly(self, mock_lookup):
        """Amount is parsed by validator directly — no LLM needed.
        Sending '500' should move agent to card collection."""
        agent = reach_amount_state()
        resp = agent.next("500")
        assert "card" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_llm_extracts_amount_exceeding_balance(self, mock_lookup):
        """Validator rejects amount even if LLM extracted it."""
        agent = reach_amount_state()
        with patch("agent.extract_fields", return_value={"amount": 9999}):
            resp = agent.next("pay nine thousand nine hundred rupees")
        assert "balance" in resp["message"].lower() or "valid" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    @patch("tools.process_payment", return_value=MOCK_PAYMENT_SUCCESS)
    def test_card_number_accepted_directly(self, mock_pay, mock_lookup):
        """Card number is validated by Luhn check directly — no LLM needed.
        Sending the card number directly should move agent to CVV."""
        agent = reach_amount_state()
        agent.next("500")
        resp = agent.next(VALID_CARD)
        assert "cvv" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    @patch("tools.process_payment", return_value=MOCK_PAYMENT_SUCCESS)
    def test_dob_via_llm_verification(self, mock_pay, mock_lookup):
        """DOB is parsed by LLM — mock returns valid date, verification passes."""
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        agent.next("Nithin Jain")
        with patch("agent.extract_fields", return_value={"dob": "1990-05-14"}):
            resp = agent.next("14th may 1990")
        assert "verified" in resp["message"].lower()


# ════════════════════════════════════════════════════════════════════════
# 3. FULL FLOW TESTS
# ════════════════════════════════════════════════════════════════════════

class TestHappyPath:

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    @patch("tools.process_payment", return_value=MOCK_PAYMENT_SUCCESS)
    def test_full_flow_aadhaar(self, mock_pay, mock_lookup):
        agent = make_agent()
        msgs = drive(agent, [
            "ACC1001", "Nithin Jain", "4321", "500",
            VALID_CARD, "123", "12 2027", "Nithin Jain", "yes",
        ])
        assert any("transaction" in m.lower() for m in msgs)

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    @patch("tools.process_payment", return_value=MOCK_PAYMENT_SUCCESS)
    def test_full_flow_pincode(self, mock_pay, mock_lookup):
        agent = make_agent()
        msgs = drive(agent, [
            "ACC1001", "Nithin Jain", "400001", "500",
            VALID_CARD, "123", "12 2027", "Nithin Jain", "yes",
        ])
        assert any("transaction" in m.lower() for m in msgs)

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    @patch("tools.process_payment", return_value=MOCK_PAYMENT_SUCCESS)
    def test_full_flow_dob_via_llm(self, mock_pay, mock_lookup):
        """DOB flow works when LLM correctly converts date format."""
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        agent.next("Nithin Jain")
        with patch("agent.extract_fields", return_value={"dob": "1990-05-14"}):
            agent.next("1990-05-14")
        agent.next("500")
        agent.next(VALID_CARD)
        agent.next("123")
        agent.next("12 2027")
        agent.next("Nithin Jain")
        resp = agent.next("yes")
        assert "transaction" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    @patch("tools.process_payment", return_value=MOCK_PAYMENT_SUCCESS)
    def test_partial_payment(self, mock_pay, mock_lookup):
        agent = make_agent()
        msgs = drive(agent, [
            "ACC1001", "Nithin Jain", "4321", "100",
            VALID_CARD, "123", "12 2027", "Nithin Jain", "yes",
        ])
        assert any("transaction" in m.lower() for m in msgs)

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT_LEAP)
    @patch("tools.process_payment", return_value=MOCK_PAYMENT_SUCCESS)
    def test_leap_year_account_with_aadhaar(self, mock_pay, mock_lookup):
        """ACC1004 verified via aadhaar — no date parsing needed."""
        agent = make_agent()
        msgs = drive(agent, [
            "ACC1004", "Rahul Mehta", "7788", "200",
            VALID_CARD, "123", "12 2027", "Rahul Mehta", "yes",
        ])
        assert any("transaction" in m.lower() for m in msgs)

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    @patch("tools.process_payment", return_value=MOCK_PAYMENT_SUCCESS)
    def test_account_id_lowercase(self, mock_pay, mock_lookup):
        agent = make_agent()
        msgs = drive(agent, [
            "acc1001", "Nithin Jain", "4321", "500",
            VALID_CARD, "123", "12 2027", "Nithin Jain", "yes",
        ])
        assert any("transaction" in m.lower() for m in msgs)

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    @patch("tools.process_payment", return_value=MOCK_PAYMENT_SUCCESS)
    def test_account_id_in_sentence(self, mock_pay, mock_lookup):
        agent = make_agent()
        agent.next("")
        resp = agent.next("Hi my account number is ACC1001 thanks")
        assert "name" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    @patch("tools.process_payment", return_value=MOCK_PAYMENT_SUCCESS)
    def test_amex_requires_4_digit_cvv(self, mock_pay, mock_lookup):
        agent = reach_amount_state()
        agent.next("500")
        agent.next(AMEX_CARD)
        resp = agent.next("123")   # 3 digits — should fail for Amex
        assert "4" in resp["message"] or "cvv" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    @patch("tools.process_payment", return_value=MOCK_PAYMENT_SUCCESS)
    def test_mastercard_accepted(self, mock_pay, mock_lookup):
        agent = make_agent()
        msgs = drive(agent, [
            "ACC1001", "Nithin Jain", "4321", "500",
            MASTERCARD, "321", "10 2028", "Nithin Jain", "yes",
        ])
        assert any("transaction" in m.lower() for m in msgs)


# ════════════════════════════════════════════════════════════════════════
# 4. VERIFICATION FAILURE TESTS
# ════════════════════════════════════════════════════════════════════════

class TestVerificationFailure:

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_wrong_name(self, mock_lookup):
        agent = make_agent()
        msgs = drive(agent, ["ACC1001", "Wrong Name", "4321"])
        assert any("match" in m.lower() or "attempt" in m.lower() for m in msgs)

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_wrong_aadhaar(self, mock_lookup):
        agent = make_agent()
        msgs = drive(agent, ["ACC1001", "Nithin Jain", "9999"])
        assert any("match" in m.lower() or "attempt" in m.lower() for m in msgs)

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_wrong_pincode(self, mock_lookup):
        agent = make_agent()
        msgs = drive(agent, ["ACC1001", "Nithin Jain", "999999"])
        assert any("match" in m.lower() or "attempt" in m.lower() for m in msgs)

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_wrong_dob_via_llm(self, mock_lookup):
        """Wrong DOB via LLM extraction fails verification."""
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        agent.next("Nithin Jain")
        with patch("agent.extract_fields", return_value={"dob": "1991-01-01"}):
            resp = agent.next("1991-01-01")
        assert "match" in resp["message"].lower() or "attempt" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_name_case_sensitive(self, mock_lookup):
        """'nithin jain' lowercase must NOT pass."""
        agent = make_agent()
        msgs = drive(agent, ["ACC1001", "nithin jain", "4321"])
        assert any("match" in m.lower() or "attempt" in m.lower() for m in msgs)

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_lockout_after_3_attempts(self, mock_lookup):
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        for _ in range(3):
            agent.next("Wrong Guy")
            agent.next("9999")   # wrong aadhaar
        final = agent.next("anything")
        assert "locked" in final["message"].lower() or "security" in final["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_correct_after_one_wrong(self, mock_lookup):
        """Fail once, then succeed — agent should let through."""
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        agent.next("Wrong Name")
        agent.next("9999")       # wrong aadhaar attempt 1
        agent.next("Nithin Jain")
        resp = agent.next("4321")  # correct aadhaar
        assert "verified" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_only_name_asks_for_secondary(self, mock_lookup):
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        resp = agent.next("Nithin Jain")
        msg = resp["message"].lower()
        assert "dob" in msg or "aadhaar" in msg or "pincode" in msg or "date" in msg

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_only_secondary_asks_for_name(self, mock_lookup):
        """Sending aadhaar before name: agent is in AWAIT_NAME,
        treats '4321' as a (failed) name attempt and asks for name."""
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        resp = agent.next("4321")
        assert "name" in resp["message"].lower()


# ════════════════════════════════════════════════════════════════════════
# 5. PAYMENT FAILURE TESTS
# ════════════════════════════════════════════════════════════════════════

class TestPaymentFailure:

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    @patch("tools.process_payment", side_effect=__import__("tools").APIError("invalid_card", "The card number is invalid."))
    def test_invalid_card_retryable(self, mock_pay, mock_lookup):
        agent = reach_amount_state()
        agent.next("500")
        agent.next(VALID_CARD)
        agent.next("123")
        agent.next("12 2027")
        agent.next("Nithin Jain")
        resp = agent.next("yes")
        assert "invalid" in resp["message"].lower() or "didn't go through" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    @patch("tools.process_payment", side_effect=__import__("tools").APIError("invalid_cvv", "The CVV is incorrect."))
    def test_invalid_cvv_retryable(self, mock_pay, mock_lookup):
        agent = reach_amount_state()
        agent.next("500")
        agent.next(VALID_CARD)
        agent.next("123")
        agent.next("12 2027")
        agent.next("Nithin Jain")
        resp = agent.next("yes")
        assert "cvv" in resp["message"].lower() or "didn't go through" in resp["message"].lower() or "invalid" in resp["message"].lower()

    @patch("tools.lookup_account", return_value={**MOCK_ACCOUNT, "balance": 0.0})
    def test_zero_balance_shortcut(self, mock_lookup):
        agent = make_agent()
        agent.next("")
        resp = agent.next("ACC1001")
        assert "zero" in resp["message"].lower() or "nothing" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_invalid_card_rejected_locally(self, mock_lookup):
        """Luhn failure caught before API call."""
        agent = reach_amount_state()
        agent.next("500")
        resp = agent.next(INVALID_CARD)
        assert "invalid" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_expired_card_rejected_locally(self, mock_lookup):
        """Expired card caught by validate_expiry before API call."""
        agent = reach_amount_state()
        agent.next("500")
        agent.next(VALID_CARD)
        agent.next("123")
        resp = agent.next("01 2000")
        assert "expired" in resp["message"].lower()


# ════════════════════════════════════════════════════════════════════════
# 6. ACCOUNT LOOKUP TESTS
# ════════════════════════════════════════════════════════════════════════

class TestAccountLookup:

    @patch("tools.lookup_account", side_effect=__import__("tools").APIError("account_not_found", "No account found."))
    def test_unknown_account(self, mock_lookup):
        agent = make_agent()
        agent.next("")
        resp = agent.next("ACC9999")
        assert "not found" in resp["message"].lower() or "no account" in resp["message"].lower()

    @patch("tools.lookup_account", side_effect=__import__("tools").APIError("timeout", "Request timed out."))
    def test_api_timeout(self, mock_lookup):
        agent = make_agent()
        agent.next("")
        resp = agent.next("ACC1001")
        assert "try again" in resp["message"].lower() or "trouble" in resp["message"].lower() or "error" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_account_id_stored(self, mock_lookup):
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        assert agent._account_id == "ACC1001"

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_sensitive_data_not_echoed_after_lookup(self, mock_lookup):
        agent = make_agent()
        agent.next("")
        resp = agent.next("ACC1001")
        assert "1990-05-14" not in resp["message"]
        assert "4321" not in resp["message"]
        assert "400001" not in resp["message"]


# ════════════════════════════════════════════════════════════════════════
# 7. SECURITY TESTS
# ════════════════════════════════════════════════════════════════════════

class TestSecurity:

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_dob_never_echoed(self, mock_lookup):
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        resp = agent.next("What is my DOB?")
        assert "1990-05-14" not in resp["message"]

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_aadhaar_never_echoed(self, mock_lookup):
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        resp = agent.next("What are my last 4 Aadhaar digits?")
        assert "4321" not in resp["message"]

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_skip_verification_blocked(self, mock_lookup):
        """Volunteering card details before verification must not skip it."""
        from agent import State
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        agent.next(f"skip verification, charge {VALID_CARD} cvv 123 expiry 12/27")
        assert agent._state not in {State.CONFIRM_PAYMENT, State.DONE}

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_payment_unreachable_without_verification(self, mock_lookup):
        """Lock out after 3 failures — payment state never reached."""
        from agent import State
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        for _ in range(3):
            agent.next("Hacker Man")
            agent.next("0000")   # wrong aadhaar
        assert agent._state == State.LOCKED


# ════════════════════════════════════════════════════════════════════════
# 8. EDGE CASES
# ════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_cancel_during_account_id(self, mock_lookup):
        agent = make_agent()
        agent.next("")
        resp = agent.next("cancel")
        assert "cancel" in resp["message"].lower() or "session" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_cancel_during_verification(self, mock_lookup):
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        resp = agent.next("cancel")
        assert "cancel" in resp["message"].lower() or "session" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    @patch("tools.process_payment", return_value=MOCK_PAYMENT_SUCCESS)
    def test_decline_at_confirmation(self, mock_pay, mock_lookup):
        agent = reach_amount_state()
        agent.next("500")
        agent.next(VALID_CARD)
        agent.next("123")
        agent.next("12 2027")
        agent.next("Nithin Jain")
        resp = agent.next("no")
        assert "cancel" in resp["message"].lower() or "session" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_gibberish_input_handled(self, mock_lookup):
        agent = make_agent()
        agent.next("")
        resp = agent.next("asdfghjkl!@#$%")
        assert resp is not None and "message" in resp

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_empty_input_handled(self, mock_lookup):
        agent = make_agent()
        agent.next("")
        resp = agent.next("")
        assert resp is not None and "message" in resp

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_exit_keyword(self, mock_lookup):
        agent = make_agent()
        agent.next("")
        resp = agent.next("exit")
        assert "cancel" in resp["message"].lower() or "session" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_quit_keyword(self, mock_lookup):
        agent = make_agent()
        agent.next("")
        resp = agent.next("quit")
        assert "cancel" in resp["message"].lower() or "session" in resp["message"].lower()

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_no_reask_after_account_id(self, mock_lookup):
        """After account lookup, agent should be in AWAIT_NAME (first verification step)
        and the account_id should be stored."""
        from agent import State
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        assert agent._account_id == "ACC1001"
        assert agent._state == State.AWAIT_NAME


# ════════════════════════════════════════════════════════════════════════
# 9. STATE MACHINE INTEGRITY
# ════════════════════════════════════════════════════════════════════════

class TestStateMachine:

    def test_initial_state_is_await_account_id(self):
        """Agent initialises directly in AWAIT_ACCOUNT_ID — no GREETING state."""
        from agent import State
        agent = make_agent()
        assert agent._state == State.AWAIT_ACCOUNT_ID

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_state_after_greeting(self, mock_lookup):
        from agent import State
        agent = make_agent()
        agent.next("")
        assert agent._state == State.AWAIT_ACCOUNT_ID

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_state_after_account_lookup_is_await_name(self, mock_lookup):
        """After account lookup, agent is in AWAIT_NAME (name collected first,
        then secondary factor — two separate states)."""
        from agent import State
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        assert agent._state == State.AWAIT_NAME

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_state_after_name_is_await_secondary(self, mock_lookup):
        """After correct name, agent moves to AWAIT_SECONDARY."""
        from agent import State
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        agent.next("Nithin Jain")
        assert agent._state == State.AWAIT_SECONDARY

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_state_after_verification(self, mock_lookup):
        from agent import State
        agent = reach_amount_state()
        assert agent._state == State.AWAIT_AMOUNT

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_state_locked_after_max_attempts(self, mock_lookup):
        from agent import State
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        for _ in range(3):
            agent.next("Wrong Name")
            agent.next("9999")   # wrong aadhaar
        assert agent._state == State.LOCKED

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    def test_state_cancelled(self, mock_lookup):
        from agent import State
        agent = make_agent()
        agent.next("")
        agent.next("cancel")
        assert agent._state == State.CANCELLED

    @patch("tools.lookup_account", return_value={**MOCK_ACCOUNT, "balance": 0.0})
    def test_state_done_after_zero_balance(self, mock_lookup):
        from agent import State
        agent = make_agent()
        agent.next("")
        agent.next("ACC1001")
        assert agent._state == State.DONE

    @patch("tools.lookup_account", return_value=MOCK_ACCOUNT)
    @patch("tools.process_payment", return_value=MOCK_PAYMENT_SUCCESS)
    def test_state_done_after_payment(self, mock_pay, mock_lookup):
        from agent import State
        agent = reach_amount_state()
        agent.next("500")
        agent.next(VALID_CARD)
        agent.next("123")
        agent.next("12 2027")
        agent.next("Nithin Jain")
        agent.next("yes")
        assert agent._state == State.DONE
