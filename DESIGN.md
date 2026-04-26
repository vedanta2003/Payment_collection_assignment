# Design Document — PayAssist Agent

## Architecture Overview

The agent is a **deterministic state machine** with the LLM scoped to a single, well-defined task.

### Core principle

Business logic lives in pure Python. The LLM is used only where rules genuinely cannot do the job — parsing free-form natural-language dates. Everything else (state transitions, verification, retries, validation, payment processing) is deterministic code.

```
User input
    ↓
State machine (agent.py) — decides what step we're on
    ↓
For pure digits → deterministic validators (validators.py)
For date strings → LLM extractor (llm.py) → deterministic validator
    ↓
API client (tools.py) — calls Prodigal's endpoints
    ↓
Hardcoded response template inline in handler
    ↓
Output
```

### State machine

The agent moves through these states. Transitions are only triggered by explicit conditions in code — never by the LLM:

```
AWAIT_ACCOUNT_ID → AWAIT_NAME → AWAIT_SECONDARY → AWAIT_AMOUNT
→ AWAIT_CARD_NUMBER → AWAIT_CVV → AWAIT_EXPIRY → AWAIT_CARDHOLDER
→ CONFIRM_PAYMENT → DONE

Terminal: DONE, LOCKED, CANCELLED
```

---

## Key Decisions

### 1. Verification is pure Python

The brief specifies "strict matching, no fuzzy matching." If the LLM handled verification, that guarantee would only be as strong as the prompt — which can drift, hallucinate, or interpret `"nithin jain"` as matching `"Nithin Jain"`. Code cannot:

```python
if text != self._account_data["full_name"]:
    return self._verification_failed("name")
```

This is auditable, testable, and deterministic.

### 2. The LLM is used in exactly one function

`extract_fields` in `llm.py`. It handles two narrowly-scoped tasks:

- **DOB normalization**: `"29 Feb 1988"` or `"14th may 1990"` → `"1988-02-29"` / `"1990-05-14"`. The handler pre-classifies the input as date-shaped (i.e., contains non-digit characters) before calling the LLM, so plain digit input like `"4321"` is never sent to the model.
- **Expiry parsing fallback**: when the regex `(\d{1,2})[/\s-](\d{2,4})` doesn't match, the LLM handles natural language like `"December 2027"` or `"Dec 27"`.

Every other field — Aadhaar last 4, pincode, card number, CVV, amount, cardholder name — is parsed by deterministic validators. If a 4-digit string can only ever mean one thing, sending it to an LLM adds latency, cost, and a new failure mode for no benefit.

### 3. I considered LLM-driven off-script handling and rejected it

I prototyped a `smart_reply` function that would generate contextual responses when the user said something unexpected (e.g., "what payment methods can I use?" at the amount step). I removed it before submission.

The brief evaluates context handling, verification logic, tool usage, and failure handling — none of which require contextual reply generation. Adding an LLM in the response path introduces:

- **Nondeterminism** — the brief explicitly requires deterministic behavior across runs.
- **Latency** — every off-script turn waits on a network call.
- **Capability hallucination** — testing showed the model would offer features the agent doesn't have ("UPI, net banking, wallets") even when the system prompt explicitly forbade it.
- **A larger surface for account data exposure** — every prompt is a potential leak vector.

Hardcoded redirects with explicit constraint reminders ("we accept credit or debit cards only") cover the same cases reliably and predictably. The LLM is reserved for the one job rules genuinely cannot do well.

### 4. Sequential collection, with one-shot pre-fill for the common out-of-order case

The agent asks for the name first, then the secondary factor, in two separate turns. An earlier version tried to accept both in a single free-form blob ("My name is Nithin and DOB is 1990-05-14") — this required pending slots, regex-based name extraction (to preserve casing the LLM would otherwise normalize), and ~70 lines of merging logic.

Sequential collection eliminated all of that. Each handler does exactly one thing.

