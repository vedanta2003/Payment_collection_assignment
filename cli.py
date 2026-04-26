#!/usr/bin/env python3
"""Interactive CLI — lets you chat with the agent in your terminal."""
import os
import sys

def main():
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set.")
        print("Run: export OPENAI_API_KEY=your_key_here")
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
            if user_input.lower() in {"cancel", "exit", "quit"}:
                break
        except (KeyboardInterrupt, EOFError):
            print("\n\nSession ended.")
            break

if __name__ == "__main__":
    main()
