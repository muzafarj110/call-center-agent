from flask import Flask, request
import anthropic
import requests
import gspread
from google.oauth2.service_account import Credentials
import os
import json
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
pending_orders = {}

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
            products += f"- {row['Product']} — {row['Price_AED']} AED — {stock_status}\n"
        return products
    except Exception as e:
        print(f"Sheet error: {e}")
        return "Products temporarily unavailable"

def save_order(phone, items, total, address):
    try:
        sh = get_sheet()
        worksheet = sh.worksheet("Orders")
        order_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        worksheet.append_row([
            order_id,
            phone,
            items,
            total,
            address,
            "New",
            now
        ])
        return order_id
    except Exception as e:
        print(f"Order save error: {e}")
        return "ORD000"

SHOP_NAME = "Fresh Mart Supermarket"

def get_system_prompt():
    products = get_products()
    return f"""You are a friendly shop assistant for {SHOP_NAME}.

Your job:
1. Greet the customer warmly
2. Help them find products and prices
3. Take their order step by step
4. Ask for their delivery address
5. Calculate total price including delivery
6. Confirm the order clearly
7. When order is confirmed say exactly: ORDER_CONFIRMED:[items]|[total]|[address]

Products:
{products}

Delivery charge: 10 AED
Free delivery on orders above 100 AED
Shop hours: 8am to 10pm
Keep replies short and friendly.
If customer is angry — say manager will call back shortly.

Important: When customer confirms order, end your message with:
ORDER_CONFIRMED:[list of items]|[total amount]|[delivery address]"""

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

    if len(conversations[sender]) > 10:
        conversations[sender] = conversations[sender][-10:]

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=500,
        system=get_system_prompt(),
        messages=conversations[sender]
    )

    reply = response.content[0].text

    conversations[sender].append({
        "role": "assistant",
        "content": reply
    })

    # Check if order is confirmed
    if "ORDER_CONFIRMED:" in reply:
        try:
            order_data = reply.split("ORDER_CONFIRMED:")[1].strip()
            parts = order_data.split("|")
            items = parts[0]
            total = parts[1]
            address = parts[2]
            order_id = save_order(sender, items, total, address)
            reply = reply.split("ORDER_CONFIRMED:")[0].strip()
            reply += f"\n\n✅ Order confirmed!\n📦 Order ID: {order_id}\n🚚 We will deliver soon!"
        except Exception as e:
            print(f"Order processing error: {e}")

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
                reply = get_ai_reply(sender, text)
                send_whatsapp_message(sender, reply)
                print(f"Reply sent: {reply}")
    except Exception as e:
        print(f"Error: {e}")
    return "OK", 200

if __name__ == "__main__":
    print("=" * 45)
    print(f"  {SHOP_NAME} — Order Management LIVE!")
    print("  Orders saved to Google Sheet!")
    print("=" * 45)
    app.run(port=5000, debug=True)