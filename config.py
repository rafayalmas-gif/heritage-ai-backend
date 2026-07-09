import os

# ==============================
# WHATSAPP / META CONFIG
# ==============================

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "heritage_verify_123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")

# ==============================
# OPENAI CONFIG
# ==============================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")

# ==============================
# CLOUDINARY CONFIG
# ==============================

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")

# ==============================
# STAFF CONFIG
# ==============================

STAFF_NUMBERS = [
    x.strip().replace("+", "").replace(" ", "")
    for x in os.getenv("STAFF_NUMBERS", "").split(",")
    if x.strip()
]

# ==============================
# HERITAGE WEBSITE / CATALOG
# ==============================

HERITAGE_SITE = os.getenv("HERITAGE_SITE", "https://heritagejewels.com.pk").rstrip("/")
CATALOG_REFRESH_SECONDS = int(os.getenv("CATALOG_REFRESH_SECONDS", "21600"))
MAX_CATALOG_PRODUCTS = int(os.getenv("MAX_CATALOG_PRODUCTS", "600"))
SIMILAR_PAGE_SIZE = int(os.getenv("SIMILAR_PAGE_SIZE", "5"))

# ==============================
# FILE PATHS
# ==============================

LOG_FILE = os.getenv("LOG_FILE", "logs/heritage.log")
CATALOG_FILE = os.getenv("CATALOG_FILE", "cache/heritage_catalog_v9.json")
SESSION_FILE = os.getenv("SESSION_FILE", "cache/sessions_v9.json")

# ==============================
# EXACT PRODUCT PRESERVATION MODE
# ==============================

EXACT_PRODUCT_MODE = True

MIN_MODEL_CONFIDENCE = int(os.getenv("MIN_MODEL_CONFIDENCE", "98"))
MODEL_SIMILARITY_THRESHOLD = int(os.getenv("MODEL_SIMILARITY_THRESHOLD", "97"))
MODEL_MAX_RETRIES = int(os.getenv("MODEL_MAX_RETRIES", "3"))

# ==============================
# VALIDATION / SCORING
# ==============================

VALIDATION_ENABLED = True
VALIDATION_PLACEHOLDER_MODE = True

MIN_GEOMETRY_SCORE = int(os.getenv("MIN_GEOMETRY_SCORE", "95"))
MIN_STONE_LAYOUT_SCORE = int(os.getenv("MIN_STONE_LAYOUT_SCORE", "95"))
MIN_MOTIF_SCORE = int(os.getenv("MIN_MOTIF_SCORE", "95"))
MIN_PEARL_LAYOUT_SCORE = int(os.getenv("MIN_PEARL_LAYOUT_SCORE", "95"))
MIN_OVERALL_PRESERVATION_SCORE = int(os.getenv("MIN_OVERALL_PRESERVATION_SCORE", "97"))

# ==============================
# LOCKED JEWELRY COMPONENTS
# ==============================

LOCK_GEOMETRY = True
LOCK_MOTIFS = True
LOCK_STONES = True
LOCK_PEARLS = True
LOCK_PRONGS = True
LOCK_METAL = True
LOCK_POLISH = True
LOCK_CHAINS = True
LOCK_CONNECTORS = True
LOCK_FILIGREE = True
LOCK_KUNDAN = True
LOCK_MEENAKARI = True
LOCK_JAALI = True
LOCK_GEMSTONE_LAYOUT = True
LOCK_PEARL_LAYOUT = True
LOCK_STONE_COUNT = True
LOCK_STONE_SHAPE = True
LOCK_STONE_SIZE = True
LOCK_STONE_POSITION = True

# ==============================
# ALLOWED CHANGES IN /model
# ==============================

ALLOW_MODEL_CHANGE = True
ALLOW_BACKGROUND_CHANGE = True
ALLOW_LIGHTING_CHANGE = True
ALLOW_SHADOW_CHANGE = True
ALLOW_CAMERA_ANGLE_CHANGE = True
ALLOW_CLOTHING_CHANGE = True
ALLOW_SKIN_RENDERING = True
ALLOW_STONE_SPARKLE_ENHANCEMENT = True
ALLOW_STONE_REFLECTION_ENHANCEMENT = True

# ==============================
# FORBIDDEN CHANGES IN /model
# ==============================

ALLOW_JEWELRY_REDESIGN = False
ALLOW_MOTIF_CHANGE = False
ALLOW_STONE_POSITION_CHANGE = False
ALLOW_STONE_COUNT_CHANGE = False
ALLOW_STONE_SHAPE_CHANGE = False
ALLOW_STONE_SIZE_CHANGE = False
ALLOW_PEARL_POSITION_CHANGE = False
ALLOW_PEARL_COUNT_CHANGE = False
ALLOW_PROPORTION_CHANGE = False
ALLOW_BAND_WIDTH_CHANGE = False
ALLOW_DOME_CHANGE = False
ALLOW_DROP_COUNT_CHANGE = False
ALLOW_MISSING_DETAIL_INVENTION = False
ALLOW_EXTRA_JEWELRY = False

# ==============================
# LOW QUALITY IMAGE HANDLING
# ==============================

REJECT_LOW_CONFIDENCE_MODEL_IMAGES = True
ASK_CLEARER_IMAGE_ON_LOW_CONFIDENCE = True

LOW_CONFIDENCE_REASONS = [
    "fingers covering jewelry",
    "blurred image",
    "cropped jewelry",
    "screenshot UI visible",
    "heavy reflection",
    "low resolution",
    "missing angle",
    "hidden or unclear design",
    "strong perspective distortion",
]

LOW_CONFIDENCE_REPLY = (
    "This jewelry design is not clear enough for exact product preservation. "
    "Please upload one clearer front image or another angle so I can place the exact same design on a model without changing it."
)

# ==============================
# CUSTOMER SHARING RULE
# ==============================

MANAGER_APPROVAL_TEXT = "Manager approval required before customer sharing."
