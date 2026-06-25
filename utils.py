import json, os, re
from datetime import datetime, timezone

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def normalize_phone(n):
    return str(n or "").replace("+", "").replace(" ", "").strip()

def clean_text(x):
    return re.sub(r"\s+", " ", str(x or "")).strip()

def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default

def save_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def log_event(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data.setdefault("time", now_iso())
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")
