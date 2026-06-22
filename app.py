import os, json, base64, requests, threading, math
from io import BytesIO
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from openai import OpenAI
from PIL import Image, ImageFilter
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
Expert in Pakistani, South Asian, Mughal, bridal, kundan, meenakari,
moissanite, lab diamond, emerald, ruby, sapphire and pearl jewelry.
Never create generic Western minimalist jewelry.
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


# =========================
# HERITAGE STONE EDIT ENGINE
# =========================

def target_hue(text):
    t = (text or "").lower()
    if "blue" in t or "sapphire" in t:
        return 158
    if "green" in t or "emerald" in t:
        return 88
    if "pink" in t or "morganite" in t:
        return 232
    if "black" in t or "onyx" in t:
        return "black"
    if "white" in t or "pearl" in t:
        return "white"
    return 0


def is_skin_pixel(r, g, b):
    if r > 80 and g > 35 and b > 20 and r > g and g >= b:
        if (r - g) < 100 and (g - b) < 90:
            return True
    return False


def is_white_background(r, g, b):
    return r > 220 and g > 220 and b > 220


def is_grey_background(r, g, b):
    return abs(r - g) < 14 and abs(g - b) < 14 and r > 165


def is_background_pixel(r, g, b):
    return is_white_background(r, g, b) or is_grey_background(r, g, b)


def is_gold_pixel(r, g, b):
    return r > 115 and g > 70 and b < 105 and r > b * 1.25 and g > b * 0.9


def is_diamond_pixel(r, g, b):
    mx = max(r, g, b)
    mn = min(r, g, b)
    return mx > 135 and (mx - mn) < 55


def is_metal_or_diamond_pixel(r, g, b):
    return is_gold_pixel(r, g, b) or is_diamond_pixel(r, g, b)


def is_probable_colored_stone(r, g, b, text):
    if is_skin_pixel(r, g, b):
        return False
    if is_background_pixel(r, g, b):
        return False
    if is_metal_or_diamond_pixel(r, g, b):
        return False

    mx = max(r, g, b)
    mn = min(r, g, b)
    chroma = mx - mn

    if chroma < 38 or mx < 45:
        return False

    green = g > r * 0.70 and g > b * 1.00 and g > 50
    red = r > g * 1.15 and r > b * 1.05 and r > 75 and g < 175
    pink = r > 105 and b > 60 and r > g * 1.10 and b > g * 0.85
    blue = b > r * 1.05 and b > g * 1.02 and b > 60

    lower = (text or "").lower()

    if "ruby" in lower or "red" in lower:
        return green or blue or pink

    if "sapphire" in lower or "blue" in lower:
        return green or red or pink

    if "emerald" in lower or "green" in lower:
        return red or pink or blue

    if "pink" in lower or "morganite" in lower:
        return green or red or blue

    return green or red or pink or blue


def build_candidate_mask(rgb, text):
    w, h = rgb.size
    px = rgb.load()
    mask = [[False for _ in range(w)] for _ in range(h)]

    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if is_probable_colored_stone(r, g, b, text):
                mask[y][x] = True

    return mask


def connected_components(mask):
    h = len(mask)
    w = len(mask[0])
    visited = [[False for _ in range(w)] for _ in range(h)]
    comps = []

    for y in range(h):
        for x in range(w):
            if not mask[y][x] or visited[y][x]:
                continue

            stack = [(x, y)]
            visited[y][x] = True
            pts = []

            while stack:
                cx, cy = stack.pop()
                pts.append((cx, cy))

                for nx, ny in ((cx+1, cy), (cx-1, cy), (cx, cy+1), (cx, cy-1)):
                    if 0 <= nx < w and 0 <= ny < h:
                        if mask[ny][nx] and not visited[ny][nx]:
                            visited[ny][nx] = True
                            stack.append((nx, ny))

            comps.append(pts)

    return comps


def component_score(points, w, h):
    area = len(points)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)

    bw = max(1, x2 - x1 + 1)
    bh = max(1, y2 - y1 + 1)

    fill = area / float(bw * bh)
    aspect = max(bw / bh, bh / bw)

    touches_border = x1 <= 2 or y1 <= 2 or x2 >= w - 3 or y2 >= h - 3

    if touches_border:
        return 0

    if area < 25:
        return 0

    if aspect > 6:
        return 0

    if fill < 0.08:
        return 0

    return area


