from flask import Flask, request
import anthropic
import requests
import gspread
from google.oauth2.service_account import Credentials
import os
import random
import string
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
SHEET_ID = "1yz4dvLvqjldeAER4FijQgPZzLshNO9VQc1EVSJZYqdM"

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
conversations = {}
waiting_confirmation = {}

def get_sheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(
        "credentials.json", scopes=scope)
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID)

def get_products():
    try:
        sh = get_sheet()
        worksheet = sh.worksheet("Products")
        records = worksheet.get_all_records()
        products = ""
        for row in records:
            stock_status = "In Stock" if int(row['Stock']) > 0 else "Out of Stock"
            products += f"- {row['Product']} -- {row['Price_AED']} AED -- {stock_status}\n"
        return products
    except Exception as e:
        print(f"Sheet error: {e}")
        return "Products temporarily unavailable"

def save_order(phone, items, total, address):
    try:
        sh = get_sheet()
        worksheet = sh.worksheet("Orders")
        order_id = ''.join(random.choices(
            string.ascii_uppercase + string.digits, k=6))
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        worksheet.append_row([
            order_id,
            phone,
            items,
            str(total),
            address,
            "New",
            now
        ])
        print(f"Order saved! ID: {order_id}")
        return order_id
    except Exception as e:
        print(f"Order save error: {e}")
        return "ORD000"

def extract_order_from_conversation(sender):
    try:
        history = conversations.get(sender, [])
        conversation_text = ""
        for msg in history:
            role = "Customer" if msg["role"] == "user" else "Agent"
            conversation_text += f"{role}: {msg['content']}\n"

        extract_prompt = f"""Extract order details from this conversation.
Return ONLY in this exact format:
ITEMS: [items and quantities]
TOTAL: [number only no currency]
ADDRESS: [delivery address]

If any detail is missing return: INCOMPLETE

Conversation:
{conversation_text}"""

        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=300,
            messages=[{"role": "user", "content": extract_prompt}]
        )

        result = response.content[0].text.strip()
        print(f"Extracted: {result}")

        if "INCOMPLETE" in result:
            return None

        items = ""
        total = ""
        address = ""

        for line in result.split("\n"):
            if line.startswith("ITEMS:"):
                items = line.replace("ITEMS:", "").strip()
            elif line.startswith("TOTAL:"):
                total = line.replace("TOTAL:", "").strip()
            elif line.startswith("ADDRESS:"):
                address = line.replace("ADDRESS:", "").strip()

        if items and total and address:
            return {"items": items, "total": total, "address": address}
        return None

    except Exception as e:
        print(f"Extract error: {e}")
        return None

SHOP_NAME = "Fresh Mart Supermarket"

def get_system_prompt():
    products = get_products()
    return f"""You are a friendly shop assistant for {SHOP_NAME}.

ORDER PROCESS:
1. Greet customer
2. Help them choose products
3. Ask for delivery address
4. Show order summary with total
5. Ask customer: "Shall I confirm your order? Reply YES to confirm."
6. Wait for customer to say YES

Important: Always ask for delivery address before confirming.
Always show total before asking for confirmation.

Products:
{products}

Delivery: 10 AED
Free delivery above 100 AED
Hours: 8am-10pm
Keep replies short and friendly."""

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

    if len(conversations[sender]) > 20:
        conversations[sender] = conversations[sender][-20:]

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1000,
        system=get_system_prompt(),
        messages=conversations[sender]
    )

    reply = response.content[0].text
    print(f"AI Reply: {reply}")

    conversations[sender].append({
        "role": "assistant",
        "content": reply
    })

    return reply

def is_confirmation(text):
    confirm_words = ["yes", "confirm", "ok", "okay", "sure", 
                     "proceed", "place order", "confirmed",
                     "yes please", "yep", "yeah", "go ahead"]
    return text.lower().strip() in confirm_words

@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook verified!")
        return challenge, 200
    return "Forbidden", 403

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

                if text.lower() == "/start":
                    conversations[sender] = []
                    waiting_confirmation[sender] = False
                    send_whatsapp_message(
                        sender,
                        f"Welcome to {SHOP_NAME}! How can I help you today?")
                    return "OK", 200

                # Check if waiting for confirmation and customer says YES
                if waiting_confirmation.get(sender) and is_confirmation(text):
                    print(f"Confirmation received from {sender}!")
                    order = extract_order_from_conversation(sender)

                    if order:
                        order_id = save_order(
                            sender,
                            order["items"],
                            order["total"],
                            order["address"]
                        )
                        waiting_confirmation[sender] = False
                        reply = f"Your order has been placed!\n\nOrder ID: {order_id}\nItems: {order['items']}\nTotal: {order['total']} AED\nDelivery to: {order['address']}\n\nWe will deliver between 8am-10pm.\nKeep your Order ID for follow up.\nThank you for shopping with {SHOP_NAME}!"
                        send_whatsapp_message(sender, reply)
                        return "OK", 200
                    else:
                        send_whatsapp_message(
                            sender,
                            "Sorry, I could not get your order details. Please type /start and try again.")
                        return "OK", 200

                reply = get_ai_reply(sender, text)

                # Check if agent asked for confirmation
                if "shall i confirm" in reply.lower() or "reply yes" in reply.lower():
                    waiting_confirmation[sender] = True
                    print(f"Waiting for confirmation from {sender}")

                send_whatsapp_message(sender, reply)

    except Exception as e:
        print(f"Error: {e}")
    return "OK", 200

if __name__ == "__main__":
    print("=" * 45)
    print(f"  {SHOP_NAME}")
    print("  Order Management System LIVE!")
    print("=" * 45)
    app.run(port=5000, debug=True)