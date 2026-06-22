import os, json, base64, requests, threading
from io import BytesIO
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from openai import OpenAI
from PIL import Image
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

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME", ""),
    api_key=os.getenv("CLOUDINARY_API_KEY", ""),
    api_secret=os.getenv("CLOUDINARY_API_SECRET", ""),
    secure=True,
)

PROCESSED = set()
PROCESSING = set()

HERITAGE_PROMPT = """
You are Heritage Jewelry Design Director for Heritage Jewellers.
You are expert in Pakistani, South Asian, Mughal, bridal, kundan, meenakari,
moissanite, lab diamond, emerald, ruby, sapphire and pearl jewelry.
Never create generic Western minimalist jewelry.
Always keep Heritage DNA, commercial appeal and manufacturability.
Manager approval required before customer sharing.
"""

COMMAND_HELP = """/stone = exact stone colour change
/model = model visualization
/dress = dress matching
/collection = collection ideas
/bridal = bridal version
/caption = Instagram caption
/product = website description
/cad = CAD/manufacturing brief"""


def log_event(data):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    except Exception as e:
        print("LOG_ERROR", str(e), flush=True)


def wa_text(to, body):
    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": body[:4096]},
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print("WA_TEXT_SEND", r.status_code, r.text[:400], flush=True)
    return r


def wa_image(to, image_url, caption=""):
    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"link": image_url, "caption": caption[:1024]},
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print("WA_IMAGE_SEND", r.status_code, r.text[:400], flush=True)
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


def upload_cloudinary(image_bytes):
    result = cloudinary.uploader.upload(
        BytesIO(image_bytes),
        resource_type="image",
        folder="heritage-ai-designer",
    )
    return result["secure_url"]


def pil_to_png_bytes(img):
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def target_hue(text):
    t = (text or "").lower()
    if "blue" in t or "sapphire" in t:
        return 155
    if "green" in t or "emerald" in t:
        return 85
    if "pink" in t:
        return 235
    if "black" in t or "onyx" in t:
        return "black"
    if "white" in t or "pearl" in t:
        return "white"
    return 0


def exact_stone_colour_change(image_bytes, text):
    img = Image.open(BytesIO(image_bytes)).convert("RGBA")

    # Resize only if huge, to prevent Render memory crash.
    max_side = 1400
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side))

    rgb = img.convert("RGB")
    hsv = rgb.convert("HSV")

    hsv_pixels = list(hsv.getdata())
    alpha = img.getchannel("A")
    target = target_hue(text)

    new_pixels = []

    changed = 0

    for h, s, v in hsv_pixels:
        # Detect emerald/green stones by default.
        is_green = 55 <= h <= 115 and s > 45 and v > 35

        # Also detect blue stones if command says blue to another colour later.
        is_blue = 130 <= h <= 175 and s > 45 and v > 35

        # Detect ruby/red stones if command says ruby/red to another colour.
        is_red = (h <= 12 or h >= 240) and s > 45 and v > 35

        should_edit = is_green or is_blue or is_red

        if should_edit:
            changed += 1
            if target == "black":
                new_pixels.append((h, int(s * 0.3), int(v * 0.25)))
            elif target == "white":
                new_pixels.append((h, 20, min(255, int(v * 1.4))))
            else:
                new_pixels.append((target, min(255, int(s * 1.25)), min(255, int(v * 1.05))))
        else:
            new_pixels.append((h, s, v))

    print("STONE_PIXELS_CHANGED", changed, flush=True)

    hsv.putdata(new_pixels)
    result_rgb = hsv.convert("RGB")
    result = Image.merge("RGBA", (*result_rgb.split(), alpha))

    return pil_to_png_bytes(result)


def openai_text(text, image_bytes=None, image_mime="image/jpeg"):
    client = OpenAI(api_key=OPENAI_API_KEY)

    content = [{
        "type": "input_text",
        "text": f"Staff message: {text}\n\nCommands:\n{COMMAND_HELP}"
    }]

    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        content.append({
            "type": "input_image",
            "image_url": f"data:{image_mime};base64,{b64}"
        })

    response = client.responses.create(
        model=OPENAI_MODEL,
        instructions=HERITAGE_PROMPT,
        input=[{"role": "user", "content": content}],
    )
    return response.output_text


