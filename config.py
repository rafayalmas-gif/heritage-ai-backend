import os

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "heritage_verify_123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")

STAFF_NUMBERS = [
    x.strip().replace("+", "").replace(" ", "")
    for x in os.getenv("STAFF_NUMBERS", "").split(",")
    if x.strip()
]

HERITAGE_SITE = os.getenv("HERITAGE_SITE", "https://heritagejewels.com.pk").rstrip("/")
CATALOG_REFRESH_SECONDS = int(os.getenv("CATALOG_REFRESH_SECONDS", "21600"))
MAX_CATALOG_PRODUCTS = int(os.getenv("MAX_CATALOG_PRODUCTS", "400"))
SIMILAR_PAGE_SIZE = int(os.getenv("SIMILAR_PAGE_SIZE", "5"))

LOG_FILE = os.getenv("LOG_FILE", "logs/heritage.log")
CATALOG_FILE = os.getenv("CATALOG_FILE", "cache/heritage_catalog.json")
SESSION_FILE = os.getenv("SESSION_FILE", "cache/sessions.json")
