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
order_stage = {}

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
            stock_status = "In Stock" if int(
                row['Stock']) > 0 else "Out of Stock"
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
        print(f"Order saved in Google Sheet! ID: {order_id}")
        return order_id
    except Exception as e:
        print(f"Order save error: {e}")
        return None

def extract_order_from_conversation(sender):
    try:
        history = conversations.get(sender, [])
        conversation_text = ""
        for msg in history:
            role = "Customer" if msg["role"] == "user" else "Agent"
            conversation_text += f"{role}: {msg['content']}\n"

        extract_prompt = f"""Extract order details from this conversation.
Return ONLY in this exact format with no extra text:
ITEMS: [items and quantities]
TOTAL: [number only no currency symbol]
ADDRESS: [delivery address]

If any detail is missing return exactly: INCOMPLETE

Conversation:
{conversation_text}"""

        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=300,
            messages=[{"role": "user", "content": extract_prompt}]
        )

        result = response.content[0].text.strip()
        print(f"Extracted order details: {result}")

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

def is_address(text):
    address_keywords = [
        "villa", "apartment", "flat", "building", "street",
        "road", "near", "behind", "opposite", "floor",
        "house", "area", "district", "city", "tower",
        "compound", "block", "unit", "office", "shop"
    ]
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in address_keywords)

def is_confirmation(text):
    confirm_words = [
        "yes", "confirm", "ok", "okay", "sure",
        "proceed", "place order", "confirmed",
        "yes please", "yep", "yeah", "go ahead",
        "do it", "correct", "right", "accept"
    ]
    return text.lower().strip() in confirm_words

SHOP_NAME = "Fresh Mart Supermarket"

def get_system_prompt():
    products = get_products()
    return f"""You are a friendly shop assistant for {SHOP_NAME}.

YOUR ONLY JOB:
1. Greet customer
2. Help them choose products
3. When they are done choosing ask for delivery address
4. When customer gives address - show order summary with total
5. End your message with exactly: "Shall I confirm your order? Reply YES to confirm."
6. Stop there - do not confirm the order yourself

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

                # Reset conversation
                if text.lower() == "/start":
                    conversations[sender] = []
                    waiting_confirmation[sender] = False
                    order_stage[sender] = "shopping"
                    send_whatsapp_message(
                        sender,
                        f"Welcome to {SHOP_NAME}! How can I help you today?")
                    return "OK", 200

                # Customer replied YES to confirm order
                if waiting_confirmation.get(sender) and is_confirmation(text):
                    print(f"YES received from {sender}! Saving order...")
                    order = extract_order_from_conversation(sender)

                    if order:
                        order_id = save_order(
                            sender,
                            order["items"],
                            order["total"],
                            order["address"]
                        )

                        if order_id:
                            waiting_confirmation[sender] = False
                            conversations[sender] = []
                            order_stage[sender] = "shopping"
                            reply = (
                                f"Your order has been placed successfully!\n\n"
                                f"Order ID: {order_id}\n"
                                f"Items: {order['items']}\n"
                                f"Total: {order['total']} AED\n"
                                f"Delivery to: {order['address']}\n\n"
                                f"We will deliver between 8am-10pm.\n"
                                f"Please save your Order ID: {order_id}\n"
                                f"Use this ID to follow up on your order.\n\n"
                                f"Thank you for shopping with {SHOP_NAME}!"
                            )
                        else:
                            reply = (
                                "Sorry, there was a problem saving your order. "
                                "Please type /start and try again."
                            )
                    else:
                        reply = (
                            "Sorry, I could not get all your order details. "
                            "Please type /start and try again."
                        )

                    send_whatsapp_message(sender, reply)
                    return "OK", 200

                # Customer says NO to confirmation
                if waiting_confirmation.get(sender) and text.lower() in ["no", "cancel", "stop"]:
                    waiting_confirmation[sender] = False
                    send_whatsapp_message(
                        sender,
                        "No problem! Your order has been cancelled. Type /start to start a new order.")
                    return "OK", 200

                # Normal conversation with AI
                reply = get_ai_reply(sender, text)

                # If address detected - set waiting for confirmation
                if is_address(text) and not waiting_confirmation.get(sender):
                    waiting_confirmation[sender] = True
                    print(f"Address detected! Waiting for YES from {sender}")
                    # Add confirmation request if AI did not include it
                    if "shall i confirm" not in reply.lower():
                        reply += "\n\nShall I confirm your order? Reply YES to confirm or NO to cancel."

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