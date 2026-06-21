import os
import json
import base64
import requests
import threading
import re
from io import BytesIO
from datetime import datetime, timezone

import numpy as np
import cv2
from PIL import Image, ImageEnhance, ImageOps
from flask import Flask, request, jsonify
from openai import OpenAI

import cloudinary
import cloudinary.uploader

try:
    from rembg import remove
except Exception:
    remove = None


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

You are expert in Pakistani, South Asian, Mughal-inspired, bridal, kundan, meenakari,
silver, gold, moissanite, lab diamond, and coloured-stone jewelry.

Always study uploaded reference images before responding.

Never create generic Western minimalist jewelry.

Prioritize emerald, ruby, sapphire, pearl, moissanite, lab diamond,
kundan-inspired layouts, arches, jharokhas, jaali, paisley, lotus,
floral vines, regal drops, and handcrafted heritage details.

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

For model visualization, do not redesign the uploaded jewelry.
For stone replacement, only change the requested stone colour.

Manager approval required before customer sharing.
"""

COMMAND_HELP = """/stone = exact stone color replacement
/model = show exact uploaded jewelry on Pakistani/South Asian model
/dress = match dress with jewelry
/collection = create full collection
/bridal = bridal version
/caption = product/social caption
/product = website product description
/cad = CAD/manufacturing brief"""


# -------------------------
# Utilities
# -------------------------

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
        "image": {"link": image_url, "caption": caption[:1024]},
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


def pil_to_png_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def upload_image_to_cloudinary(image_bytes, folder="heritage-ai-designer"):
    upload_result = cloudinary.uploader.upload(
        BytesIO(image_bytes),
        resource_type="image",
        folder=folder,
    )
    return upload_result["secure_url"]


# -------------------------
# OpenAI text / analysis
# -------------------------

def command_instructions(text):
    lower = (text or "").lower().strip()
    if lower.startswith("/model"):
        return "Analyze uploaded jewelry for exact product-on-model compositing. Do not redesign."
    if lower.startswith("/stone"):
        return "Analyze uploaded jewelry for exact stone colour replacement. Do not redesign."
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

    user_content = [{
        "type": "input_text",
        "text": f"Staff message: {text or ''}\n\nTask: {command_instructions(text)}\n\nCommands:\n{COMMAND_HELP}",
    }]

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


def detect_product_type(text, image_bytes, image_mime):
    """Small classifier used for compositing placement."""
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        response = client.responses.create(
            model=OPENAI_MODEL,
            instructions=(
                "Classify the uploaded jewelry into one word only: "
                "earrings, ring, pendant, necklace, bracelet, bangle, set, unknown."
            ),
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": f"User request: {text}"},
                    {"type": "input_image", "image_url": f"data:{image_mime};base64,{b64}"},
                ],
            }],
        )
        result = response.output_text.lower()
        for k in ["earrings", "ring", "pendant", "necklace", "bracelet", "bangle", "set"]:
            if k in result:
                return k
    except Exception as exc:
        print("DETECT_PRODUCT_TYPE_ERROR", str(exc), flush=True)

    lower = (text or "").lower()
    if "ring" in lower:
        return "ring"
    if "necklace" in lower:
        return "necklace"
    if "pendant" in lower:
        return "pendant"
    if "bracelet" in lower or "bangle" in lower:
        return "bracelet"
    return "earrings"


# -------------------------
# EXACT /stone processing
# -------------------------

TARGET_HUES = {
    "ruby": 0,
    "red": 0,
    "maroon": 175,
    "emerald": 60,
    "green": 60,
    "sapphire": 115,
    "blue": 115,
    "navy": 120,
    "yellow": 28,
    "champagne": 22,
    "pink": 165,
    "purple": 140,
    "amethyst": 140,
    "black": None,
    "white": None,
}


def target_colour_from_text(text):
    lower = (text or "").lower()
    for word in ["ruby", "red", "emerald", "green", "sapphire", "blue", "navy",
                 "yellow", "champagne", "pink", "purple", "amethyst", "black", "white", "maroon"]:
        if word in lower:
            return word
    return "ruby"


def build_coloured_stone_mask(rgb_arr):
    """Detect saturated coloured stones, avoiding diamonds/white background/gold metal."""
    hsv = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

    # Saturated non-white, non-gray coloured areas are likely stones.
    mask = ((s > 45) & (v > 45)).astype(np.uint8) * 255

    # Exclude common yellow-gold metal range to avoid changing gold.
    gold_mask = (((h >= 15) & (h <= 38) & (s > 35) & (v > 70))).astype(np.uint8) * 255
    mask = cv2.bitwise_and(mask, cv2.bitwise_not(gold_mask))

    # Clean mask.
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    return mask


def exact_stone_colour_edit(image_bytes, target_word):
    """
    Pixel-level stone colour edit.
    This preserves prongs, diamonds, metal, layout, perspective, and background.
    """
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    rgb = np.array(img)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)

    mask = build_coloured_stone_mask(rgb)

    target_word = target_word.lower().strip()
    hue = TARGET_HUES.get(target_word, 0)

    edited_hsv = hsv.copy()

    if target_word == "black":
        edited_hsv[:, :, 2][mask > 0] = np.clip(edited_hsv[:, :, 2][mask > 0] * 0.25, 0, 255)
        edited_hsv[:, :, 1][mask > 0] = np.clip(edited_hsv[:, :, 1][mask > 0] * 0.55, 0, 255)
    elif target_word == "white":
        edited_hsv[:, :, 1][mask > 0] = 15
        edited_hsv[:, :, 2][mask > 0] = np.maximum(edited_hsv[:, :, 2][mask > 0], 210)
    else:
        edited_hsv[:, :, 0][mask > 0] = hue
        edited_hsv[:, :, 1][mask > 0] = np.maximum(edited_hsv[:, :, 1][mask > 0], 120)
        edited_hsv[:, :, 2][mask > 0] = np.maximum(edited_hsv[:, :, 2][mask > 0], 80)

    edited_rgb = cv2.cvtColor(edited_hsv, cv2.COLOR_HSV2RGB)

    # Soft blend only on mask edges for natural result.
    soft_mask = cv2.GaussianBlur(mask, (7, 7), 0).astype(np.float32) / 255.0
    soft_mask = soft_mask[:, :, None]
    final = (edited_rgb * soft_mask + rgb * (1 - soft_mask)).astype(np.uint8)

    out = Image.fromarray(final)
    return pil_to_png_bytes(out)


# -------------------------
# /model compositing
# -------------------------

def generate_model_base(product_type):
    """Generate model image with no jewelry; exact jewelry is overlaid afterward."""
    client = OpenAI(api_key=OPENAI_API_KEY)

    if product_type == "ring":
        prompt = """
