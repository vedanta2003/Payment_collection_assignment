# Design Document — PayAssist Agent

## Architecture Overview

The agent is built as a **hybrid state machine + LLM** system.

### Core principle
Business logic lives in pure Python. The LLM is a tool, not the decision-maker.

```
User input
    ↓
State machine (agent.py) — decides what step we're on
    ↓
LLM extractor (llm.py) — parses messy text into structured fields
    ↓
Validators (validators.py) — checks fields before any API call
    ↓
API client (tools.py) — calls Prodigal's endpoints
    ↓
Response generator (llm.py) — produces natural reply
    ↓
Output
```

### State machine
The agent moves through these states in sequence. Transitions are only triggered by explicit conditions in code — never by the LLM:

```
GREETING → AWAIT_ACCOUNT_ID → AWAIT_NAME → AWAIT_SECONDARY
→ AWAIT_AMOUNT → AWAIT_CARD_NUMBER → AWAIT_CVV
→ AWAIT_EXPIRY → AWAIT_CARDHOLDER → CONFIRM_PAYMENT
→ DONE / LOCKED / CANCELLED
```

---

## Key Decisions

### 1. LLM-driven vs rule-based verification
**Decision**: Verification is pure Python code.

The assignment says "strict, no fuzzy matching." If the LLM handled verification, that guarantee would only be as strong as the prompt. A prompt can drift, hallucinate, or interpret "Nithin jain" as matching "Nithin Jain." Code cannot. The state machine does exact string comparison:

```python
if name != self._account_data["full_name"]:
    return self._verification_failed()
```

This is auditable, testable, and deterministic.

### 2. Where the LLM IS used
The LLM handles two narrow tasks:
- **Extraction**: converting "my dob is 14th may 1990" → `1990-05-14`
- **Generation**: turning intent codes like `"verification_success"` into natural sentences

This keeps the LLM in its zone of genuine competence (NLU/NLG) and out of business logic.

### 3. Retry logic
- Verification: 3 attempts max, then `LOCKED` state
- Card payment: 3 attempts for retryable errors (invalid_card, invalid_cvv, invalid_expiry)
- Terminal errors (insufficient_balance, connection_error after retry) close the session cleanly

### 4. Sensitive data handling
`_account_data` is stored on the Agent object but never included in any user-facing message. Response generation templates never reference DOB, Aadhaar, or pincode. Card details are stored only in `self._card` for the duration of one payment attempt and are never echoed back.

### 5. Zero balance shortcut
If the account lookup returns balance ≤ 0, the agent transitions directly to `DONE` and informs the user — avoiding unnecessary verification steps.

---

## Tradeoffs Accepted

| Tradeoff | Reason |
|---|---|
| LLM extraction can fail on very unusual inputs | Acceptable — agent re-prompts gracefully rather than crashing |
| Sessions are in-memory (not persisted) | Fine for a demo; production would use Redis |
| No rate limiting on the FastAPI server | Out of scope for this assignment |
| Response templates are hardcoded strings | Faster to audit than LLM-generated responses for every turn |

---

## What I Would Improve With More Time

1. **Streaming responses** — the FastAPI endpoint could stream the agent's reply token by token for a smoother UI
2. **Persisted sessions** — Redis or a database so sessions survive server restarts
3. **LLM-based evaluator** — a second agent that simulates different user personas and scores the agent's responses
4. **Partial field collection** — if the user provides name and DOB in one message, collect both at once instead of asking for secondary after name
5. **Audit logging** — structured logs of every state transition and API call, with PII redacted
6. **Rate limiting + session expiry** — production necessities
