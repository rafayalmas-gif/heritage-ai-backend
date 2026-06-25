import base64, threading, time, traceback
from flask import Flask, request, jsonify

from config import VERIFY_TOKEN, STAFF_NUMBERS, LOG_FILE, CATALOG_REFRESH_SECONDS
from services.utils import normalize_phone, log_event
from services.whatsapp import send_text, send_image, get_media_url, download_media
from services.openai_service import friendly_error
from services.analyzer import analyze_product, format_analysis
from services.stone import stone_edit, has_scope, clarification_text
from services.polish import polish_edit
from services.model import model_outputs
from services.similarity import similar_search, send_similar_page
from services.catalog import build_catalog
from services.content import content_command
from services.media import upload_image
from services.sessions import set_session, get_session, clear_session, encode_image, decode_image

app = Flask(__name__)
PROCESSED = set()
PROCESSING = set()

def background_job(sender, text, image_bytes, image_mime, message_id):
    try:
        lower = text.lower().strip()

        if lower.startswith("/analyze"):
            send_text(sender, format_analysis(analyze_product(image_bytes, image_mime, text)) + "\n\nManager approval required before customer sharing.")

        elif lower.startswith("/stone"):
            analysis = analyze_product(image_bytes, image_mime, text)
            if analysis.get("clarification_needed_for_stone") and not has_scope(text):
                q, choices = clarification_text(analysis)
                set_session(sender, {
                    "type": "stone_clarification",
                    "text": text,
                    "image_b64": encode_image(image_bytes),
                    "image_mime": image_mime,
                    "choices": choices,
                })
                send_text(sender, q)
            else:
                out = stone_edit(image_bytes, image_mime, text)
                send_image(sender, upload_image(out), "Heritage stone edit. Manager approval required before customer sharing.")

        elif lower.startswith("/polish"):
            out = polish_edit(image_bytes, image_mime, text)
            send_image(sender, upload_image(out), "Heritage polish edit. Manager approval required before customer sharing.")

        elif lower.startswith("/model"):
            analysis = analyze_product(image_bytes, image_mime, text)
            if analysis.get("needs_product_type_confirmation") or float(analysis.get("category_confidence") or 0) < 0.70:
                possible = analysis.get("possible_categories") or ["pendant", "ring", "earrings", "necklace set", "bangle", "bracelet"]
                set_session(sender, {
                    "type": "model_category_confirmation",
                    "text": text,
                    "image_b64": encode_image(image_bytes),
                    "image_mime": image_mime,
                    "choices": possible,
                })
                lines = ["I am not fully sure what this product is.", "", "Please confirm:"]
                lines += [f"{i}. {c}" for i, c in enumerate(possible, 1)]
                lines += ["", "Reply with number, for example: 1"]
                send_text(sender, "\n".join(lines))
            else:
                for i, out in enumerate(model_outputs(image_bytes, image_mime, text), 1):
                    send_image(sender, upload_image(out), f"Heritage model visualization option {i}. Manager approval required before customer sharing.")

        elif lower.startswith(("/similar", "/alternatives", "/upsell")):
            similar_search(sender, text, image_bytes, image_mime)

        else:
            send_text(sender, content_command(text, image_bytes, image_mime) + "\n\nManager approval required before customer sharing.")

        PROCESSED.add(message_id)
    except Exception as e:
        print("JOB_ERROR", e, traceback.format_exc(), flush=True)
        send_text(sender, friendly_error(e))
    finally:
        PROCESSING.discard(message_id)

@app.get("/")
def home():
    return "Heritage WhatsApp AI Designer V6 backend is running.", 200

@app.get("/webhook")
def verify_webhook():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge") or "", 200
    return "Verification failed", 403

