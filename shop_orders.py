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
order_data = {}

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

def extract_order_details(sender):
    try:
        extract_prompt = f"""Look at this conversation and extract order details.
Return ONLY in this exact format, nothing else:
ITEMS: [list the items and quantities]
TOTAL: [number only, no AED]
ADDRESS: [delivery address]

If you cannot find all 3 details, return:
INCOMPLETE

Conversation:
{str(conversations.get(sender, []))}"""

        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=200,
            messages=[{"role": "user", "content": extract_prompt}]
        )
        
        result = response.content[0].text.strip()
        print(f"Extracted order: {result}")
        
        if "INCOMPLETE" in result:
            return None
            
        lines = result.strip().split("\n")
        items = ""
        total = ""
        address = ""
        
        for line in lines:
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
1. Greet customer warmly
2. Help them choose products
3. Ask for delivery address
4. Show clear order summary
5. Ask customer to confirm with Yes or No
6. When customer says Yes - say "Processing your order now..."

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

    # If customer confirmed order
    if "Processing your order now" in reply:
        print("Customer confirmed! Extracting order details...")
        order = extract_order_details(sender)
        
        if order:
            order_id = save_order(
                sender,
                order["items"],
                order["total"],
                order["address"]
            )
            reply = f"Your order has been placed successfully!\n\nOrder ID: {order_id}\nItems: {order['items']}\nTotal: {order['total']} AED\nDelivery to: {order['address']}\n\nWe will deliver between 8am-10pm.\nPlease keep your Order ID for follow up.\nThank you for shopping with {SHOP_NAME}!"
        else:
            reply = "I am sorry, I could not process your order. Please type /start and try again."

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