Create a photorealistic luxury Pakistani/South Asian model campaign image.
Show elegant hands in a premium jewelry pose, but DO NOT include any jewelry or ring.
Clean hands, neutral luxury background, soft studio lighting.
Leave clear empty ring finger area for product overlay.
No text, no logo.
"""
    elif product_type in ["necklace", "pendant", "set"]:
        prompt = """
Create a photorealistic Pakistani/South Asian female model portrait for a luxury jewelry campaign.
Do NOT include any necklace, pendant, earrings, or jewelry.
Elegant bridal/party styling, visible neck and upper chest area, soft studio lighting.
Leave the neck area clean and empty for jewelry overlay.
No text, no logo.
"""
    else:
        prompt = """
Create a photorealistic Pakistani/South Asian female model portrait for a luxury jewelry campaign.
Do NOT include earrings, necklace, or any jewelry.
Hair styled to reveal both ears clearly.
Elegant bridal/party styling, soft studio lighting, clean luxury background.
Leave both ears empty and visible for earring overlay.
No text, no logo.
"""

    result = client.images.generate(
        model=OPENAI_IMAGE_MODEL,
        prompt=prompt,
        size="1024x1024",
        quality="medium",
        n=1,
    )
    image_bytes = base64.b64decode(result.data[0].b64_json)
    return Image.open(BytesIO(image_bytes)).convert("RGBA")


def remove_bg_product(image_bytes):
    """
    Cut out product. If rembg fails, use simple white-background removal.
    """
    if remove is not None:
        try:
            cutout_bytes = remove(image_bytes)
            return Image.open(BytesIO(cutout_bytes)).convert("RGBA")
        except Exception as exc:
            print("REMBG_ERROR", str(exc), flush=True)

    img = Image.open(BytesIO(image_bytes)).convert("RGBA")
    arr = np.array(img)
    rgb = arr[:, :, :3]
    # Remove near-white background.
    white = (rgb[:, :, 0] > 225) & (rgb[:, :, 1] > 225) & (rgb[:, :, 2] > 225)
    arr[:, :, 3][white] = 0
    return Image.fromarray(arr)


def trim_transparent(img):
    bbox = img.getbbox()
    if bbox:
        return img.crop(bbox)
    return img


def resize_keep_aspect(img, target_width=None, target_height=None):
    w, h = img.size
    if target_width:
        ratio = target_width / float(w)
    elif target_height:
        ratio = target_height / float(h)
    else:
        ratio = 1
    return img.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.LANCZOS)


def composite_product_on_model(product_bytes, product_type):
    model = generate_model_base(product_type)
    product = remove_bg_product(product_bytes)
    product = trim_transparent(product)

    canvas = model.copy()

    if product_type == "ring":
        # Place on visible hand/finger area. This is approximate but preserves exact product.
        p = resize_keep_aspect(product, target_width=170)
        p = p.rotate(-8, expand=True, resample=Image.BICUBIC)
        x, y = 560, 650
        canvas.alpha_composite(p, (x, y))

    elif product_type in ["necklace", "pendant"]:
        p = resize_keep_aspect(product, target_width=420)
        x = (1024 - p.size[0]) // 2
        y = 485
        canvas.alpha_composite(p, (x, y))

    elif product_type in ["bracelet", "bangle"]:
        p = resize_keep_aspect(product, target_width=260)
        p = p.rotate(-12, expand=True, resample=Image.BICUBIC)
        x, y = 560, 690
        canvas.alpha_composite(p, (x, y))

    else:
        # Earrings/studs: overlay exact product on both ears.
        earring = resize_keep_aspect(product, target_width=90)
        left = earring
        right = ImageOps.mirror(earring)

        # Approximate ear positions on generated portrait.
        canvas.alpha_composite(left, (318, 420))
        canvas.alpha_composite(right, (615, 420))

    final = canvas.convert("RGB")
    final = ImageEnhance.Sharpness(final).enhance(1.08)
    return pil_to_png_bytes(final)


# -------------------------
# Background jobs
# -------------------------

def background_image_job(sender, text, image_bytes, image_mime, message_id):
    try:
        print("BACKGROUND_JOB_START", message_id, sender, text[:100], flush=True)
        lower = text.lower().strip()

        if lower.startswith("/stone"):
            target = target_colour_from_text(text)
            edited_bytes = exact_stone_colour_edit(image_bytes, target)
            image_url = upload_image_to_cloudinary(edited_bytes)
            send_whatsapp_image(
                sender,
                image_url,
                f"Exact stone colour edit: {target}. Manager approval required before customer sharing.",
            )

        elif lower.startswith("/model"):
            product_type = detect_product_type(text, image_bytes, image_mime)
            final_bytes = composite_product_on_model(image_bytes, product_type)
            image_url = upload_image_to_cloudinary(final_bytes)
            send_whatsapp_image(
                sender,
                image_url,
                "Exact product composite on model. Manager approval required before customer sharing.",
            )

        else:
            reply = call_openai(text, image_bytes, image_mime)
            reply += "\n\nManager approval required before customer sharing."
            send_whatsapp_text(sender, reply)

        PROCESSED_MESSAGE_IDS.add(message_id)
        print("BACKGROUND_JOB_DONE", message_id, flush=True)

    except Exception as exc:
        print("BACKGROUND_JOB_ERROR", str(exc), flush=True)
        send_whatsapp_text(sender, f"Sorry, Heritage AI had an image-processing error: {str(exc)[:500]}")
    finally:
        PROCESSING_MESSAGE_IDS.discard(message_id)


# -------------------------
# Routes
# -------------------------

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
            send_whatsapp_text(sender, "Please send a text command or image with caption. Example: /stone change emerald to ruby")
            return jsonify({"status": "unsupported"}), 200

        if not text:
            text = "Analyze this image for Heritage Jewellers."

        lower = text.lower().strip()

        if (lower.startswith("/stone") or lower.startswith("/model")) and image_bytes:
            PROCESSING_MESSAGE_IDS.add(message_id)

            if lower.startswith("/stone"):
                send_whatsapp_text(sender, "Editing stone colour on the exact uploaded product. Please wait...")
            else:
                send_whatsapp_text(sender, "Creating model composite using the exact uploaded product. Please wait...")

            thread = threading.Thread(
                target=background_image_job,
                args=(sender, text, image_bytes, image_mime, message_id),
                daemon=True,
            )
            thread.start()

            return jsonify({"status": "image_processing_started"}), 200

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
