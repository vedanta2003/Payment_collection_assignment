# PayAssist — Payment Collection AI Agent

A conversational AI agent that handles end-to-end payment collection over chat. Built as a deterministic state machine in Python, with OpenAI GPT-4o-mini used in one narrowly scoped place: parsing free-form date strings into structured form.

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/vedanta2003/Payment_collection_assignment.git
cd Payment_collection_assignment
```

### 2. Create a virtual environment

Recommended on macOS / modern Linux, where system Python often refuses global `pip install`:

```bash
python3 -m venv venv
source venv/bin/activate     # on Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set your OpenAI API key

Either export it for the session:

```bash
export OPENAI_API_KEY=sk-your-key-here
```

…or create a `.env` file in the project root with one line:

```
OPENAI_API_KEY=sk-your-key-here
```

Both `server.py` and `cli.py` will pick it up.

---

## Running it

### Web UI (recommended)

```bash
python -m uvicorn server:app --reload --port 8000
```

Then open **http://localhost:8000** in your browser.

The web UI is the recommended way to interact with the agent for review purposes. The right-hand panel shows a **live agent log** — every state transition, tool call, and LLM extraction streams in as you chat. This makes it easy to see exactly what the agent is doing internally on each turn. (This panel is for demo/review only; it's not part of a production-facing product.)

### Terminal CLI (fallback)

If you can't run a local server or just want a quick test:

```bash
python cli.py
```

Same agent, no log panel, no UI — just back-and-forth in your terminal. Type `cancel` or hit `Ctrl+C` to exit.

### Tests

```bash
pytest test_agent.py -v
```

---

## Troubleshooting

**`error: externally-managed-environment` when running `pip install`** — you skipped step 2 (virtual environment). Modern macOS/Linux distributions block global pip installs. Activate the venv first.

**`OPENAI_API_KEY environment variable not set.`** — your key isn't being picked up. Run `echo $OPENAI_API_KEY` to check; if it's empty, re-export it or check that your `.env` file is in the same directory as `server.py`.

**`Address already in use` on port 8000** — another process is using the port. Either kill it (`lsof -ti:8000 | xargs kill`) or run uvicorn on a different port: `--port 8001`.

**Agent says "I'm having trouble connecting to the server right now"** — this means the Prodigal payment API at `se-payment-verification-api.service.external.usea2.aws.prodigaltech.com` is unreachable. Check your internet connection.

---

## Project Structure

```
payment_agent/
├── agent.py          # Agent class — deterministic state machine
├── validators.py     # Pure validation: Luhn check, expiry, dates, amounts
├── tools.py          # HTTP calls to Prodigal's payment API
├── llm.py            # OpenAI wrapper — extract_fields only
├── server.py         # FastAPI server + SSE log streaming
├── cli.py            # Terminal interface (fallback)
├── static/
│   └── index.html    # Web chat UI with live agent log panel
├── test_agent.py     # pytest suite
├── DESIGN.md         # Design document
└── requirements.txt
```

---

## Architecture (one paragraph)

The state machine in `agent.py` controls everything: which step the conversation is on, when to call the lookup and payment APIs, when verification fails, when retries are exhausted. All business rules live here as plain Python — strict equality for verification, hard retry caps, deterministic transitions.

The LLM (`gpt-4o-mini`) is used in exactly one place: `extract_fields` in `llm.py`. It normalizes free-form date strings — `"29 Feb 1988"`, `"December 2027"`, `"14 May 1990"` — into structured form. Plain digit inputs (Aadhaar last 4, pincode, CVV, card numbers, amounts) skip the LLM entirely and are parsed by deterministic validators.

See `DESIGN.md` for the full reasoning.

### States

```
AWAIT_ACCOUNT_ID → AWAIT_NAME → AWAIT_SECONDARY → AWAIT_AMOUNT
→ AWAIT_CARD_NUMBER → AWAIT_CVV → AWAIT_EXPIRY → AWAIT_CARDHOLDER
→ CONFIRM_PAYMENT → DONE

Terminal: DONE, LOCKED, CANCELLED
```

---

## Sample Conversations

### 1. Successful payment

```
Agent:  Welcome to PayAssist. I'm here to help you settle your outstanding
        balance. To get started, please share your account ID.
User:   ACC1001
Agent:  To verify your identity, please share your full name as it appears
        on the account.
User:   Nithin Jain
Agent:  Thanks. Now please provide one of: date of birth (YYYY-MM-DD or
        e.g. 29 Feb 1988), Aadhaar last 4 digits, or pincode.
User:   1990-05-14
Agent:  Identity verified successfully. Your outstanding balance is
        ₹1250.75. We accept credit or debit cards only. How much would
        you like to pay today? (up to ₹1250.75)
User:   500
Agent:  Please enter your card number.
User:   4532015112830366
Agent:  Please enter your CVV.
User:   123
Agent:  Please enter your card expiry — month and year (e.g. 12 2027).
User:   12 2027
Agent:  Please enter the cardholder name as it appears on the card.
User:   Nithin Jain
Agent:  I'll process a payment of ₹500.00 on your card ending in 0366.
        Shall I proceed? (yes / no)
User:   yes
Agent:  Payment of ₹500.00 processed successfully. Your transaction ID
        is txn_1762510325322_l1fl4oy. Please save this for your records.
        Thank you for using PayAssist.
```

### 2. Verification failure (locks after 3 attempts)

```
Agent:  ...please share your account ID.
User:   ACC1001
Agent:  To verify your identity, please share your full name...
User:   John Doe
Agent:  That name doesn't match our records. You have 2 attempt(s)
        remaining. Please share your full name exactly as it appears
        on the account.
User:   Wrong Name
Agent:  That name doesn't match our records. You have 1 attempt(s)
        remaining. Please share your full name...
User:   Still Wrong
Agent:  We were unable to verify your identity after multiple attempts.
        For security reasons, this session has been locked. Please
        contact our support team for assistance.
```

### 3. Smart retry — right name, wrong secondary

The agent keeps you on whichever step actually failed. If your name matched but your DOB didn't, you don't have to re-enter your name:

```
User:   Nithin Jain
Agent:  Thanks. Now please provide one of: date of birth, Aadhaar last 4,
        or pincode.
User:   9999
Agent:  That doesn't match our records. You have 2 attempt(s) remaining.
        Please provide your date of birth, Aadhaar last 4, or pincode.
User:   4321                ← correct Aadhaar
Agent:  Identity verified successfully. Your outstanding balance is...
```

### 4. Invalid card (retryable up to 3 times)

```
Agent:  Please enter your card number.
User:   1234123412341234
Agent:  I didn't quite catch that. Card number is invalid.
User:   4532015112830366    ← valid Luhn
Agent:  Please enter your CVV.
        ...flow continues normally...
```

### 5. Leap-year edge case (ACC1004)

ACC1004's DOB is 1988-02-29 — intentionally a leap-year date.

```
User:   ACC1004
Agent:  ...please share your full name...
User:   Rahul Mehta
Agent:  Thanks. Now please provide one of: date of birth...
User:   1988-02-29              ← valid (1988 IS a leap year)
Agent:  Identity verified successfully...
```

If a user typos `29 Feb 1989` (1989 is not a leap year), the LLM correctly returns null for the date, and the agent responds:

```
Agent:  I couldn't read that as a valid date or code. Please provide
        your date of birth (e.g. 1990-05-14 or 14 May 1990), Aadhaar
        last 4 digits, or 6-digit pincode.
```

### 6. Natural-language inputs

The LLM handles informal date formats:

```
User:   14th may 1990          → parsed as 1990-05-14
User:   December 2027          → expiry parsed as month=12, year=2027
User:   29 Feb 1988            → parsed as 1988-02-29
User:   feb 29 1989            → returned as null (invalid date), agent re-prompts
```

### 7. Out-of-order info — name volunteered with account ID

If the user provides their name in the same message as the account ID, the agent recognizes it and skips the name step:

```
User:   Hi, my name is Nithin Jain and my account is ACC1001.
Agent:  Thanks, Nithin Jain. Now please provide one of: date of birth
        (YYYY-MM-DD or e.g. 29 Feb 1988), Aadhaar last 4 digits, or
        pincode.
```

If the volunteered name doesn't match the account on file, the agent falls through to the standard prompt without counting it as a failed attempt — the user was trying to be helpful, not to authenticate.

---

## Test Accounts

| Account | Name | DOB | Aadhaar Last 4 | Pincode | Balance |
|---------|------|-----|----------------|---------|---------|
| ACC1001 | Nithin Jain | 1990-05-14 | 4321 | 400001 | ₹1,250.75 |
| ACC1002 | Rajarajeswari Balasubramaniam | 1985-11-23 | 9876 | 400002 | ₹540.00 |
| ACC1003 | Priya Agarwal | 1992-08-10 | 2468 | 400003 | ₹0.00 |
| ACC1004 | Rahul Mehta | 1988-02-29 | 1357 | 400004 | ₹3,200.50 |

ACC1003 has zero balance — the agent recognizes this and exits cleanly without asking for verification.