def refined_stone_mask(rgb, text):
    w, h = rgb.size

    max_side = max(w, h)

    if max_side > 900:
        scale = 900 / max_side
        small = rgb.resize((int(w * scale), int(h * scale)))
    else:
        scale = 1.0
        small = rgb

    sw, sh = small.size

    raw_mask = build_candidate_mask(small, text)
    comps = connected_components(raw_mask)

    scored = []
    for c in comps:
        score = component_score(c, sw, sh)
        if score > 0:
            scored.append((score, c))

    scored.sort(reverse=True, key=lambda x: x[0])

    if not scored:
        print("STONE_MASK_COMPONENTS 0", flush=True)
        return [[False for _ in range(w)] for _ in range(h)]

    # Keep strong stone regions only.
    largest = scored[0][0]
    keep = []

    for score, comp in scored:
        if score >= max(25, largest * 0.08):
            keep.extend(comp)

    small_mask_img = Image.new("L", (sw, sh), 0)
    spx = small_mask_img.load()

    for x, y in keep:
        spx[x, y] = 255

    # Smooth mask slightly.
    small_mask_img = small_mask_img.filter(ImageFilter.MaxFilter(3))
    small_mask_img = small_mask_img.filter(ImageFilter.MinFilter(3))
    small_mask_img = small_mask_img.filter(ImageFilter.GaussianBlur(0.8))

    if scale != 1.0:
        mask_img = small_mask_img.resize((w, h))
    else:
        mask_img = small_mask_img

    mask_px = mask_img.load()
    final_mask = [[False for _ in range(w)] for _ in range(h)]

    for y in range(h):
        for x in range(w):
            final_mask[y][x] = mask_px[x, y] > 80

    print("STONE_MASK_COMPONENTS", len(scored), "KEPT_PIXELS", len(keep), flush=True)
    return final_mask


def recolor_hsv_pixel(h, s, v, target):
    # Preserve gemstone depth, highlights, and shadows.
    # Do not force full saturation; this avoids painted look.
    if target == "black":
        return h, int(s * 0.35), int(v * 0.28)

    if target == "white":
        return h, 18, min(255, int(v * 1.25))

    new_h = target
    new_s = min(255, max(70, int(s * 0.92)))
    new_v = min(255, max(20, int(v * 1.00)))

    # Preserve bright facet reflections.
    if v > 210:
        new_s = int(new_s * 0.55)

    # Preserve deep gemstone shadow.
    if v < 75:
        new_s = int(new_s * 0.85)
        new_v = int(v * 0.92)

    return new_h, new_s, new_v


def exact_stone_colour_change(image_bytes, text):
    img = Image.open(BytesIO(image_bytes)).convert("RGBA")

    max_side = 1400
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side))

    rgb = img.convert("RGB")
    hsv = rgb.convert("HSV")
    alpha = img.getchannel("A")

    w, h = rgb.size

    mask = refined_stone_mask(rgb, text)

    hsv_pixels = list(hsv.getdata())
    target = target_hue(text)

    new_pixels = []
    changed = 0

    for idx, (hh, s, v) in enumerate(hsv_pixels):
        x = idx % w
        y = idx // w

        if mask[y][x]:
            changed += 1
            new_pixels.append(recolor_hsv_pixel(hh, s, v, target))
        else:
            new_pixels.append((hh, s, v))

    print("STONE_PIXELS_CHANGED_FINAL", changed, flush=True)

    hsv.putdata(new_pixels)
    result_rgb = hsv.convert("RGB")
    result = Image.merge("RGBA", (*result_rgb.split(), alpha))

    result = result.filter(ImageFilter.SHARPEN)

    return pil_to_png_bytes(result)


# =========================
# OPENAI
# =========================

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

Use uploaded jewelry image as the main product reference.

Important:
- Keep jewelry style close to uploaded product.
- Keep stone colour.
- Keep metal colour.
- Jewelry must remain hero.
- Luxury bridal / party-wear styling.
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

    return base64.b64decode(result.data[0].b64_json)


def background_job(sender, text, image_bytes, image_mime, message_id):
    try:
        print("BACKGROUND_JOB_START", message_id, sender, text[:100], flush=True)
        lower = text.lower().strip()

        if lower.startswith("/stone"):
            output = exact_stone_colour_change(image_bytes, text)
            url = upload_cloudinary(output)
            wa_image(sender, url, "Exact jewelry-stone colour edit. Manager approval required before customer sharing.")

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
                wa_text(sender, "Editing only gemstone areas while preserving jewelry design, skin and background. Please wait...")
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
