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

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
conversations = {}
waiting_confirmation = {}
saved_orders = {}
known_addresses = {}
products_cache = ""
products_cache_time = None
CACHE_MINUTES = 5

SHEET_ID = "1CtvFUstEy5-vUZ_CmjQOz50Dkc8oWJQ-EkzafudJQ5s"
SHOP_NAME = "Daily Fresh Vegetables & Fruits L.L.C"
SHOP_HOURS = "8:00 AM to 12:00 PM"
DELIVERY_CHARGE = 0
FREE_DELIVERY = True
ESCALATION_NUMBER = "971565893710"

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
    global products_cache, products_cache_time
    if products_cache and products_cache_time:
        elapsed = (datetime.now() - products_cache_time).seconds / 60
        if elapsed < CACHE_MINUTES:
            print(f"Using cached products ({elapsed:.1f} mins old)")
            return products_cache
    try:
        print("Loading fresh products from Google Sheet...")
        sh = get_sheet()
        worksheet = sh.worksheet("Products")
        records = worksheet.get_all_records()
        products = ""
        for row in records:
            stock_status = "In Stock" if int(
                row['Stock']) > 0 else "Out of Stock"
            products += f"- {row['Product']} -- {row['Price_AED']} AED -- {stock_status}\n"
        products_cache = products
        products_cache_time = datetime.now()
        print("Products loaded and cached!")
        return products
    except Exception as e:
        print(f"Sheet error: {e}")
        if products_cache:
            return products_cache
        return "Products temporarily unavailable"

def get_customer(phone):
    try:
        sh = get_sheet()
        worksheet = sh.worksheet("Customers")
        records = worksheet.get_all_records()
        for row in records:
            if str(row['Phone']) == str(phone):
                return row
        return None
    except Exception as e:
        print(f"Customer lookup error: {e}")
        return None

def save_customer(phone, address):
    try:
        sh = get_sheet()
        worksheet = sh.worksheet("Customers")
        records = worksheet.get_all_records()
        for i, row in enumerate(records):
            if str(row['Phone']) == str(phone):
                row_num = i + 2
                worksheet.update(f"C{row_num}", address)
                worksheet.update(f"D{row_num}",
                    datetime.now().strftime("%Y-%m-%d %H:%M"))
                total = int(row.get('Total_Orders', 0)) + 1
                worksheet.update(f"E{row_num}", str(total))
                print(f"Customer updated: {phone}")
                return
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        worksheet.append_row([phone, "", address, now, 1, now])
        print(f"New customer saved: {phone}")
    except Exception as e:
        print(f"Customer save error: {e}")

def save_order(phone, items, total, address):
    try:
        sh = get_sheet()
        worksheet = sh.worksheet("Orders")
        order_id = ''.join(random.choices(
            string.ascii_uppercase + string.digits, k=6))
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        worksheet.append_row([
            order_id, phone, items,
            str(total), address, "New", now
        ])
        print(f"Order saved! ID: {order_id}")
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
Return ONLY in this exact format:
ITEMS: [items and quantities]
TOTAL: [number only]
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
        items = total = address = ""
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
        "compound", "block", "unit", "office", "shop",
        "al ", "bur ", "deira", "dubai", "abu dhabi",
        "sharjah", "ajman", "number", "no.", "room"
    ]
    text_lower = text.lower()
    word_count = len(text.split())
    has_keyword = any(keyword in text_lower for keyword in address_keywords)
    return has_keyword and word_count >= 2

def is_confirmation(text):
    confirm_words = [
        "yes", "confirm", "ok", "okay", "sure",
        "proceed", "place order", "confirmed",
        "yes please", "yep", "yeah", "go ahead",
        "do it", "correct", "right", "accept",
        "1", "same"
    ]
    return text.lower().strip() in confirm_words

def is_rejection(text):
    reject_words = ["no", "cancel", "stop", "dont", "don't", "2", "new"]
    return text.lower().strip() in reject_words

def notify_escalation(sender, reason):
    try:
        url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        data = {
            "messaging_product": "whatsapp",
            "to": ESCALATION_NUMBER,
            "type": "text",
            "text": {"body": f"ESCALATION ALERT!\nCustomer: {sender}\nReason: {reason}\nPlease follow up immediately!"}
        }
        requests.post(url, headers=headers, json=data)
        print(f"Escalation sent to {ESCALATION_NUMBER}")
    except Exception as e:
        print(f"Escalation error: {e}")

