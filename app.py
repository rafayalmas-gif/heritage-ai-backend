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
Expert in Pakistani, South Asian, Mughal-inspired, bridal, kundan, meenakari, gold, silver,
moissanite, lab diamond, emerald, ruby, sapphire, pearl and colored-stone jewelry.
Never create generic Western minimalist jewelry.
Manager approval required before customer sharing.
"""

COMMAND_HELP = """/stone ruby = change mounted main jewelry stones only
/stone emerald = change mounted main jewelry stones only
/stone sapphire = change mounted main jewelry stones only
/stone yellow sapphire = yellow pukhraj tone
/stone grey pearl = pearl tone edit
/polish white gold = metal only
/polish yellow gold = metal only
/polish rose gold = metal only
/model = 2 model options
/model 3 options = 3 model options
/caption = Instagram caption
/product = website description
/cad = manufacturing brief
/bridal = bridal concept
/collection = collection concept"""

STONE_PROFILES = {
    "ruby": ("deep pigeon-blood ruby red", False), "rubi": ("deep pigeon-blood ruby red", False),
    "laal": ("deep pigeon-blood ruby red", False), "red": ("deep pigeon-blood ruby red", False),
    "emerald": ("deep Colombian emerald green", False), "zamurd": ("deep Colombian emerald green", False),
    "zamarud": ("deep Colombian emerald green", False), "panna": ("deep Colombian emerald green", False),
    "green": ("deep Colombian emerald green", False),
    "sapphire": ("royal dark blue Kashmir sapphire", False), "blue sapphire": ("royal dark blue Kashmir sapphire", False),
    "neelam": ("royal dark blue Kashmir sapphire", False), "blue": ("royal dark blue Kashmir sapphire", False),
    "yellow sapphire": ("rich golden yellow pukhraj sapphire", False), "pukhraj": ("rich golden yellow pukhraj sapphire", False),
    "yellow": ("rich golden yellow pukhraj sapphire", False),
    "topaz": ("Swiss blue topaz", False), "firoza": ("natural turquoise blue-green stone", False),
    "turquoise": ("natural turquoise blue-green stone", False),
    "amethyst": ("deep royal purple amethyst", False), "jamunia": ("deep royal purple amethyst", False),
    "falsa": ("dark blackberry-purple amethyst tone", False),
    "champagne": ("warm champagne golden-brown gemstone", False), "garnet": ("deep wine-red garnet", False),
    "aqeeq": ("deep wine-red garnet", False), "onyx": ("deep black onyx", False),
    "black": ("deep black onyx", False), "morganite": ("soft peach-pink morganite", False),
    "pink": ("rich pink sapphire tone", False),
    "pearl": ("smooth white pearl with natural pearl luster", True), "moti": ("smooth white pearl with natural pearl luster", True),
    "white pearl": ("smooth white pearl with natural pearl luster", True),
    "grey pearl": ("smooth grey pearl with natural pearl luster", True), "gray pearl": ("smooth grey pearl with natural pearl luster", True),
    "pink pearl": ("smooth pink pearl with natural pearl luster", True),
    "black pearl": ("smooth black pearl with natural pearl luster", True),
    "champagne pearl": ("smooth champagne pearl with natural pearl luster", True),
}

def log_event(data):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    except Exception as e:
        print("LOG_ERROR", str(e), flush=True)

def wa_text(to, body):
    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"preview_url": False, "body": body[:4096]}}
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print("WA_TEXT_SEND", r.status_code, r.text[:500], flush=True)
    return r

def wa_image(to, image_url, caption=""):
    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "image", "image": {"link": image_url, "caption": caption[:1024]}}
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print("WA_IMAGE_SEND", r.status_code, r.text[:500], flush=True)
    return r

def get_media_url(media_id):
    r = requests.get(f"https://graph.facebook.com/v20.0/{media_id}", headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}, timeout=30)
    r.raise_for_status()
    return r.json().get("url")

def download_media(media_url):
    r = requests.get(media_url, headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}, timeout=60)
    r.raise_for_status()
    return r.content, r.headers.get("Content-Type", "image/jpeg")

def upload_cloudinary(image_bytes):
    result = cloudinary.uploader.upload(BytesIO(image_bytes), resource_type="image", folder="heritage-ai-designer")
    return result["secure_url"]

def prepare_png(image_bytes, max_side=1600):
    img = Image.open(BytesIO(image_bytes)).convert("RGBA")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
    out = BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    out.name = "heritage_input.png"
    return out

def requested_stone(text):
    t = (text or "").lower()
    for key in sorted(STONE_PROFILES, key=len, reverse=True):
        if key in t:
            return key, STONE_PROFILES[key][0], STONE_PROFILES[key][1]
    return "ruby", STONE_PROFILES["ruby"][0], False

def requested_polish(text):
    t = (text or "").lower()
    if "white" in t:
        return "white gold polish, cool bright luxury white metal"
    if "rose" in t:
        return "rose gold polish, warm pink luxury metal"
    if "silver" in t:
        return "silver polish, bright cool silver tone"
    return "yellow gold polish, rich warm yellow gold tone"

def openai_text(text, image_bytes=None, image_mime="image/jpeg", instructions=HERITAGE_PROMPT):
    client = OpenAI(api_key=OPENAI_API_KEY)
    content = [{"type": "input_text", "text": f"Staff message: {text}\n\nCommands:\n{COMMAND_HELP}"}]
    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        content.append({"type": "input_image", "image_url": f"data:{image_mime};base64,{b64}"})
    response = client.responses.create(model=OPENAI_MODEL, instructions=instructions, input=[{"role": "user", "content": content}])
    return response.output_text

def product_lock_sheet(image_bytes, image_mime, text):
    instructions = """
