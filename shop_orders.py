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

SHOP_NAME = "Fresh Mart Supermarket"

def get_system_prompt():
    products = get_products()
    return f"""You are a friendly shop assistant for {SHOP_NAME}.

STEP BY STEP ORDER PROCESS:
Step 1 - Greet customer
Step 2 - Help them choose products
Step 3 - Ask for delivery address
Step 4 - Show order summary and ask YES or NO
Step 5 - When customer says YES - reply with ONLY this exact format:

SAVE_ORDER
items: [list items here]
total: [number only]
address: [address here]
END_ORDER

Then thank the customer normally.

Products available:
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

def extract_and_save_order(sender, reply):
    if "SAVE_ORDER" in reply and "END_ORDER" in reply:
        try:
            print("Order detected! Saving...")
            order_section = reply.split("SAVE_ORDER")[1].split("END_ORDER")[0]
            lines = order_section.strip().split("\n")

            items = ""
            total = ""
            address = ""

            for line in lines:
                if line.startswith("items:"):
                    items = line.replace("items:", "").strip()
                elif line.startswith("total:"):
                    total = line.replace("total:", "").strip()
                elif line.startswith("address:"):
                    address = line.replace("address:", "").strip()

            print(f"Items: {items}")
            print(f"Total: {total}")
            print(f"Address: {address}")

            order_id = save_order(sender, items, total, address)

            clean_reply = reply.split("SAVE_ORDER")[0].strip()
            if "END_ORDER" in reply:
                after_order = reply.split("END_ORDER")[1].strip()
                if after_order:
                    clean_reply += "\n" + after_order

            clean_reply += f"\n\nOrder confirmed!\nOrder ID: {order_id}\nDelivery coming soon!\nTotal: {total} AED"
            return clean_reply

        except Exception as e:
            print(f"Order extraction error: {e}")
            return reply
    return reply

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

    reply = extract_and_save_order(sender, reply)

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

                if text.lower() == "/start":
                    conversations[sender] = []
                    send_whatsapp_message(
                        sender,
                        f"Welcome to {SHOP_NAME}! How can I help you today?")
                    return "OK", 200

                reply = get_ai_reply(sender, text)
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