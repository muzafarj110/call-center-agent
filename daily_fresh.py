from flask import Flask, request
from flask_cors import CORS
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
CORS(app)


WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
conversations = {}
waiting_confirmation = {}
saved_orders = {}
known_addresses = {}
address_prompted = {}
products_cache = ""
products_cache_time = None
CACHE_MINUTES = 5

SHEET_ID = "1CtvFUstEy5-vUZ_CmjQOz50Dkc8oWJQ-EkzafudJQ5s"
SHOP_NAME = "Daily Fresh Vegetables & Fruits L.L.C"
SHOP_HOURS = "8:00 AM to 12:00 PM"
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
            try:
                stock = int(row['Stock']) if str(
                    row['Stock']).strip() != '' else 0
                stock_status = "In Stock" if stock > 0 else "Out of Stock"
            except (ValueError, KeyError):
                stock_status = "In Stock"
            products += f"- {row['Product']} -- {row['Price_AED']} AED per unit -- {stock_status}\n"
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
                try:
                    total = int(row.get('Total_Orders', 0)) + 1
                except ValueError:
                    total = 1
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
Return ONLY in this exact format with no extra text:
ITEMS: [items and quantities]
TOTAL: [number only no currency symbol, if free write 0]
ADDRESS: [delivery address]

Rules:
- TOTAL must be a number only like 15 or 10.5
- If total is free or zero write 0
- If truly nothing found return: INCOMPLETE

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

        if not total:
            total = "0"

        if items and address:
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
        "sharjah", "ajman", "number", "no.", "room",
        "فيلا", "شقة", "بناية", "شارع", "قريب", "خلف",
        "منطقة", "مدينة", "برج", "وحدة", "دبي", "الشارقة",
        "عجمان", "ابوظبي"
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
        "do it", "correct", "right", "accept", "1", "same",
        "نعم", "اكد", "تاكيد", "موافق", "صح", "ايوا", "اي",
        "تمام", "حسنا", "اوكي", "اوك"
    ]
    return text.lower().strip() in confirm_words

def is_rejection(text):
    reject_words = [
        "no", "cancel", "stop", "dont", "don't", "2", "new",
        "لا", "الغ", "الغاء", "توقف", "لأ"
    ]
    return text.lower().strip() in reject_words

def is_asking_for_address(reply):
    phrases = [
        "delivery address", "عنوان التوصيل",
        "share your address", "عنوانك",
        "your address", "عنوان التوصيل",
        "where to deliver", "اين نوصل",
        "please share", "من فضلك",
        "address so", "عنوان لتوصيل",
        "ممكن تعطيني عنوان",
        "عنوان توصيل"
    ]
    reply_lower = reply.lower()
    return any(phrase in reply_lower for phrase in phrases)

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
            "text": {"body": (
                f"ESCALATION ALERT!\n"
                f"Customer: {sender}\n"
                f"Reason: {reason}\n"
                f"Please follow up immediately!"
            )}
        }
        requests.post(url, headers=headers, json=data)
        print(f"Escalation sent to {ESCALATION_NUMBER}")
    except Exception as e:
        print(f"Escalation error: {e}")

def get_system_prompt():
    products = get_products()
    return f"""You are a friendly shop assistant for {SHOP_NAME}.

LANGUAGE RULES - VERY IMPORTANT:
- If customer writes in Arabic reply ONLY in Arabic
- If customer writes in English reply ONLY in English
- If customer mixes both languages reply in Arabic
- Always match the customer language automatically
- Never ask customer which language they prefer

YOUR JOB:
1. Greet customer warmly in their language
2. Help them choose fresh vegetables and fruits
3. When they are done collecting items ask for delivery address
4. When customer gives address show complete order summary
5. DO NOT confirm order yourself
6. DO NOT say order is placed
7. DO NOT ask for YES or NO - system handles this
8. If anything is missing ask ONLY for that missing thing
9. NEVER ask customer to start over or type /start

Shop Hours: {SHOP_HOURS}
Delivery: FREE on all orders

Products available:
{products}

PRICING RULES:
- 500g of 1kg product = half price
- 2kg of 1kg product = double price
- 250g of 1kg product = quarter price
- Always calculate and show price for each item
- Always show TOTAL
- Delivery is always FREE

ORDER SUMMARY FORMAT in English:
Items:
- Tomatoes 500g = 2.5 AED
- Apples 1kg = 8 AED
Total: 10.5 AED
Delivery: FREE

ORDER SUMMARY FORMAT in Arabic:
المنتجات:
- طماطم 500 جرام = 2.5 درهم
- تفاح 1 كيلو = 8 درهم
المجموع: 10.5 درهم
التوصيل: مجاني

IMPORTANT RULES:
- If item Out of Stock suggest alternative
- Keep replies short and friendly
- If customer angry:
  English: A manager will call you back shortly
  Arabic: سيتصل بك المدير قريباً
- Always show total before asking for address
- Never ask customer to start over"""

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

