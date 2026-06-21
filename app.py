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

from PIL import Image, ImageEnhance, ImageFilter
import cv2
import numpy as np

try:
    from rembg import remove
except Exception:
    remove = None


app = Flask(__name__)

# ----------------------------
# Environment variables
# ----------------------------
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

ENABLE_EXACT_STONE_EDIT = os.getenv("ENABLE_EXACT_STONE_EDIT", "true").lower() == "true"
ENABLE_PRODUCT_COMPOSITING = os.getenv("ENABLE_PRODUCT_COMPOSITING", "true").lower() == "true"

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

You are expert in Pakistani, South Asian, Mughal-inspired, bridal, kundan, meenakari, silver,
gold, moissanite, lab diamond, and coloured-stone jewelry.

Always study uploaded reference images before responding.

Never create generic Western minimalist jewelry.

Prioritize emerald, ruby, sapphire, pearl, moissanite, lab diamond, kundan-inspired layouts,
arches, jharokhas, jaali, paisley, lotus, floral vines, regal drops, and handcrafted heritage details.

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

Manager approval required before customer sharing.
"""

COMMAND_HELP = """/stone = exact stone colour change
/model = show exact uploaded product on Pakistani/South Asian model
/dress = match dress with jewelry
/collection = create full collection
/bridal = bridal version
/caption = product/social caption
/product = website product description
/cad = CAD/manufacturing brief"""


# ----------------------------
# Basic utilities
# ----------------------------
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


def upload_image_to_cloudinary(image_bytes, folder="heritage-ai-designer"):
    upload_result = cloudinary.uploader.upload(
        BytesIO(image_bytes),
        resource_type="image",
        folder=folder,
    )
    return upload_result["secure_url"]


def pil_to_png_bytes(img):
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def open_image_rgba(image_bytes):
    return Image.open(BytesIO(image_bytes)).convert("RGBA")


# ----------------------------
# OpenAI text / analysis
# ----------------------------
def command_instructions(text):
    lower = (text or "").lower().strip()

    if lower.startswith("/model"):
        return "Analyze product category and give styling notes for exact product compositing."
    if lower.startswith("/stone"):
        return "Analyze which stone colour should be changed and which areas must remain unchanged."
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


# ----------------------------
# Exact /stone using image processing
# ----------------------------
def requested_target_color(text):
    lower = (text or "").lower()

    if "ruby" in lower or "red" in lower:
        return "ruby"
    if "sapphire" in lower or "blue" in lower:
        return "sapphire"
    if "emerald" in lower or "green" in lower:
        return "emerald"
    if "pink" in lower or "morganite" in lower:
        return "pink"
    if "black" in lower or "onyx" in lower:
        return "black"
    if "pearl" in lower or "white" in lower:
        return "white"

    return "ruby"


def hue_for_target(target):
    # OpenCV hue is 0-179
    return {
        "ruby": 0,
        "sapphire": 115,
        "emerald": 60,
        "pink": 165,
        "black": 0,
        "white": 0,
    }.get(target, 0)


def get_source_mask(hsv, text):
    """
    Creates a mask for common colored gemstones.
    Default: detect green emerald areas.
    If command mentions changing red/ruby, detect red. If blue/sapphire, detect blue.
    """
    lower = (text or "").lower()

    if "ruby to" in lower or "red to" in lower or "change ruby" in lower or "change red" in lower:
        mask1 = cv2.inRange(hsv, np.array([0, 40, 40]), np.array([12, 255, 255]))
        mask2 = cv2.inRange(hsv, np.array([170, 40, 40]), np.array([179, 255, 255]))
        mask = cv2.bitwise_or(mask1, mask2)
    elif "sapphire to" in lower or "blue to" in lower or "change sapphire" in lower or "change blue" in lower:
        mask = cv2.inRange(hsv, np.array([90, 40, 40]), np.array([135, 255, 255]))
    else:
        # default emerald/green stones
        mask = cv2.inRange(hsv, np.array([32, 35, 35]), np.array([92, 255, 255]))

    # Clean mask
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.GaussianBlur(mask, (5, 5), 0)
    return mask


def exact_stone_colour_change(image_bytes, text):
    """
    Pixel-level stone recolor. Keeps product shape, diamonds, metal, prongs, and background.
    Best for emerald/ruby/sapphire visible stones.
    """
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    rgb = np.array(img)

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    mask = get_source_mask(hsv, text)
    target = requested_target_color(text)

    result_hsv = hsv.copy()

    if target == "black":
        result_hsv[:, :, 1][mask > 0] = 30
        result_hsv[:, :, 2][mask > 0] = np.clip(result_hsv[:, :, 2][mask > 0] * 0.35, 0, 255)
    elif target == "white":
        result_hsv[:, :, 1][mask > 0] = 15
        result_hsv[:, :, 2][mask > 0] = np.clip(result_hsv[:, :, 2][mask > 0] * 1.35, 0, 255)
    else:
        result_hsv[:, :, 0][mask > 0] = hue_for_target(target)
        result_hsv[:, :, 1][mask > 0] = np.clip(result_hsv[:, :, 1][mask > 0] * 1.20, 0, 255)
        result_hsv[:, :, 2][mask > 0] = np.clip(result_hsv[:, :, 2][mask > 0] * 1.03, 0, 255)

    changed_rgb = cv2.cvtColor(result_hsv, cv2.COLOR_HSV2RGB)

    # Feather mask and blend for realistic edges
    alpha = (mask.astype(np.float32) / 255.0)[..., None]
    blended = (changed_rgb * alpha + rgb * (1 - alpha)).astype(np.uint8)

    out = Image.fromarray(blended).convert("RGBA")
    return pil_to_png_bytes(out)


# ----------------------------
# Product cutout / compositing for /model
# ----------------------------
def remove_background_from_product(image_bytes):
    if remove is None:
        # fallback: return original image with alpha as-is
        return open_image_rgba(image_bytes)

    try:
        cutout_bytes = remove(image_bytes)
        return Image.open(BytesIO(cutout_bytes)).convert("RGBA")
    except Exception as exc:
        print("REMBG_ERROR", str(exc), flush=True)
        return open_image_rgba(image_bytes)


def trim_transparent(img):
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    bbox = img.getbbox()
    if bbox:
        return img.crop(bbox)
    return img


def generate_model_without_jewelry(text):
    """
    Generates a model base image WITHOUT jewelry, so we can overlay the exact product.
    """
    client = OpenAI(api_key=OPENAI_API_KEY)

    prompt = f"""
