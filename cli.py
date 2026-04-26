#!/usr/bin/env python3
"""Interactive CLI — chat with the agent in your terminal.

This is a fallback for environments where you can't run the FastAPI server.
The web UI (`uvicorn server:app`) is the recommended way to interact with
the agent — it shows a live log panel of state transitions, API calls, and
LLM activity that's useful for assignment review.
"""
import os
import sys

# Load .env if present, so users don't have to export OPENAI_API_KEY manually
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional


TERMINAL_STATES = {"DONE", "LOCKED", "CANCELLED"}


def main():
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set.")
        print("Either export it: export OPENAI_API_KEY=sk-...")
        print("Or add it to a .env file in the project root.")
        sys.exit(1)

    from agent import Agent
    agent = Agent()

    print("\n" + "─" * 50)
    print("  PayAssist — Terminal Mode")
    print("  Type 'cancel' or Ctrl+C to exit")
    print("─" * 50 + "\n")

    # Greeting
    resp = agent.next("")
    print(f"Agent: {resp['message']}\n")

    while True:
        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            resp = agent.next(user_input)
            print(f"\nAgent: {resp['message']}\n")

            # Stop once the agent reaches any terminal state
            if agent._state.name in TERMINAL_STATES:
                print("─" * 50)
                print("  Session ended.")
                print("─" * 50 + "\n")
                break

        except (KeyboardInterrupt, EOFError):
            print("\n\nSession ended.")
            break


if __name__ == "__main__":
    main()