@app.route("/update-order", methods=["POST"])
def update_order():
    try:
        data = request.get_json()
        order_id = data.get("order_id")
        new_status = data.get("status")
        sheet_id = data.get("sheet_id")

        if not order_id or not new_status or not sheet_id:
            return {"error": "Missing data"}, 400

        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_file(
            "credentials.json", scopes=scope)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(sheet_id)
        worksheet = sh.worksheet("Orders")
        records = worksheet.get_all_records()

        for i, row in enumerate(records):
            if str(row.get("Order_ID", "")) == str(order_id):
                row_num = i + 2
                worksheet.update(f"F{row_num}", [[new_status]])
                print(f"Order {order_id} updated to {new_status}")
                return {"success": True, "order_id": order_id,
                        "status": new_status}, 200

        return {"error": "Order not found"}, 404

    except Exception as e:
        print(f"Update order error: {e}")
        return {"error": str(e)}, 500
        
@app.route("/escalate", methods=["POST"])
def escalate():
    data = request.get_json()
    to = data.get("to")
    message = data.get("message")
    if to and message:
        send_whatsapp_message(to, message)
        print(f"Escalation sent to {to}")
    return "OK", 200
    
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
                if text.lower() in ["/start", "/ابدأ"]:
                    conversations[sender] = []
                    waiting_confirmation[sender] = False
                    saved_orders[sender] = None
                    known_addresses[sender] = None
                    address_prompted[sender] = False
                    customer = get_customer(sender)
                    if customer and customer.get('Address'):
                        welcome = (
                            f"Welcome back to {SHOP_NAME}!\n"
                            f"Great to see you again!\n"
                            f"How can I help you today?\n\n"
                            f"اهلاً بعودتك!\n"
                            f"كيف أقدر أساعدك اليوم؟"
                        )
                    else:
                        welcome = (
                            f"Welcome to {SHOP_NAME}!\n"
                            f"We deliver the freshest vegetables "
                            f"and fruits to your door!\n"
                            f"Delivery is always FREE!\n\n"
                            f"اهلاً وسهلاً في {SHOP_NAME}!\n"
                            f"نوصل أطازج الخضروات والفواكه لباب بيتك!\n"
                            f"التوصيل مجاني دائماً!"
                        )
                    send_whatsapp_message(sender, welcome)
                    return "OK", 200

                # Handle address choice 1 or 2
                if waiting_confirmation.get(sender) and text.strip() in ["1", "2"]:
                    customer = get_customer(sender)
                    if customer and customer.get('Address'):
                        if text.strip() == "1":
                            address = customer['Address']
                            print(f"Using saved address: {address}")
                        else:
                            address = known_addresses.get(sender, "")
                            if not address:
                                # Ask for new address
                                waiting_confirmation[sender] = False
                                reply = (
                                    "Please share your new delivery address.\n\n"
                                    "من فضلك شارك عنوانك الجديد للتوصيل."
                                )
                                send_whatsapp_message(sender, reply)
                                return "OK", 200

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
                            f"Reply NO to cancel\n\n"
                            f"---\n"
                            f"تم تأكيد العنوان!\n\n"
                            f"العنوان: {address}\n\n"
                            f"اكتب نعم لتأكيد الطلب\n"
                            f"اكتب لا للإلغاء"
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

                        if order and order.get('items') and order.get('address'):
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
                                address_prompted[sender] = False
                                total_display = "FREE" if order[
                                    'total'] == "0" else f"{order['total']} AED"
                                reply = (
                                    f"Your order has been placed!\n\n"
                                    f"Order ID: {order_id}\n"
                                    f"Items: {order['items']}\n"
                                    f"Total: {total_display}\n"
                                    f"Delivery: FREE\n"
                                    f"Delivery to: {order['address']}\n\n"
                                    f"We will deliver between {SHOP_HOURS}.\n"
                                    f"Save your Order ID: {order_id}\n\n"
                                    f"---\n"
                                    f"تم تأكيد طلبك!\n\n"
                                    f"رقم الطلب: {order_id}\n"
                                    f"المنتجات: {order['items']}\n"
                                    f"التوصيل: مجاني\n"
                                    f"العنوان: {order['address']}\n\n"
                                    f"سيتم التوصيل خلال {SHOP_HOURS}\n"
                                    f"احتفظ برقم طلبك: {order_id}\n\n"
                                    f"شكراً لاختيارك {SHOP_NAME}!"
                                )
                            else:
                                reply = (
                                    f"Sorry, problem saving order.\n"
                                    f"Our team will contact you shortly.\n\n"
                                    f"عذراً، حدث خطأ.\n"
                                    f"سيتواصل معك فريقنا قريباً."
                                )
                        elif order and order.get('items') and not order.get('address'):
                            # Missing address - ask for it
                            waiting_confirmation[sender] = False
                            reply = (
                                "Please share your delivery address to complete the order.\n\n"
                                "من فضلك شارك عنوانك لإكمال الطلب."
                            )
                        else:
                            # Missing items - ask for them
                            waiting_confirmation[sender] = False
                            reply = get_ai_reply(sender,
                                "System: Customer said yes but order details unclear. Ask what they want to order.")

                        send_whatsapp_message(sender, reply)
                        return "OK", 200

                    elif is_rejection(text):
                        waiting_confirmation[sender] = False
                        saved_orders[sender] = None
                        address_prompted[sender] = False
                        send_whatsapp_message(
                            sender,
                            "Order cancelled.\n"
                            "How can I help you?\n\n"
                            "تم إلغاء الطلب.\n"
                            "كيف أقدر أساعدك؟")
                        return "OK", 200

                    else:
                        send_whatsapp_message(
                            sender,
                            "Please reply YES to confirm or NO to cancel.\n\n"
                            "الرجاء الرد بنعم للتأكيد أو لا للإلغاء.")
                        return "OK", 200

                # Check for address typed by customer
                address_detected = is_address(text)
                if address_detected and not waiting_confirmation.get(sender):
                    print(f"Address found from {sender}!")
                    customer = get_customer(sender)
                    if customer and customer.get('Address'):
                        saved_address = customer['Address']
                        known_addresses[sender] = text
                        waiting_confirmation[sender] = True
                        reply = (
                            f"I found your saved address:\n\n"
                            f"Address: {saved_address}\n\n"
                            f"Reply 1 for SAME ADDRESS\n"
                            f"Reply 2 for NEW ADDRESS: {text}\n\n"
                            f"---\n"
                            f"وجدت عنوانك المحفوظ:\n\n"
                            f"العنوان: {saved_address}\n\n"
                            f"اكتب 1 لنفس العنوان\n"
                            f"اكتب 2 للعنوان الجديد: {text}"
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
                        "\nReply YES to confirm / نعم للتأكيد"
                        "\nReply NO to cancel / لا للإلغاء"
                    )
                    send_whatsapp_message(sender, final_reply)
                    return "OK", 200

                # Normal conversation
                reply = get_ai_reply(sender, text)

                # Check if agent is asking for address
                # and customer has a saved address
                if is_asking_for_address(reply) and not address_prompted.get(sender):
                    customer = get_customer(sender)
                    if customer and customer.get('Address'):
                        saved_address = customer['Address']
                        address_prompted[sender] = True
                        waiting_confirmation[sender] = True
                        known_addresses[sender] = ""
                        reply = (
                            f"{reply}\n\n"
                            f"----------------------------------------\n"
                            f"I found your saved address:\n"
                            f"Address: {saved_address}\n\n"
                            f"Reply 1 for SAME ADDRESS\n"
                            f"Reply 2 to enter NEW ADDRESS\n\n"
                            f"---\n"
                            f"وجدت عنوانك المحفوظ:\n"
                            f"العنوان: {saved_address}\n\n"
                            f"اكتب 1 لنفس العنوان\n"
                            f"اكتب 2 لإدخال عنوان جديد"
                        )

                # Check for complaint
                complaint_words = [
                    "complaint", "problem", "wrong", "bad",
                    "terrible", "manager", "refund", "angry", "worst",
                    "شكوى", "مشكلة", "غلط", "سيء", "مدير", "استرداد"
                ]
                if any(word in text.lower() for word in complaint_words):
                    notify_escalation(sender, text)

                send_whatsapp_message(sender, reply)

    except Exception as e:
        print(f"Error: {e}")
    return "OK", 200

if __name__ == "__main__":
    print("=" * 45)
    print(f"  {SHOP_NAME}")
    print("  AI Agent is LIVE!")
    print("  Arabic + English Support")
    print("=" * 45)
    app.run(port=5000, debug=True)