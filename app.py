import os
import json
import base64
import requests
import threading
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
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
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

PROCESSED_MESSAGE_IDS = set()
PROCESSING_MESSAGE_IDS = set()

HERITAGE_SYSTEM_PROMPT = """
You are Heritage Jewelry Design Director for Heritage Jewellers.

You are expert in Pakistani, South Asian, Mughal-inspired, bridal, kundan, meenakari, silver, gold, moissanite, lab diamond, and coloured-stone jewelry.

Always study uploaded reference images before responding.

Never create generic Western minimalist jewelry.

Prioritize emerald, ruby, sapphire, pearl, moissanite, lab diamond, kundan-inspired layouts, arches, jharokhas, jaali, paisley, lotus, floral vines, regal drops, and handcrafted heritage details.

When an image is uploaded, analyze:
- jewelry category
- metal color
- stone color
- stone shape
- stone layout
- setting style
- proportions
- commercial appeal
- manufacturability

For model visualization, the uploaded jewelry is the exact product reference.
Do not change stone color, metal color, stone placement, shape, setting, or proportions unless the command specifically asks for stone change.

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


def mime_to_filename(image_mime):
    if "png" in image_mime:
        return "heritage_reference.png"
    if "webp" in image_mime:
        return "heritage_reference.webp"
    return "heritage_reference.jpg"


def upload_image_to_cloudinary(image_bytes, folder="heritage-ai-designer"):
    upload_result = cloudinary.uploader.upload(
        BytesIO(image_bytes),
        resource_type="image",
        folder=folder,
    )
    return upload_result["secure_url"]


def command_instructions(text):
    lower = (text or "").lower().strip()

    if lower.startswith("/model"):
        return "Create strict product-preservation analysis for model visualization."
    if lower.startswith("/stone"):
        return "Create strict analysis for stone color change only."
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


def create_locked_product_spec(text, image_bytes, image_mime):
    client = OpenAI(api_key=OPENAI_API_KEY)

    b64 = base64.b64encode(image_bytes).decode("utf-8")

    response = client.responses.create(
        model=OPENAI_MODEL,
        instructions="""
You are a jewelry product preservation inspector.

Study the uploaded jewelry image very carefully.

Return a strict product lock sheet.

Do not be creative.

Describe only what is visible.

Focus on exact preservation:
- product type
- metal color
- stone colors
- stone count/pattern if visible
- stone layout
- shape
- silhouette
- setting style
- symmetry
- proportions
- what must NOT change

The output will be used by an image editing model to preserve the exact product.
""",
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": f"Staff request: {text}\n\nCreate exact jewelry preservation specification."
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:{image_mime};base64,{b64}"
                    }
                ],
            }
        ],
    )

    return response.output_text


def edit_image_and_upload(image_bytes, image_mime, prompt):
    client = OpenAI(api_key=OPENAI_API_KEY)

    image_file = BytesIO(image_bytes)
    image_file.name = mime_to_filename(image_mime)

    result = client.images.edit(
        model=OPENAI_IMAGE_MODEL,
        image=image_file,
        prompt=prompt,
        size="1024x1024",
        quality="high",
        n=1,
    )

    image_base64 = result.data[0].b64_json
    output_bytes = base64.b64decode(image_base64)

    return upload_image_to_cloudinary(output_bytes)


def build_model_prompt(product_spec, staff_text):
    return f"""
STRICT PRODUCT-PRESERVATION MODEL VISUALIZATION.

The uploaded jewelry image is the exact product reference.

Staff request:
{staff_text}

Exact product lock sheet:
{product_spec}

Create a photorealistic Pakistani / South Asian female model wearing the uploaded jewelry.

MANDATORY PRODUCT PRESERVATION RULES:
- The jewelry must match the uploaded product as closely as possible.
- Do not change stone color.
- Do not change metal color.
- Do not change stone arrangement.
- Do not change stone shapes.
- Do not change the product silhouette.
- Do not change the setting style.
- Do not invent a new ring, necklace, pendant, or earring.
- If the uploaded product is earrings, show earrings.
- If the uploaded product is a ring, show a ring.
- If the uploaded product is a pendant, show a pendant.
- Keep the jewelry visually identical to the reference image.
- The model, clothing, lighting, and background may change.
- The jewelry itself must not be redesigned.