You are a strict jewelry product inspector. Analyze the uploaded jewelry image and return a compact lock sheet:
product type, main jewelry piece, mounted main stones, small diamonds/zircons, pearls, metal polish, chain/lock/hook/bail, exact parts that must not change.
Do not be creative.
"""
    return openai_text(text, image_bytes, image_mime, instructions)

def image_edit(image_bytes, prompt):
    client = OpenAI(api_key=OPENAI_API_KEY)
    result = client.images.edit(model=OPENAI_IMAGE_MODEL, image=prepare_png(image_bytes), prompt=prompt, size="1024x1024", n=1)
    return base64.b64decode(result.data[0].b64_json)

def stone_edit(image_bytes, image_mime, text):
    _, profile, pearl_target = requested_stone(text)
    lock = product_lock_sheet(image_bytes, image_mime, text)
    prompt = f"""
Edit this jewelry photo for Heritage Jewellers.

TASK: Change ONLY mounted main stones/pearls inside the MAIN jewelry product to {profile}.

PRODUCT LOCK SHEET:
{lock}

STRICT RULES:
- First identify the main jewelry item/set.
- Edit only stones physically mounted inside the main jewelry item.
- Ignore loose background stones, props, chairs, showcase, trays, tags, boxes, hands, skin, ear, neck, hair, model, dummy, floor, wall, shadows and reflections.
- Do not edit diamonds, zircon, CZ, moissanite, small white halo stones, or pearls unless the requested target is pearl or the main stone is pearl.
- If pearl to pearl: keep smooth round pearl surface, change only pearl tone/luster.
- If pearl to gemstone: replace smooth pearl appearance with realistic faceted gemstone fitted in the same setting.
- If gemstone to pearl: replace faceted look with smooth pearl of same size/position.
- Preserve jewelry design, stone count, shape, size, placement, prongs, bezels, chain, bail, clasp, lock, polish, angle and background.
- Use luxury dark realistic gemstone tone. Preserve facets, depth, highlights and shadows. No painted look.
Return only the edited image.
"""
    return image_edit(image_bytes, prompt)

def polish_edit(image_bytes, image_mime, text):
    polish = requested_polish(text)
    lock = product_lock_sheet(image_bytes, image_mime, text)
    prompt = f"""
Edit this jewelry photo for Heritage Jewellers.

TASK: Change ONLY metal polish to {polish}.

PRODUCT LOCK SHEET:
{lock}

