# PayAssist — Payment Collection AI Agent

A conversational AI agent for end-to-end payment collection, built with a deterministic state machine and OpenAI GPT-4o-mini for natural language understanding.

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set your OpenAI API key
```bash
export OPENAI_API_KEY=your_key_here
```

### 3. Run the web UI (recommended)
```bash
python -m uvicorn server:app --reload --port 8000
```
Then open **http://localhost:8000** in your browser.

### 4. Or run in the terminal
```bash
python cli.py
```

### 5. Run tests
```bash
pytest tests/ -v
```

---

## Project Structure

```
payment_agent/
├── agent.py          # Core Agent class — state machine
├── validators.py     # Pure validation: Luhn, expiry, dates
├── tools.py          # HTTP calls to Prodigal's API
├── llm.py            # OpenAI wrapper (NLU + response generation)
├── server.py         # FastAPI server
├── cli.py            # Terminal interface
├── static/
│   └── index.html    # Professional chat UI
├── tests/
│   └── test_agent.py # pytest suite
└── requirements.txt
```

---

## Architecture

The agent uses a **hybrid state machine + LLM** approach:

- **State machine** (Python) — controls the flow, enforces verification logic, counts retries, decides when to call APIs. All business rules are deterministic code.
- **LLM** (GPT-4o-mini) — used only for two things: (1) extracting structured fields from messy user input, (2) generating natural response text.

This means verification is always strict (exact match) and auditable, while the agent still handles natural language gracefully.

### States
```
GREETING → AWAIT_ACCOUNT_ID → AWAIT_NAME → AWAIT_SECONDARY
→ AWAIT_AMOUNT → AWAIT_CARD_NUMBER → AWAIT_CVV
→ AWAIT_EXPIRY → AWAIT_CARDHOLDER → CONFIRM_PAYMENT → DONE
```

---

## Sample Conversations

### 1. Successful payment

```
Agent: Welcome to PayAssist. Please share your account ID.
User:  ACC1001
Agent: Thank you. Could you please confirm your full name?
User:  Nithin Jain
Agent: To verify your identity, please provide your DOB, Aadhaar last 4, or pincode.
User:  1990-05-14
Agent: Identity verified. Your outstanding balance is ₹1,250.75. How much would you like to pay?
User:  500
Agent: Please enter your card number.
User:  4532015112830366
Agent: Please enter your CVV.
User:  123
Agent: Please enter your card expiry (e.g. 12 2027).
User:  12 2027
Agent: Please enter the cardholder name.
User:  Nithin Jain
Agent: I'll process ₹500.00 on your card ending in 0366. Shall I proceed? (yes/no)
User:  yes
Agent: Payment of ₹500.00 processed successfully. Transaction ID: txn_1762510325322_l1fl4oy
```

### 2. Verification failure (exhausts retries)

```
Agent: Welcome to PayAssist. Please share your account ID.
User:  ACC1001
Agent: Thank you. Could you please confirm your full name?
User:  John Doe
Agent: To verify, please provide your DOB, Aadhaar last 4, or pincode.
User:  1990-05-14
Agent: The details don't match. You have 2 attempt(s) remaining.
User:  John Doe — 1234
Agent: The details don't match. You have 1 attempt(s) remaining.
User:  John Doe — 999999
Agent: We were unable to verify your identity. Session locked. Please contact support.
```

### 3. Invalid card (retryable)

```
...verified...
Agent: Please enter your card number.
User:  1234123412341234
Agent: Card number is invalid (failed Luhn check).
User:  4532015112830366
Agent: Please enter your CVV.
...continues normally...
```

### 4. Edge case — leap year (ACC1004)

```
User:  ACC1004
Agent: Could you confirm your full name?
User:  Rahul Mehta
Agent: Please provide DOB, Aadhaar last 4, or pincode.
User:  1988-02-29       ← valid! 1988 is a leap year
Agent: Identity verified. Your balance is ₹3,200.50.
User:  1989-02-29       ← if they try this instead
Agent: I didn't catch that. Please provide DOB as YYYY-MM-DD.
```

---

## Test Accounts

| Account | Name | DOB | Aadhaar Last 4 | Pincode | Balance |
|---------|------|-----|----------------|---------|---------|
| ACC1001 | Nithin Jain | 1990-05-14 | 4321 | 400001 | ₹1,250.75 |
| ACC1002 | Rajarajeswari Balasubramaniam | 1985-11-23 | 9876 | 400002 | ₹540.00 |
| ACC1003 | Priya Agarwal | 1992-08-10 | 2468 | 400003 | ₹0.00 |
| ACC1004 | Rahul Mehta | 1988-02-29 | 1357 | 400004 | ₹3,200.50 |
