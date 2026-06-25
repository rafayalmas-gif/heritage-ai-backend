import requests
from config import WHATSAPP_TOKEN, WHATSAPP_PHONE_ID

def send_text(to, body):
    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": str(body)[:4096]},
    }
    r = requests.post(url, headers={
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }, json=payload, timeout=30)
    print("WA_TEXT", r.status_code, r.text[:400], flush=True)
    return r

def send_image(to, image_url, caption=""):
    url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"link": image_url, "caption": str(caption)[:1024]},
    }
    r = requests.post(url, headers={
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }, json=payload, timeout=30)
    print("WA_IMAGE", r.status_code, r.text[:400], flush=True)
    return r

def get_media_url(media_id):
    r = requests.get(
        f"https://graph.facebook.com/v20.0/{media_id}",
        headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("url")

def download_media(media_url):
    r = requests.get(media_url, headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}, timeout=90)
    r.raise_for_status()
    return r.content, r.headers.get("Content-Type", "image/jpeg")