The brief calls out one specific out-of-order case: *"user provides name before being asked."* This is supported. After a successful account lookup, if the user's message contained text beyond the account ID, the LLM is asked once whether a full name is present. If found and it matches the account on file, the agent skips `AWAIT_NAME` entirely and prompts for the secondary factor. If the volunteered name doesn't match (or no name was found), the agent silently falls through to the standard "please share your name" prompt — without counting it as a failed verification attempt, since the user was trying to be helpful, not to authenticate.

Pre-filling the secondary factor (DOB / Aadhaar / pincode) was deliberately not implemented. Doing so would either require multi-field extraction in the same turn (the complexity we removed) or echoing back guesses about what the user provided ("I see you mentioned a date — confirming?"), which leaks account-shape information.

### 5. Smart retry within verification

On a verification failure, the agent stays on the *failing* step rather than restarting from the beginning. If the user's name was correct but their DOB didn't match, they only re-enter the DOB. This preserves user effort without reintroducing the multi-field extraction complexity — `self._state` already tells us which step failed, so the bookkeeping is free.

### 6. Retry policy

- **Verification**: 3 total attempts across name and secondary failures combined, then `LOCKED`.
- **Card payment**: 3 attempts for retryable errors (`invalid_card`, `invalid_cvv`, `invalid_expiry`). On retry, all card fields are re-collected — partial card data is never reused.
- **Terminal errors** (`insufficient_balance`, `account_not_found`, persistent connection failures): close the session cleanly with a clear message.

### 7. Sensitive data handling

`_account_data` is stored on the Agent object but never appears in any user-facing message. The card dict (`self._card`) is held only for the duration of one payment attempt; on a retryable failure it's wiped before re-collecting. No account data ever enters an LLM prompt — `extract_fields` only sees the user's input plus the field name to extract.

### 8. Zero balance shortcut

If `lookup_account` returns `balance ≤ 0`, the agent transitions directly to `DONE` without asking for verification — there's nothing to charge.

### 9. One payment per session

After a successful payment (or terminal failure), the agent enters `DONE` and does not offer another payment. The brief asks the agent to *"recap and close the conversation"* — that's a goodbye, not a multi-payment loop. Card data is cleared from memory immediately after a successful charge. If the user wants to make another payment, they start a new session, which restarts identity verification from scratch — the secure default for a payment system.

---

## Tradeoffs Accepted

| Tradeoff | Reason |
|---|---|
| LLM extraction can fail on unusual date formats | Acceptable — agent re-prompts gracefully with a clear example, doesn't crash |
| Sessions are in-memory in `server.py` | Fine for the assignment scope; production would use Redis |
| No rate limiting on the FastAPI server | Out of scope for the assignment; would matter the moment this had a public URL |
| Off-script user messages get hardcoded redirects, not LLM-generated nudges | Deliberate — see Decision #3 |
| Cardholder name is accepted as typed | Per the API spec, the server doesn't validate it against the account holder |
| Live SSE log panel echoes raw user messages | **Demo only.** The right-hand log panel exists to showcase the agent's internal flow for the assignment review — state transitions, tool calls, and LLM activity. In a real deployment, the chat handler would redact card fields based on the current state before logging, and the SSE stream would be scoped to a single session rather than broadcast globally. Both are out of scope for the assignment. |

---

## What I Would Improve With More Time

1. **Streaming responses** — FastAPI could stream the agent's reply token by token for a smoother UI.
2. **Persisted sessions** — Redis-backed session store so conversations survive server restarts and the app can scale horizontally.
3. **Rate limiting + abuse protection** — per-IP limits on `/chat`, scoped SSE streams, basic bot detection. Necessary for any public deployment.
4. **LLM-based evaluator harness** — a second agent simulating different user personas (impatient, confused, adversarial, distracted) running through the flow and scoring responses against rubrics.
5. **Structured audit logging** — every state transition and API call written to a log store with PII redacted, suitable for compliance review.
6. **Internationalization** — copy is currently hardcoded English with `₹`. The hardcoded-template choice means moving this to i18n is a clean refactor: extract the inlined strings into a message catalog at the boundary, rather than rewriting the agent.

---

## Evaluation Approach

