import anthropic
import os
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# =============================================
# SHOP CONFIGURATION — change this per client
# =============================================
SHOP_NAME = "Day Mart Supermarket"
SHOP_PRODUCTS = """
- Rice (5kg bag) — 25 AED — In Stock
- Rice (10kg bag) — 45 AED — In Stock
- Cooking Oil (1L) — 12 AED — In Stock
- Cooking Oil (2L) — 22 AED — In Stock
- Sugar (1kg) — 8 AED — In Stock
- Sugar (2kg) — 15 AED — In Stock
- Milk (1L) — 6 AED — In Stock
- Eggs (12 pack) — 14 AED — In Stock
- Bread (loaf) — 5 AED — In Stock
- Water (12 bottles) — 20 AED — In Stock
- Tomatoes (1kg) — 7 AED — Out of Stock
- Onions (1kg) — 5 AED — In Stock
"""
DELIVERY_CHARGE = 10
FREE_DELIVERY_ABOVE = 100
SHOP_HOURS = "8am to 10pm, 7 days a week"
CONTACT_NUMBER = "+971 50 123 4567"

# =============================================
SYSTEM_PROMPT = f"""You are a friendly shop assistant for {SHOP_NAME}.

Your job:
1. Greet the customer warmly
2. Help them find products and prices
3. Take their order step by step
4. Ask for their delivery address
5. Calculate total price including delivery
6. Confirm the order clearly

Products we have:
{SHOP_PRODUCTS}

Delivery charge: {DELIVERY_CHARGE} AED
Free delivery on orders above {FREE_DELIVERY_ABOVE} AED
Shop hours: {SHOP_HOURS}
Contact: {CONTACT_NUMBER}

Rules:
- If item is Out of Stock, apologize and suggest alternatives
- Always confirm the full order before finishing
- Be friendly, short, and clear
- If customer is angry or has a complaint, say a manager will call them back shortly
"""

print("=" * 45)
print(f"  {SHOP_NAME}")
print("  Day Mart Shop Assistant ")
print("  Type 'quit' to exit")
print("=" * 45)

history = []

while True:
    user_input = input("\nCustomer: ")

    if user_input.lower() == "quit":
        print("Assistant stopped. Goodbye!")
        break

    history.append({"role": "user", "content": user_input})

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=history
    )

    reply = response.content[0].text
    history.append({"role": "assistant", "content": reply})

    print(f"\nAgent: {reply}")