MODEL STYLE:
- Pakistani / South Asian model.
- Elegant luxury styling.
- Bridal or party-wear look.
- Heritage Jewellers premium campaign mood.
- Warm luxury studio lighting.
- Natural skin texture.
- Jewelry is the hero.
- No text.
- No logo.
"""


def build_stone_prompt(product_spec, staff_text):
    return f"""
STRICT STONE-COLOR EDIT.

The uploaded jewelry image is the exact product reference.

Staff request:
{staff_text}

Exact product lock sheet:
{product_spec}

Create a photorealistic product image.

MANDATORY RULES:
- Preserve the exact jewelry shape.
- Preserve the exact metal color.
- Preserve the exact setting style.
- Preserve the exact angle and product type.
- Preserve the exact stone layout.
- Only change the requested stone color.
- Do not change product design.
- Do not create a different product.
- White clean product background.
- No text.
- No logo.
"""


def background_image_job(sender, text, image_bytes, image_mime, message_id):
    try:
        print("BACKGROUND_JOB_START", message_id, sender, text[:100], flush=True)

        product_spec = create_locked_product_spec(text, image_bytes, image_mime)
        lower = text.lower().strip()

        if lower.startswith("/model"):
            prompt = build_model_prompt(product_spec, text)
            image_url = edit_image_and_upload(image_bytes, image_mime, prompt)

            send_whatsapp_image(
                sender,
                image_url,
                "Heritage AI model visualization. Manager approval required before customer sharing.",
            )

        elif lower.startswith("/stone"):
            prompt = build_stone_prompt(product_spec, text)
            image_url = edit_image_and_upload(image_bytes, image_mime, prompt)

            send_whatsapp_image(
                sender,
                image_url,
                "Heritage AI stone-change concept. Manager approval required before customer sharing.",
            )

        else:
            reply = call_openai(text, image_bytes, image_mime)
            reply += "\n\nManager approval required before customer sharing."
            send_whatsapp_text(sender, reply)

        PROCESSED_MESSAGE_IDS.add(message_id)
        print("BACKGROUND_JOB_DONE", message_id, flush=True)

    except Exception as exc:
        print("BACKGROUND_JOB_ERROR", str(exc), flush=True)
        send_whatsapp_text(
            sender,
            f"Sorry, Heritage AI had an image-generation error: {str(exc)[:500]}"
        )
    finally:
        PROCESSING_MESSAGE_IDS.discard(message_id)


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

        if "statuses" in value:
            return jsonify({"status": "status_update"}), 200

        messages = value.get("messages", [])

        if not messages:
            return jsonify({"status": "ignored"}), 200

        msg = messages[0]
        message_id = msg.get("id", "")

        if message_id and (message_id in PROCESSED_MESSAGE_IDS or message_id in PROCESSING_MESSAGE_IDS):
            return jsonify({"status": "duplicate_ignored"}), 200

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

        if (lower.startswith("/model") or lower.startswith("/stone")) and image_bytes:
            PROCESSING_MESSAGE_IDS.add(message_id)

            if lower.startswith("/model"):
                send_whatsapp_text(
                    sender,
                    "Generating model visualization while preserving the uploaded jewelry design. Please wait..."
                )
            else:
                send_whatsapp_text(
                    sender,
                    "Generating stone-change concept while preserving the uploaded jewelry design. Please wait..."
                )

            thread = threading.Thread(
                target=background_image_job,
                args=(sender, text, image_bytes, image_mime, message_id),
                daemon=True,
            )
            thread.start()

            return jsonify({"status": "image_generation_started"}), 200

        reply = call_openai(text, image_bytes, image_mime)
        reply += "\n\nManager approval required before customer sharing."
        send_whatsapp_text(sender, reply)

        if message_id:
            PROCESSED_MESSAGE_IDS.add(message_id)

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