RULES:
- Edit only metal areas.
- Do not edit gemstones, pearls, diamonds, zircons, CZ, moissanite.
- Do not edit skin, hand, ear, model, background, box, tag, chair, showcase, cloth, shadows or reflections.
- Preserve design, stones, stone count, stone color, pearl luster, prongs, chain, bail, clasp, lock, camera angle and background.
Return only the edited image.
"""
    return image_edit(image_bytes, prompt)

def model_edit_multi(image_bytes, image_mime, text):
    lock = product_lock_sheet(image_bytes, image_mime, text)
    count = 3 if any(x in text.lower() for x in ["3", "three", "options"]) else 2
    base = f"""
Create a customer-shareable Heritage Jewellers model visualization.

UPLOADED JEWELRY IS THE MASTER REFERENCE.
PRODUCT LOCK SHEET:
{lock}

ABSOLUTE LOCK:
- Use same jewelry product only.
- Do not redesign.
- Do not change stone count, stone shape, stone color, diamond layout, metal color, polish, chain, bail, clasp, hook, lock, fitting, size ratio, dimensions, or proportions.
- Do not add extra jewelry. Do not remove product components.
- If earrings: show earrings on ear. If ring: show ring on finger. If pendant/necklace: show on neck. If bangle/bracelet: show on wrist.
- Pakistani/South Asian model, luxury Heritage styling, realistic skin, realistic contact shadows, professional campaign lighting.
- No text, logo or watermark.
"""
    prompts = [
        base + "\nVIEW 1: Close-up placement view.",
        base + "\nVIEW 2: Styled South Asian model portrait, jewelry visible and hero.",
    ]
    if count >= 3:
        prompts.append(base + "\nVIEW 3: Luxury campaign/banner angle.")
    return [image_edit(image_bytes, p) for p in prompts]

def content_command(text, image_bytes=None, image_mime="image/jpeg"):
    lower = text.lower()
    tasks = {
        "/caption": "Write premium Instagram caption, short version, long version, and hashtags.",
        "/product": "Write website title, short description, full description, styling notes, and SEO keywords.",
        "/cad": "Write CAD/manufacturing brief with setting, construction, stone placement, comfort, and production notes.",
        "/bridal": "Create a Heritage bridal version concept preserving design DNA.",
        "/collection": "Create a matching Heritage collection: earrings, pendant, ring, bracelet/bangle, necklace.",
    }
    task = next((v for k, v in tasks.items() if lower.startswith(k)), "Answer as Heritage Jewelry Design Director.")
    return openai_text(f"{text}\n\nTask: {task}", image_bytes, image_mime)

def background_job(sender, text, image_bytes, image_mime, message_id):
    try:
        print("BACKGROUND_JOB_START", message_id, sender, text[:100], flush=True)
        lower = text.lower().strip()
        if lower.startswith("/stone"):
            output = stone_edit(image_bytes, image_mime, text)
            wa_image(sender, upload_cloudinary(output), "Heritage stone edit. Manager approval required before customer sharing.")
        elif lower.startswith("/polish"):
            output = polish_edit(image_bytes, image_mime, text)
            wa_image(sender, upload_cloudinary(output), "Heritage polish edit. Manager approval required before customer sharing.")
        elif lower.startswith("/model"):
            outputs = model_edit_multi(image_bytes, image_mime, text)
            for i, output in enumerate(outputs, 1):
                wa_image(sender, upload_cloudinary(output), f"Heritage model visualization option {i}. Manager approval required before customer sharing.")
        else:
            reply = content_command(text, image_bytes, image_mime) + "\n\nManager approval required before customer sharing."
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
    return "Heritage WhatsApp AI Designer V3 backend is running.", 200

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge") or "", 200
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

        text, image_bytes, image_mime = "", None, "image/jpeg"
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
        image_command = lower.startswith("/stone") or lower.startswith("/polish") or lower.startswith("/model")

        if image_bytes and image_command:
            PROCESSING.add(message_id)
            if lower.startswith("/stone"):
                wa_text(sender, "Editing mounted jewelry stones only. Please wait...")
            elif lower.startswith("/polish"):
                wa_text(sender, "Editing metal polish only. Please wait...")
            else:
                wa_text(sender, "Creating Heritage model visualization options. Please wait...")
            threading.Thread(target=background_job, args=(sender, text, image_bytes, image_mime, message_id), daemon=True).start()
            return jsonify({"status": "processing_started"}), 200

        reply = content_command(text, image_bytes, image_mime) + "\n\nManager approval required before customer sharing."
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
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))