def model_visualization(image_bytes, image_mime, text):
    client = OpenAI(api_key=OPENAI_API_KEY)

    img_file = BytesIO(image_bytes)
    img_file.name = "heritage_product.png"

    prompt = f"""
Create a photorealistic Pakistani / South Asian model visualization for Heritage Jewellers.

Use the uploaded jewelry image as the main product reference.

Important:
- Keep the uploaded jewelry style as close as possible.
- Keep stone colour.
- Keep metal colour.
- Keep product category.
- Do not create Western minimalist jewelry.
- Jewelry must remain the hero.
- Luxury bridal / party wear styling.
- Warm premium studio lighting.
- No text, no logo.

Staff request:
{text}
"""

    result = client.images.edit(
        model=OPENAI_IMAGE_MODEL,
        image=img_file,
        prompt=prompt,
        size="1024x1024",
        n=1,
    )

    b64 = result.data[0].b64_json
    return base64.b64decode(b64)


def background_job(sender, text, image_bytes, image_mime, message_id):
    try:
        print("BACKGROUND_JOB_START", message_id, sender, text[:100], flush=True)
        lower = text.lower().strip()

        if lower.startswith("/stone"):
            output = exact_stone_colour_change(image_bytes, text)
            url = upload_cloudinary(output)
            wa_image(sender, url, "Exact stone-colour edit. Manager approval required before customer sharing.")

        elif lower.startswith("/model"):
            output = model_visualization(image_bytes, image_mime, text)
            url = upload_cloudinary(output)
            wa_image(sender, url, "Heritage model visualization. Manager approval required before customer sharing.")

        else:
            reply = openai_text(text, image_bytes, image_mime)
            reply += "\n\nManager approval required before customer sharing."
            wa_text(sender, reply)

        PROCESSED.add(message_id)
        print("BACKGROUND_JOB_DONE", message_id, flush=True)

    except Exception as e:
        print("BACKGROUND_JOB_ERROR", str(e), flush=True)
        wa_text(sender, f"Sorry, Heritage AI had an error: {str(e)[:700]}")
    finally:
        PROCESSING.discard(message_id)


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
    log_event({"time": datetime.now(timezone.utc).isoformat(), "payload": payload})

    try:
        value = payload.get("entry", [])[0].get("changes", [])[0].get("value", {})

        if "statuses" in value:
            return jsonify({"status": "status_update"}), 200

        messages = value.get("messages", [])
        if not messages:
            return jsonify({"status": "ignored"}), 200

        msg = messages[0]
        message_id = msg.get("id", "")

        if message_id in PROCESSED or message_id in PROCESSING:
            return jsonify({"status": "duplicate_ignored"}), 200

        sender = msg.get("from")

        if STAFF_NUMBERS and sender not in STAFF_NUMBERS:
            wa_text(sender, "Access denied. This Heritage AI Designer number is staff-only.")
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
            wa_text(sender, "Please send text or image with caption. Example: /stone ruby")
            return jsonify({"status": "unsupported"}), 200

        if not text:
            text = "Analyze this jewelry image for Heritage Jewellers."

        lower = text.lower().strip()

        if image_bytes and (lower.startswith("/stone") or lower.startswith("/model")):
            PROCESSING.add(message_id)

            if lower.startswith("/stone"):
                wa_text(sender, "Editing stone colour on the exact uploaded product. Please wait...")
            else:
                wa_text(sender, "Creating Heritage model visualization. Please wait...")

            thread = threading.Thread(
                target=background_job,
                args=(sender, text, image_bytes, image_mime, message_id),
                daemon=True,
            )
            thread.start()

            return jsonify({"status": "processing_started"}), 200

        reply = openai_text(text, image_bytes, image_mime)
        reply += "\n\nManager approval required before customer sharing."
        wa_text(sender, reply)

        if message_id:
            PROCESSED.add(message_id)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print("WEBHOOK_ERROR", str(e), flush=True)
        try:
            sender = payload["entry"][0]["changes"][0]["value"]["messages"][0]["from"]
            wa_text(sender, f"Sorry, Heritage AI had an error: {str(e)[:700]}")
        except Exception:
            pass
        return jsonify({"status": "error"}), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