Create a photorealistic luxury jewelry campaign portrait for Heritage Jewellers.

Staff request:
{text}

Important:
- Pakistani / South Asian female model.
- Elegant bridal or party-wear styling.
- Face visible, ears visible, neck visible.
- Clean beauty lighting.
- Warm luxury studio background.
- NO earrings.
- NO necklace.
- NO ring.
- NO jewelry at all.
- Leave ears and neckline clean for product compositing.
- Realistic human proportions.
- High-end fashion campaign look.
- No text.
- No logo.
"""

    result = client.images.generate(
        model=OPENAI_IMAGE_MODEL,
        prompt=prompt,
        size="1024x1024",
        quality="medium",
        n=1,
    )

    image_base64 = result.data[0].b64_json
    model_bytes = base64.b64decode(image_base64)
    return Image.open(BytesIO(model_bytes)).convert("RGBA")


def detect_product_type(text):
    lower = (text or "").lower()
    if "ring" in lower:
        return "ring"
    if "necklace" in lower or "choker" in lower or "set" in lower:
        return "necklace"
    if "pendant" in lower:
        return "pendant"
    if "bracelet" in lower or "bangle" in lower:
        return "bracelet"
    # default for your current use case
    return "earrings"


def resize_product_for_model(product, product_type):
    w, h = product.size

    if product_type == "earrings":
        target_w = 150
    elif product_type == "ring":
        target_w = 210
    elif product_type == "necklace":
        target_w = 420
    elif product_type == "pendant":
        target_w = 260
    else:
        target_w = 250

    scale = target_w / max(w, 1)
    target_h = int(h * scale)
    return product.resize((target_w, target_h), Image.Resampling.LANCZOS)


def add_soft_shadow(layer):
    alpha = layer.getchannel("A")
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shadow.putalpha(alpha.filter(ImageFilter.GaussianBlur(4)))
    return shadow


def composite_product_on_model(model_img, product_img, product_type):
    """
    Places exact cutout product on generated model. Placement is heuristic.
    It preserves product pixels far better than AI redraw.
    """
    canvas = model_img.convert("RGBA").copy()
    product = trim_transparent(product_img.convert("RGBA"))
    product = resize_product_for_model(product, product_type)

    cw, ch = canvas.size
    pw, ph = product.size

    # Slight enhancement so jewelry appears like campaign jewelry.
    product = ImageEnhance.Sharpness(product).enhance(1.15)
    product = ImageEnhance.Contrast(product).enhance(1.05)

    if product_type == "earrings":
        # If uploaded image has a pair of earrings, place the pair around both ears.
        # Coordinates are portrait heuristics for 1024x1024 model.
        x = int((cw - pw) / 2)
        y = int(ch * 0.33)

    elif product_type == "ring":
        x = int(cw * 0.58)
        y = int(ch * 0.70)

    elif product_type == "necklace":
        x = int((cw - pw) / 2)
        y = int(ch * 0.58)

    elif product_type == "pendant":
        x = int((cw - pw) / 2)
        y = int(ch * 0.55)

    else:
        x = int((cw - pw) / 2)
        y = int(ch * 0.50)

    shadow = add_soft_shadow(product)
    shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_layer.alpha_composite(shadow, (x + 4, y + 6))
    canvas = Image.alpha_composite(canvas, shadow_layer)

    product_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    product_layer.alpha_composite(product, (x, y))
    canvas = Image.alpha_composite(canvas, product_layer)

    return canvas


def exact_model_composite(image_bytes, text):
    product_type = detect_product_type(text)
    product_cutout = remove_background_from_product(image_bytes)
    model_img = generate_model_without_jewelry(text)
    final_img = composite_product_on_model(model_img, product_cutout, product_type)
    return pil_to_png_bytes(final_img)


# ----------------------------
# Background jobs
# ----------------------------
def background_image_job(sender, text, image_bytes, image_mime, message_id):
    try:
        print("BACKGROUND_JOB_START", message_id, sender, text[:120], flush=True)
        lower = text.lower().strip()

        if lower.startswith("/stone"):
            if ENABLE_EXACT_STONE_EDIT:
                output_bytes = exact_stone_colour_change(image_bytes, text)
                image_url = upload_image_to_cloudinary(output_bytes)

                send_whatsapp_image(
                    sender,
                    image_url,
                    "Exact stone-colour edit. Manager approval required before customer sharing.",
                )
            else:
                send_whatsapp_text(sender, "Exact stone edit is disabled in Render environment.")

        elif lower.startswith("/model"):
            if ENABLE_PRODUCT_COMPOSITING:
                output_bytes = exact_model_composite(image_bytes, text)
                image_url = upload_image_to_cloudinary(output_bytes)

                send_whatsapp_image(
                    sender,
                    image_url,
                    "Product compositing visualization. Manager approval required before customer sharing.",
                )
            else:
                send_whatsapp_text(sender, "Product compositing is disabled in Render environment.")

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
            f"Sorry, Heritage AI had an image-processing error: {str(exc)[:700]}"
        )
    finally:
        PROCESSING_MESSAGE_IDS.discard(message_id)


# ----------------------------
# Flask routes
# ----------------------------
@app.route("/", methods=["GET"])
def home():
    return "Heritage WhatsApp AI Designer v4 backend is running.", 200


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

        # Ignore delivery/read status webhooks.
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
            send_whatsapp_text(sender, "Please send a text command or image with caption. Example: /stone emerald to ruby")
            return jsonify({"status": "unsupported"}), 200

        if not text:
            text = "Analyze this image for Heritage Jewellers."

        lower = text.lower().strip()

        if (lower.startswith("/stone") or lower.startswith("/model")) and image_bytes:
            PROCESSING_MESSAGE_IDS.add(message_id)

            if lower.startswith("/stone"):
                send_whatsapp_text(
                    sender,
                    "Creating exact stone-colour edit while preserving the original product. Please wait..."
                )
            else:
                send_whatsapp_text(
                    sender,
                    "Creating model visualization using exact uploaded product overlay. Please wait..."
                )

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
            send_whatsapp_text(sender, f"Sorry, Heritage AI had an error: {str(exc)[:700]}")
        except Exception:
            pass

        return jsonify({"status": "error", "message": str(exc)}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
