import time, base64
from config import SESSION_FILE
from services.utils import load_json, save_json

SESSIONS = load_json(SESSION_FILE, {})

def save():
    save_json(SESSION_FILE, SESSIONS)

def set_session(sender, data):
    data["created"] = time.time()
    SESSIONS[sender] = data
    save()

def get_session(sender):
    return SESSIONS.get(sender)

def clear_session(sender):
    if sender in SESSIONS:
        del SESSIONS[sender]
        save()

def encode_image(b):
    return base64.b64encode(b).decode("utf-8")

def decode_image(s):
    return base64.b64decode(s)