def get_system_prompt():
    products = get_products()
    return f"""You are a friendly shop assistant for {SHOP_NAME}.

YOUR JOB:
1. Greet customer warmly
2. Help them choose fresh vegetables and fruits
3. When they are done ask for delivery address
4. When customer gives address show order summary ONLY
5. DO NOT confirm order yourself
6. DO NOT say order is placed
7. DO NOT ask for YES or NO
8. The system handles confirmation automatically

Shop Hours: {SHOP_HOURS}
Delivery: FREE on all orders

Products available:
{products}

Keep replies very very short and friendly.
If customer is angry or has complaint
say: A manager will call you back shortly."""

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
                    saved_orders[sender] = None
                    known_addresses[sender] = None
                    customer = get_customer(sender)
                    if customer and customer.get('Address'):
                        welcome = (
                            f"Welcome back to {SHOP_NAME}!\n"
                            f"Great to see you again!\n"
                            f"How can I help you today?"
                        )
                    else:
                        welcome = (
                            f"Welcome to {SHOP_NAME}!\n"
                            f"We deliver the freshest vegetables "
                            f"and fruits to your door!\n"
                            f"How can I help you today?"
                        )
                    send_whatsapp_message(sender, welcome)
                    return "OK", 200

                # Handle address choice 1 or 2
                if waiting_confirmation.get(sender) and text.strip() in ["1", "2"]:
                    customer = get_customer(sender)
                    if customer and customer.get('Address'):
                        if text.strip() == "1":
                            address = customer['Address']
                        else:
                            address = known_addresses.get(sender, "")

                        conversations[sender].append({
                            "role": "user",
                            "content": f"My delivery address is: {address}"
                        })
                        order = extract_order_from_conversation(sender)
                        if order:
                            order['address'] = address
                            saved_orders[sender] = order

                        reply = (
                            f"Delivery address confirmed!\n\n"
                            f"Address: {address}\n\n"
                            f"Reply YES to confirm your order\n"
                            f"Reply NO to cancel"
                        )
                        send_whatsapp_message(sender, reply)
                        return "OK", 200

                # Waiting for YES or NO
                if waiting_confirmation.get(sender):
                    print(f"In confirmation mode for {sender}")
                    if is_confirmation(text):
                        print(f"YES from {sender}! Saving order...")
                        order = saved_orders.get(sender)
                        if not order:
                            order = extract_order_from_conversation(sender)
                        if order:
                            order_id = save_order(
                                sender,
                                order["items"],
                                order["total"],
                                order["address"]
                            )
                            if order_id:
                                save_customer(sender, order["address"])
                                waiting_confirmation[sender] = False
                                conversations[sender] = []
                                saved_orders[sender] = None
                                reply = (
                                    f"Your order has been placed!\n\n"
                                    f"Order ID: {order_id}\n"
                                    f"Items: {order['items']}\n"
                                    f"Total: FREE Delivery\n"
                                    f"Delivery to: {order['address']}\n\n"
                                    f"We will deliver between {SHOP_HOURS}.\n"
                                    f"Save your Order ID: {order_id}\n\n"
                                    f"Thank you for choosing {SHOP_NAME}!"
                                )
                            else:
                                reply = "Sorry, problem saving order. Please type /start and try again."
                        else:
                            reply = "Sorry, could not get order details. Please type /start and try again."
                        send_whatsapp_message(sender, reply)
                        return "OK", 200

                    elif is_rejection(text):
                        waiting_confirmation[sender] = False
                        saved_orders[sender] = None
                        send_whatsapp_message(
                            sender,
                            "Order cancelled. Type /start to start a new order.")
                        return "OK", 200
                    else:
                        send_whatsapp_message(
                            sender,
                            "Please reply YES to confirm or NO to cancel.")
                        return "OK", 200

                # Check for address
                address_detected = is_address(text)
                if address_detected:
                    print(f"Address found from {sender}!")
                    customer = get_customer(sender)
                    if customer and customer.get('Address'):
                        saved_address = customer['Address']
                        known_addresses[sender] = text
                        waiting_confirmation[sender] = True
                        reply = (
                            f"I found your previous delivery address:\n\n"
                            f"Address: {saved_address}\n\n"
                            f"Reply 1 for SAME ADDRESS\n"
                            f"Reply 2 for NEW ADDRESS: {text}"
                        )
                        send_whatsapp_message(sender, reply)
                        return "OK", 200

                    waiting_confirmation[sender] = True
                    ai_reply = get_ai_reply(sender, text)
                    order = extract_order_from_conversation(sender)
                    if order:
                        saved_orders[sender] = order
                        print(f"Order pre-saved: {order}")

                    final_reply = (
                        ai_reply +
                        "\n\n----------------------------------------"
                        "\nReply YES to confirm your order"
                        "\nReply NO to cancel"
                    )
                    send_whatsapp_message(sender, final_reply)
                    return "OK", 200

                # Check for complaint or escalation
                complaint_words = ["complaint", "problem", "wrong",
                                  "bad", "terrible", "manager",
                                  "refund", "angry", "worst"]
                if any(word in text.lower() for word in complaint_words):
                    notify_escalation(sender, text)

                # Normal conversation
                reply = get_ai_reply(sender, text)
                send_whatsapp_message(sender, reply)

    except Exception as e:
        print(f"Error: {e}")
    return "OK", 200

if __name__ == "__main__":
    print("=" * 45)
    print(f"  {SHOP_NAME}")
    print("  AI Agent is LIVE!")
    print("=" * 45)
    app.run(port=5000, debug=True)