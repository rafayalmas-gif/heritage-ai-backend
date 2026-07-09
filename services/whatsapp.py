import requests
from config import WHATSAPP_TOKEN, WHATSAPP_PHONE_ID

TOKEN = (WHATSAPP_TOKEN or "").strip()
PHONE_ID = (WHATSAPP_PHONE_ID or "").strip()


def _headers():
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }


def send_text(to, body):
    url = f"https://graph.facebook.com/v20.0/{PHONE_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": str(body)[:4096]},
    }
    r = requests.post(url, headers=_headers(), json=payload, timeout=30)
    print("WA_TEXT", r.status_code, r.text[:400], flush=True)
    return r


def send_image(to, image_url, caption=""):
    url = f"https://graph.facebook.com/v20.0/{PHONE_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"link": image_url, "caption": str(caption)[:1024]},
    }
    r = requests.post(url, headers=_headers(), json=payload, timeout=30)
    print("WA_IMAGE", r.status_code, r.text[:400], flush=True)
    return r


def get_media_url(media_id):
    media_id = str(media_id).strip()
    url = f"https://graph.facebook.com/v20.0/{media_id}"

    r = requests.get(
        url,
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=30,
    )

    print("WA_GET_MEDIA_URL", r.status_code, r.text[:400], flush=True)
    r.raise_for_status()

    return r.json().get("url")


def download_media(media_url):
    r = requests.get(
        media_url,
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=90,
    )

    print("WA_DOWNLOAD_MEDIA", r.status_code, r.headers.get("Content-Type"), flush=True)
    r.raise_for_status()

    return r.content, r.headers.get("Content-Type", "image/jpeg")
