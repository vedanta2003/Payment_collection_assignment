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

Terminal:        LOCKED, CANCELLED
Repeat-payment:  AWAIT_SAME_OR_NEW, AWAIT_SAME_CARD
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

### 4. Sequential collection over multi-field extraction

The agent asks for the name first, then the secondary factor, in two separate turns. An earlier version tried to accept both in a single free-form blob ("My name is Nithin and DOB is 1990-05-14") — this required pending slots, regex-based name extraction (to preserve casing the LLM would otherwise normalize), and ~70 lines of merging logic.

Sequential collection eliminated all of that. Each handler does exactly one thing. The brief's "handle out-of-order information" requirement is satisfied by tolerating an account ID volunteered before being asked, but doesn't require parsing arbitrary multi-field messages.

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

---

## Tradeoffs Accepted

| Tradeoff | Reason |
|---|---|
| LLM extraction can fail on unusual date formats | Acceptable — agent re-prompts gracefully with a clear example, doesn't crash |
| Sessions are in-memory in `server.py` | Fine for the assignment scope; production would use Redis |
| No rate limiting on the FastAPI server | Out of scope for the assignment; would matter the moment this had a public URL |
| Off-script user messages get hardcoded redirects, not LLM-generated nudges | Deliberate — see Decision #3 |
| Cardholder name is accepted as typed | Per the API spec, the server doesn't validate it against the account holder |

---

## What I Would Improve With More Time

1. **Streaming responses** — FastAPI could stream the agent's reply token by token for a smoother UI.
2. **Persisted sessions** — Redis-backed session store so conversations survive server restarts and the app can scale horizontally.
3. **Rate limiting + abuse protection** — per-IP limits on `/chat`, scoped SSE streams, basic bot detection. Necessary for any public deployment.
4. **LLM-based evaluator harness** — a second agent simulating different user personas (impatient, confused, adversarial, distracted) running through the flow and scoring responses against rubrics.
5. **Structured audit logging** — every state transition and API call written to a log store with PII redacted, suitable for compliance review.
6. **Internationalization** — copy is currently hardcoded English with `₹`. The hardcoded-template choice means moving this to i18n is a clean refactor: extract the inlined strings into a message catalog at the boundary, rather than rewriting the agent.
