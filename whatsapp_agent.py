from flask import Flask, request
import anthropic
import requests
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Store conversation history
conversations = {}

SHOP_NAME = "Fresh Mart Supermarket"
SHOP_PRODUCTS = """
- Rice (5kg bag) — 25 AED — In Stock
- Rice (10kg bag) — 45 AED — In Stock
- Cooking Oil (1L) — 12 AED — In Stock
- Cooking Oil (2L) — 22 AED — In Stock
- Sugar (1kg) — 8 AED — In Stock
- Milk (1L) — 6 AED — In Stock
- Eggs (12 pack) — 14 AED — In Stock
- Bread (loaf) — 5 AED — In Stock
- Water (12 bottles) — 20 AED — In Stock
- Tomatoes (1kg) — 7 AED — Out of Stock
"""

SYSTEM_PROMPT = f"""You are a friendly shop assistant for {SHOP_NAME}.
Your job:
1. Greet the customer warmly
2. Help them find products and prices
3. Take their order step by step
4. Ask for their delivery address
5. Calculate total price including delivery
6. Confirm the order clearly

Products:
{SHOP_PRODUCTS}

Delivery charge: 10 AED
Free delivery on orders above 100 AED
Shop hours: 8am to 10pm
Keep replies short and friendly.
If customer is angry — say manager will call back shortly."""

def send_whatsapp_message(to, message):
    url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    response = requests.post(url, headers=headers, json=data)
    print(f"WhatsApp API Response: {response.status_code}")
    print(f"Response details: {response.text}")

def get_ai_reply(sender, message):
    if sender not in conversations:
        conversations[sender] = []
    
    conversations[sender].append({
        "role": "user",
        "content": message
    })
    
    # Keep last 10 messages only
    if len(conversations[sender]) > 10:
        conversations[sender] = conversations[sender][-10:]
    
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=conversations[sender]
    )
    
    reply = response.content[0].text
    
    conversations[sender].append({
        "role": "assistant",
        "content": reply
    })
    
    return reply

# Webhook verification
@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook verified!")
        return challenge, 200
    return "Forbidden", 403

# Receive messages
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    
    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]
        
        if "messages" in value:
            message = value["messages"][0]
            sender = message["from"]
            
            if message["type"] == "text":
                text = message["text"]["body"]
                print(f"Message from {sender}: {text}")
                
                reply = get_ai_reply(sender, text)
                send_whatsapp_message(sender, reply)
                print(f"Reply sent: {reply}")
    
    except Exception as e:
        print(f"Error: {e}")
    
    return "OK", 200

if __name__ == "__main__":
    print("=" * 45)
    print("  ShopBot WhatsApp Agent is LIVE!")
    print("  Waiting for WhatsApp messages...")
    print("=" * 45)
    app.run(port=5000, debug=True)