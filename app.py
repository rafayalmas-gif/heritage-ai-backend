import os
import json
import base64
import requests
from io import BytesIO
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from openai import OpenAI

import cloudinary
import cloudinary.uploader

app = Flask(__name__)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "heritage_verify_123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
STAFF_NUMBERS = [x.strip() for x in os.getenv("STAFF_NUMBERS", "").split(",") if x.strip()]
LOG_FILE = os.getenv("LOG_FILE", "logs.jsonl")

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True,
)

HERITAGE_SYSTEM_PROMPT = """
You are Heritage Jewelry Design Director, expert in Pakistani, South Asian, Mughal-inspired, bridal, kundan, meenakari, silver, gold, moissanite, lab diamond, and colored-stone jewelry.

Always study uploaded reference images before responding.

Never create generic Western minimalist jewelry.

Prioritize emerald, ruby, sapphire, pearl, moissanite, lab diamond, kundan-inspired layouts, arches, jharokhas, jaali, paisley, lotus, floral vines, regal drops, and handcrafted heritage details.

Every design must be commercially viable, manufacturable, premium, Instagram-worthy, and suitable for Heritage Jewellers customers.

When an image is uploaded, analyze design, stone placement, balance, wearability, manufacturability, and commercial appeal.

When model visualization is requested, preserve the uploaded jewelry design as much as possible. Jewelry must remain the hero.

Manager approval required before customer sharing.
"""

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
    print("WA_TEXT_SEND", r.status_code, r.text[:500], flush=True)
    return r


def send_whatsapp_image(to, image_url, caption=""):
    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {
            "link": image_url,
            "caption": caption[:1024],
        },
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print("WA_IMAGE_SEND", r.status_code, r.text[:500], flush=True)
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

    if lower.startswith("/model"):
        return "Analyze uploaded jewelry and create model visualization guidance."
    if lower.startswith("/stone"):
        return "Analyze uploaded jewelry and create stone color change concept."
    if lower.startswith("/caption"):
        return "Write premium Instagram caption for Heritage Jewellers."
    if lower.startswith("/product"):
        return "Write website product description."
    if lower.startswith("/dress"):
        return "Match jewelry with dress styling."
    if lower.startswith("/collection"):
        return "Create full collection from design."
    if lower.startswith("/bridal"):
        return "Convert design into bridal set."
    if lower.startswith("/cad"):
        return "Create CAD/manufacturing brief."

    return "Answer helpfully and include available commands."


def call_openai(text, image_bytes=None, image_mime="image/jpeg"):
    if not OPENAI_API_KEY:
        return "OpenAI API key is not configured yet."

    client = OpenAI(api_key=OPENAI_API_KEY)

    user_content = [
        {
            "type": "input_text",
            "text": f"Staff message: {text or ''}\n\nTask: {command_instructions(text)}\n\nCommands:\n{COMMAND_HELP}",
        }
    ]

    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        user_content.append({
            "type": "input_image",
            "image_url": f"data:{image_mime};base64,{b64}",
        })

    response = client.responses.create(
        model=OPENAI_MODEL,
        instructions=HERITAGE_SYSTEM_PROMPT,
        input=[{"role": "user", "content": user_content}],
    )

    return response.output_text


def upload_generated_image_to_cloudinary(image_bytes):
    upload_result = cloudinary.uploader.upload(
        BytesIO(image_bytes),
        resource_type="image",
        folder="heritage-ai-designer",
    )
    return upload_result["secure_url"]


def edit_image_and_upload(image_bytes, prompt):
    client = OpenAI(api_key=OPENAI_API_KEY)

    image_file = BytesIO(image_bytes)
    image_file.name = "heritage_reference.png"

    result = client.images.edit(
        model="gpt-image-1",
        image=image_file,
        prompt=prompt,
        size="1024x1024",
        quality="medium",
        n=1,
    )

    image_base64 = result.data[0].b64_json
    output_bytes = base64.b64decode(image_base64)

    return upload_generated_image_to_cloudinary(output_bytes)


def generate_image_and_upload(prompt):
    client = OpenAI(api_key=OPENAI_API_KEY)

    result = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1024x1024",
        quality="medium",
        n=1,
    )

    image_base64 = result.data[0].b64_json
    output_bytes = base64.b64decode(image_base64)

    return upload_generated_image_to_cloudinary(output_bytes)


def build_model_image_prompt(analysis, staff_text):
    return f"""
Use the uploaded jewelry image as the primary visual reference.

Staff request:
{staff_text}

Jewelry analysis:
{analysis}

Create a realistic luxury campaign visualization for Heritage Jewellers.

Critical requirements:
- Preserve the uploaded jewelry design as closely as possible
- Do not invent a different jewelry item
- Keep the same shape, stone layout, proportions, metal color, and design language
- Place the jewelry naturally on a Pakistani or South Asian model
- Jewelry must remain the hero
- Premium bridal or party-wear styling
- Mughal-inspired Heritage Jewellers luxury mood
- Soft high-end campaign lighting
- No text
- No logo
- No Western minimalist styling
"""


def build_stone_image_prompt(analysis, staff_text):
    return f"""
Use the uploaded jewelry image as the primary visual reference.

Staff request:
{staff_text}

Jewelry analysis:
{analysis}

Create a realistic product visualization for Heritage Jewellers.

Critical requirements:
- Preserve the exact jewelry design as closely as possible
- Do not redesign the jewelry
- Do not invent a different product
- Keep the same shape, stone placement, proportions, metal structure, and angle
- Only change the requested stone color
- Keep metal color polished and realistic
- Premium white background product image
- No text
- No logo
"""


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
        
        # Ignore WhatsApp delivery/status updates
        if "statuses" in value:
        return jsonify({"status": "status_update"}), 200
        
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
            send_whatsapp_text(sender, "Please send a text command or image with caption. Example: /model")
            return jsonify({"status": "unsupported"}), 200

        if not text:
            text = "Analyze this image for Heritage Jewellers."

        lower = text.lower().strip()

        analysis = call_openai(text, image_bytes, image_mime)

        if lower.startswith("/model") and image_bytes:
            send_whatsapp_text(sender, "Generating model visualization using your uploaded jewelry as reference. Please wait...")

            image_prompt = build_model_image_prompt(analysis, text)
            image_url = edit_image_and_upload(image_bytes, image_prompt)

            send_whatsapp_image(
                sender,
                image_url,
                "Heritage AI model visualization. Manager approval required before customer sharing.",
            )

            return jsonify({"status": "model_image_sent"}), 200

        if lower.startswith("/stone") and image_bytes:
            send_whatsapp_text(sender, "Generating stone-change concept using your uploaded jewelry as reference. Please wait...")

            image_prompt = build_stone_image_prompt(analysis, text)
            image_url = edit_image_and_upload(image_bytes, image_prompt)

            send_whatsapp_image(
                sender,
                image_url,
                "Heritage AI stone-change concept. Manager approval required before customer sharing.",
            )

            return jsonify({"status": "stone_image_sent"}), 200

        reply = analysis + "\n\nManager approval required before customer sharing."
        send_whatsapp_text(sender, reply)

        return jsonify({"status": "ok"}), 200

    except Exception as exc:
        print("WEBHOOK_ERROR", str(exc), flush=True)

        try:
            sender = payload["entry"][0]["changes"][0]["value"]["messages"][0]["from"]
            send_whatsapp_text(sender, f"Sorry, Heritage AI had an error: {str(exc)[:500]}")
        except Exception:
            pass

        return jsonify({"status": "error", "message": str(exc)}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