@app.post("/webhook")
def receive_webhook():
    payload = request.get_json(silent=True) or {}
    log_event(LOG_FILE, {"type": "webhook", "payload": payload})

    try:
        value = payload.get("entry", [])[0].get("changes", [])[0].get("value", {})
        if "statuses" in value:
            return jsonify({"status": "status_update"}), 200

        messages = value.get("messages", [])
        if not messages:
            return jsonify({"status": "ignored"}), 200

        msg = messages[0]
        message_id = msg.get("id", "")
        sender = msg.get("from")

        if message_id in PROCESSED or message_id in PROCESSING:
            return jsonify({"status": "duplicate"}), 200

        if STAFF_NUMBERS and normalize_phone(sender) not in STAFF_NUMBERS:
            send_text(sender, "Access denied. This Heritage AI Designer number is staff-only.")
            return jsonify({"status": "blocked"}), 200

        text = ""
        image_bytes = None
        image_mime = "image/jpeg"
        msg_type = msg.get("type")

        if msg_type == "text":
            text = msg.get("text", {}).get("body", "")
        elif msg_type == "image":
            text = msg.get("image", {}).get("caption", "")
            media_id = msg.get("image", {}).get("id")
            if media_id:
                image_bytes, image_mime = download_media(get_media_url(media_id))
        elif msg_type == "video":
            send_text(sender, "Video received. Video frame extraction is planned for V6.2. Please send a clear product photo for now.")
            return jsonify({"status": "video_received"}), 200
        else:
            send_text(sender, "Please send text or image with caption. Example: /stone ruby")
            return jsonify({"status": "unsupported"}), 200

        lower = text.lower().strip()

        # Follow-up flows
        if msg_type == "text" and get_session(sender):
            session = get_session(sender)
            if session.get("type") == "stone_clarification":
                choices = session.get("choices", [])
                if lower.isdigit() and 0 <= int(lower) - 1 < len(choices):
                    scope = choices[int(lower) - 1][0]
                    new_text = session["text"] + f" | SCOPE_SELECTED: {scope}"
                    ib = decode_image(session["image_b64"])
                    im = session["image_mime"]
                    clear_session(sender)
                    PROCESSING.add(message_id)
                    send_text(sender, "Editing selected gemstone areas only. Please wait...")
                    threading.Thread(target=background_job, args=(sender, new_text, ib, im, message_id), daemon=True).start()
                    return jsonify({"status": "stone_followup"}), 200
                send_text(sender, "Please reply with a valid option number.")
                return jsonify({"status": "clarification_retry"}), 200

            if session.get("type") == "model_category_confirmation":
                choices = session.get("choices", [])
                if lower.isdigit() and 0 <= int(lower) - 1 < len(choices):
                    product_type = choices[int(lower) - 1]
                    new_text = session["text"] + f" | CONFIRMED_PRODUCT_TYPE: {product_type}"
                    ib = decode_image(session["image_b64"])
                    im = session["image_mime"]
                    clear_session(sender)
                    PROCESSING.add(message_id)
                    send_text(sender, "Creating Heritage model visualization using confirmed product type. Please wait...")
                    threading.Thread(target=background_job, args=(sender, new_text, ib, im, message_id), daemon=True).start()
                    return jsonify({"status": "model_followup"}), 200
                send_text(sender, "Please reply with a valid option number.")
                return jsonify({"status": "category_retry"}), 200

        if lower in ["/more", "more"]:
            send_similar_page(sender)
            PROCESSED.add(message_id)
            return jsonify({"status": "more_sent"}), 200

        if lower.startswith("/refreshcatalog"):
            send_text(sender, "Refreshing Heritage website catalog. This may take a few minutes...")
            def refresh():
                try:
                    data = build_catalog(True)
                    send_text(sender, f"Catalog refreshed. Products indexed: {data.get('count',0)}")
                except Exception as e:
                    send_text(sender, friendly_error(e))
            threading.Thread(target=refresh, daemon=True).start()
            PROCESSED.add(message_id)
            return jsonify({"status": "refresh_started"}), 200

        image_command = lower.startswith(("/stone", "/polish", "/model", "/similar", "/alternatives", "/upsell", "/analyze"))
        if image_command and not image_bytes:
            send_text(sender, "Please send a product image with this command.")
            return jsonify({"status": "image_required"}), 200

        if image_bytes and image_command:
            PROCESSING.add(message_id)
            if lower.startswith("/similar"):
                send_text(sender, "Searching Heritage website for visually similar products. Please wait...")
            elif lower.startswith("/analyze"):
                send_text(sender, "Analyzing Heritage product DNA. Please wait...")
            elif lower.startswith("/stone"):
                send_text(sender, "Analyzing stone zones first. Please wait...")
            elif lower.startswith("/model"):
                send_text(sender, "Creating Heritage model visualization options. Please wait...")
            elif lower.startswith("/polish"):
                send_text(sender, "Editing metal polish only. Please wait...")
            threading.Thread(target=background_job, args=(sender, text, image_bytes, image_mime, message_id), daemon=True).start()
            return jsonify({"status": "processing_started"}), 200

        send_text(sender, content_command(text or "Help") + "\n\nManager approval required before customer sharing.")
        PROCESSED.add(message_id)
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print("WEBHOOK_ERROR", e, traceback.format_exc(), flush=True)
        try:
            send_text(payload["entry"][0]["changes"][0]["value"]["messages"][0]["from"], friendly_error(e))
        except Exception:
            pass
        return jsonify({"status": "error"}), 200

def catalog_loop():
    while True:
        try:
            build_catalog(False)
        except Exception as e:
            print("CATALOG_LOOP_ERROR", e, flush=True)
        time.sleep(CATALOG_REFRESH_SECONDS)

threading.Thread(target=catalog_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

