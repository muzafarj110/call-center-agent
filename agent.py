import anthropic
import os
from dotenv import load_dotenv

# Loads key from .env file — key never touches your code
load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

print("=================================")
print("  Call Center Agent is LIVE!")
print("  Type 'quit' to exit")
print("=================================")

history = []

while True:
    user_input = input("\nYou: ")

    if user_input.lower() == "quit":
        print("Agent stopped. Goodbye!")
        break

    history.append({"role": "user", "content": user_input})

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=500,
        system="You are a helpful call center assistant. You help customers with appointments, orders, and general questions. Be friendly and keep replies short.",
        messages=history
    )

    reply = response.content[0].text
    history.append({"role": "assistant", "content": reply})

    print(f"\nAgent: {reply}")