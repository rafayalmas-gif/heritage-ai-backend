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

COMMAND_HELP = """/stone ruby = change only mounted jewelry stones to deep ruby
/stone emerald = change only mounted jewelry stones to deep emerald
/stone sapphire = change only mounted jewelry stones to deep sapphire
/model = show exact uploaded jewelry on South Asian model
/polish yellow gold = change only metal polish
/polish white gold = change only metal polish
/polish rose gold = change only metal polish
/caption = Instagram caption
/product = website product description
/cad = CAD/manufacturing brief"""

HERITAGE_PROMPT = """
You are Heritage Jewelry Design Director for Heritage Jewellers.
Expert in Pakistani, South Asian, Mughal-inspired, bridal, kundan, meenakari,
gold, silver, moissanite, lab diamond, emerald, ruby, sapphire and pearl jewelry.
Never create generic Western minimalist jewelry.
Manager approval required before customer sharing.
"""


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
    print("WA_TEXT_SEND", r.status_code, r.text[:500], flush=True)
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


def upload_cloudinary(image_bytes):
    result = cloudinary.uploader.upload(
        BytesIO(image_bytes),
        resource_type="image",
        folder="heritage-ai-designer",
    )
    return result["secure_url"]


def prepare_image_file(image_bytes):
    img = Image.open(BytesIO(image_bytes)).convert("RGBA")
    max_side = 1600
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side))

    out = BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    out.name = "heritage_input.png"
    return out


def requested_stone(text):
    t = (text or "").lower()
    if "sapphire" in t or "blue" in t:
        return "royal deep Kashmir sapphire blue"
    if "emerald" in t or "green" in t:
        return "deep Colombian emerald green"
    if "ruby" in t or "red" in t:
        return "deep pigeon-blood ruby red"
    if "pink" in t or "morganite" in t:
        return "soft luxury pink morganite"
    if "black" in t or "onyx" in t:
        return "deep black onyx"
    return "deep pigeon-blood ruby red"


def requested_polish(text):
    t = (text or "").lower()
    if "white" in t:
        return "white gold polish"
    if "rose" in t:
        return "rose gold polish"
    if "silver" in t:
        return "silver polish"
    if "yellow" in t or "gold" in t:
        return "yellow gold polish"
    return "yellow gold polish"


def image_edit(image_bytes, prompt):
    client = OpenAI(api_key=OPENAI_API_KEY)
    image_file = prepare_image_file(image_bytes)

    result = client.images.edit(
        model=OPENAI_IMAGE_MODEL,
        image=image_file,
        prompt=prompt,
        size="1024x1024",
        n=1,
    )

    return base64.b64decode(result.data[0].b64_json)


def stone_edit_ai(image_bytes, text):
    stone = requested_stone(text)

    prompt = f"""
Edit the uploaded jewelry photo for Heritage Jewellers.

Task:
Change ONLY the gemstones that are physically mounted inside the MAIN jewelry piece to {stone}.

Very important:
- First identify the MAIN jewelry item or jewelry set.
- Edit ONLY stones mounted inside that jewelry.
- Do NOT edit loose stones lying in the background.
- Do NOT edit decorative stones, chairs, showcase, dummy, tray, labels, tags, box, cloth, skin, hand, ear, neck, hair, model, floor or wall.
- Do NOT change diamonds.
- Do NOT change pearls.
- Do NOT change metal.
- Do NOT change jewelry design.
- Do NOT change stone count.
- Do NOT change stone shape.
- Do NOT change prongs.
- Do NOT change size, placement, angle, background, lighting or camera perspective.

Gemstone realism:
- Use dark luxury gemstone colour.
- Preserve original stone cut, facets, transparency, shine, reflection, highlights, shadows and depth.
- Result must look like a real gemstone, not painted colour.

Return only the edited image.
"""

    return image_edit(image_bytes, prompt)


def polish_edit_ai(image_bytes, text):
    polish = requested_polish(text)

    prompt = f"""
Edit the uploaded jewelry photo for Heritage Jewellers.

Task:
Change ONLY the jewelry metal polish to {polish}.

Very important:
- Edit only metal areas.
- Do NOT edit gemstones.
- Do NOT edit diamonds.
- Do NOT edit pearls.
- Do NOT edit skin, hand, ear, neck, hair, model, box, tray, tags, chair, showcase, cloth, wall or background.
- Do NOT change jewelry design, stone shape, stone count, size, placement or camera angle.
- Preserve original reflections, shine, shadows and luxury finish.

Return only the edited image.
"""

    return image_edit(image_bytes, prompt)


def model_edit_ai(image_bytes, text):
    prompt = f"""
Create a luxury Heritage Jewellers model visualization.

Use the uploaded jewelry as the exact reference.

Very important:
- Show the EXACT uploaded jewelry product on a Pakistani / South Asian model.
- Do NOT redesign the jewelry.
- Do NOT change stone colour.
- Do NOT change metal colour.
- Do NOT change stone count.
- Do NOT change stone shape.
- Do NOT change diamond layout.
- Do NOT change prongs, size, proportions or design language.
- Jewelry must remain the hero.
- If uploaded product is earrings, place on ears.
- If uploaded product is ring, place on hand.
- If uploaded product is necklace or pendant, place on neck.
- Luxury bridal / party wear South Asian styling.
- Photorealistic campaign image.
- No text, no logo, no watermark.

Staff request:
{text}

Return only the model visualization image.
"""

    return image_edit(image_bytes, prompt)


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


def background_job(sender, text, image_bytes, image_mime, message_id):
    try:
        print("BACKGROUND_JOB_START", message_id, sender, text[:100], flush=True)
        lower = text.lower().strip()

        if lower.startswith("/stone"):
            output = stone_edit_ai(image_bytes, text)
            url = upload_cloudinary(output)
            wa_image(sender, url, "Stone colour edit. Manager approval required before customer sharing.")

        elif lower.startswith("/polish"):
            output = polish_edit_ai(image_bytes, text)
            url = upload_cloudinary(output)
            wa_image(sender, url, "Metal polish edit. Manager approval required before customer sharing.")

        elif lower.startswith("/model"):
            output = model_edit_ai(image_bytes, text)
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

        image_commands = (
            lower.startswith("/stone")
            or lower.startswith("/model")
            or lower.startswith("/polish")
        )

        if image_bytes and image_commands:
            PROCESSING.add(message_id)

            if lower.startswith("/stone"):
                wa_text(sender, "Editing only mounted gemstones inside the main jewelry piece. Please wait...")
            elif lower.startswith("/polish"):
                wa_text(sender, "Changing only metal polish while preserving stones and design. Please wait...")
            else:
                wa_text(sender, "Creating Heritage model visualization using uploaded jewelry reference. Please wait...")

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