### Test suite

`test_agent.py` contains 127 tests across 15 categories, runnable with `pytest test_agent.py -v`. The suite runs without any live API calls — all tool and LLM calls are mocked.

| Category | Tests | What's covered |
|---|---|---|
| Validator unit tests | 38 | Luhn, expiry, DOB, amount, Aadhaar/pincode parsing — all branches |
| LLM extraction | 10 | DOB normalization, expiry fallback, deterministic paths that skip the LLM |
| Full happy-path flows | 9 | Aadhaar, pincode, DOB, partial payment, leap-year account, Amex, Mastercard |
| Verification failures | 9 | Wrong name, wrong secondary, case sensitivity, lockout, smart retry |
| Payment failures | 5 | Invalid card/CVV (retryable), expired card, invalid Luhn, zero balance |
| Account lookup | 4 | Not found, timeout, stored correctly, sensitive data not echoed |
| Security | 4 | DOB/Aadhaar never echoed, skip-verification blocked, payment unreachable |
| Edge cases | 8 | Cancel/exit/quit, gibberish input, empty input, decline at confirmation |
| State machine integrity | 9 | State after every transition, LOCKED/CANCELLED/DONE correctness |
| Out-of-order name | 5 | Name volunteered with account ID, wrong name no penalty, long names, bare ID no LLM |
| Card data security | 2 | Card cleared after success and after retryable failure |
| Card attempt exhaustion | 2 | Three retryable failures → DONE; two failures → still retryable |
| Natural-language expiry | 3 | Month-name via LLM, numeric via fast-path (LLM not called), garbage input |
| Terminal state permanence | 3 | LOCKED, DONE, CANCELLED absorb all further input |
| Non-retryable errors | 3 | `insufficient_balance`, `connection_error` → DONE, never back to card collection |

### What "correct" means per step

**Verification**: correct means exact string equality — `"Nithin Jain"` and `"nithin jain"` must produce different outcomes. The test `test_name_case_sensitive` asserts this directly. Retry counting is correct if `_verify_attempts` increments on every failure and `LOCKED` is reached on the third.

**Tool calling**: correct means the API is called once, at the right moment, with a validated payload. `test_invalid_card_rejected_locally` and `test_expired_card_rejected_locally` verify that the API is never called when local validation fails — if they pass, the validators are acting as a proper gate.

**Failure handling**: correct means retryable errors (invalid card, wrong CVV, invalid expiry) loop back to `AWAIT_CARD_NUMBER` with cleared card data, and non-retryable errors (insufficient balance, connection failure) move to `DONE`. The distinction is tested explicitly in `TestCardAttemptExhaustion` and `TestNonRetryablePaymentErrors`.

**State machine**: correct means every handler is only reachable in the right sequence and terminal states are truly terminal. `TestTerminalStatePermanence` drives multiple inputs into `LOCKED`, `DONE`, and `CANCELLED` to verify they absorb everything cleanly.

### Where the agent struggles

**Ambiguous short inputs at the secondary step.** A 4-digit string like `"1234"` that doesn't match the Aadhaar is treated as a failed Aadhaar attempt, not a possible year fragment. This is correct behavior (and what the tests assert), but a user typing part of a date (`"1990"`) would get an unintuitive failure message. In production, a clarifying prompt ("did you mean a date or an Aadhaar number?") would help.

**Off-script inputs with no digits at the amount step.** "What's the minimum I can pay?" receives the generic validator error ("Please enter a valid number") which is technically correct but feels blunt. Without `smart_reply`, the agent can't distinguish between a malformed number and a genuine question. This is a known tradeoff — see Decision #3.

**LLM date parsing on edge cases.** The agent relies on `gpt-4o-mini` to correctly parse and reject invalid dates (e.g., 29 Feb in a non-leap year). `validate_dob` provides a hard backstop, but if the LLM returns a plausible-looking but wrong date string, the backstop only catches structural invalidity, not semantic incorrectness. Testing this with a live LLM produces the right results; a heavily fine-tuned or quantized model might not.
