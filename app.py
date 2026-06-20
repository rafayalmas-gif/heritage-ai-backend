import os
import json
import base64
import requests
from datetime import datetime, timezone
from flask import Flask, request, jsonify

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

app = Flask(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "heritage_verify_123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
STAFF_NUMBERS = [x.strip() for x in os.getenv("STAFF_NUMBERS", "").split(",") if x.strip()]
LOG_FILE = os.getenv("LOG_FILE", "logs.jsonl")

HERITAGE_SYSTEM_PROMPT = """You are Heritage Jewelry Design Director, expert in Pakistani, South Asian, Mughal-inspired, bridal, kundan, meenakari, silver, gold, moissanite, lab diamond, and colored-stone jewelry. Create designs suitable for Heritage Jewellers. Never create generic Western minimalist jewelry. Prioritize emerald, ruby, sapphire, pearl, moissanite, lab diamond, kundan-inspired layouts, arches, jharokhas, jaali, paisley, lotus, floral vines, regal drops, and handcrafted heritage details. Every design must be commercially viable, manufacturable, premium, Instagram-worthy, and suitable for Heritage customers. When an image is uploaded, analyze design, stone placement, balance, wearability, manufacturability, and commercial appeal. When a dress is uploaded, recommend matching jewelry, stone colors, metal color, earrings, necklace, bangle/bracelet, ring, makeup, hairstyle, clutch, and styling direction. When stone change is requested, suggest at least three realistic stone variations with visual impact, outfit compatibility, luxury appeal, Heritage appeal, and commercial potential. When model visualization is requested, use Pakistani, Indian, British Asian, or Middle Eastern model styling. Jewelry must remain the hero. Score every design on Heritage DNA, luxury appeal, commercial potential, manufacturability, Instagram appeal, and bestseller potential. If any score is below 8/10, improve before final answer. Add: Manager approval required before customer sharing."""

COMMAND_HELP = """/stone = change stone color
/model = show jewelry on Pakistani/South Asian model
/dress = match dress with jewelry
/collection = create full collection
/bridal = bridal version
/caption = product/social caption
/product = website product description
/cad = CAD/manufacturing brief"""

def log_event(data):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    except Exception as exc:
        print("LOG_ERROR", str(exc), flush=True)

def send_whatsapp_text(to, body):
    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": body[:4096]},
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print("WA_SEND", r.status_code, r.text[:500], flush=True)
    return r

def get_media_url(media_id):
    url = f"https://graph.facebook.com/v20.0/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json().get("url")

def download_media(media_url):
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    r = requests.get(media_url, headers=headers, timeout=60)
    r.raise_for_status()
    return r.content, r.headers.get("Content-Type", "image/jpeg")

def command_instructions(text):
    lower = (text or "").lower().strip()
    if lower.startswith("/stone"):
        return "Staff requested stone change. Suggest at least three realistic stone variations with commercial analysis."
    if lower.startswith("/model"):
        return "Staff requested model visualization. Analyze product and create a detailed image-generation prompt for a Pakistani/South Asian model wearing the jewelry. Jewelry must remain the hero."
    if lower.startswith("/dress"):
        return "Staff requested dress matching. Recommend matching jewelry, stones, metal tone, earrings, necklace, bangles/bracelet, ring, makeup, hairstyle, clutch, and styling direction."
    if lower.startswith("/collection"):
        return "Staff requested full collection. Create necklace/earrings/ring/bangle/bracelet variations from the uploaded design."
    if lower.startswith("/bridal"):
        return "Staff requested bridal conversion. Convert the design into a premium Heritage bridal set."
    if lower.startswith("/caption"):
        return "Staff requested Instagram/social caption. Write premium captions with hashtags suitable for Heritage Jewellers."
    if lower.startswith("/product"):
        return "Staff requested website product description. Write title, short description, detailed description, material notes, styling, and SEO keywords."
    if lower.startswith("/cad"):
        return "Staff requested CAD/manufacturing brief. Provide manufacturable CAD notes, stone sizes/placement suggestions, finishing, setting type, and production cautions."
    return "Staff did not use a known command. Helpfully answer and include available commands."

def call_openai(text, image_bytes=None, image_mime="image/jpeg"):
    if not OPENAI_API_KEY:
        return "OpenAI API key is not configured yet. Please add OPENAI_API_KEY in Render environment variables."
    client = OpenAI(api_key=OPENAI_API_KEY)
    user_content = [
        {
            "type": "input_text",
            "text": f"Staff message: {text or ''}\n\nTask: {command_instructions(text)}\n\nAvailable commands:\n{COMMAND_HELP}"
        }
    ]
    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        user_content.append({
            "type": "input_image",
            "image_url": f"data:{image_mime};base64,{b64}"
        })
    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        instructions=HERITAGE_SYSTEM_PROMPT,
        input=[{"role": "user", "content": user_content}],
    )
    return response.output_text

@app.route("/", methods=["GET"])
def home():
    return "Heritage WhatsApp AI Designer backend is running.", 200

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge or "", 200
    return "Verification failed", 403

@app.route("/webhook", methods=["POST"])
def receive_webhook():
    payload = request.get_json(silent=True) or {}
    log_event({"time": datetime.now(timezone.utc).isoformat(), "type": "incoming", "payload": payload})
    try:
        entry = payload.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return jsonify({"status": "ignored"}), 200
        msg = messages[0]
        sender = msg.get("from")
        if STAFF_NUMBERS and sender not in STAFF_NUMBERS:
            send_whatsapp_text(sender, "Access denied. This Heritage AI Designer number is staff-only.")
            return jsonify({"status": "blocked"}), 200
        text = ""
        image_bytes = None
        image_mime = "image/jpeg"
        if msg.get("type") == "text":
            text = msg.get("text", {}).get("body", "")
        elif msg.get("type") == "image":
            text = msg.get("image", {}).get("caption", "")
            media_id = msg.get("image", {}).get("id")
            if media_id:
                media_url = get_media_url(media_id)
                image_bytes, image_mime = download_media(media_url)
        else:
            send_whatsapp_text(sender, "Please send a text command or image with caption. Example: /stone change emerald to ruby")
            return jsonify({"status": "unsupported"}), 200
        if not text:
            text = "Analyze this image for Heritage Jewellers and suggest improvements."
        reply = call_openai(text, image_bytes, image_mime)
        reply += "\n\nManager approval required before customer sharing."
        send_whatsapp_text(sender, reply)
        log_event({"time": datetime.now(timezone.utc).isoformat(), "type": "reply", "to": sender, "reply": reply})
        return jsonify({"status": "ok"}), 200
    except Exception as exc:
        print("WEBHOOK_ERROR", str(exc), flush=True)
        try:
            sender = payload["entry"][0]["changes"][0]["value"]["messages"][0]["from"]
            send_whatsapp_text(sender, "Sorry, Heritage AI had an error processing this request. Please try again.")
        except Exception:
            pass
        return jsonify({"status": "error", "message": str(exc)}), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
