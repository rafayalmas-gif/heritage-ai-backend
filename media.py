from io import BytesIO
from PIL import Image
import cloudinary, cloudinary.uploader
import requests
from config import CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True,
)

def prepare_png(image_bytes, max_side=1600):
    img = Image.open(BytesIO(image_bytes)).convert("RGBA")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
    out = BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    out.name = "heritage_input.png"
    return out

def upload_image(image_bytes, folder="heritage-ai"):
    result = cloudinary.uploader.upload(BytesIO(image_bytes), resource_type="image", folder=folder)
    return result["secure_url"]

def download_public_image(url):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 HeritageAI"}, timeout=30)
        if r.status_code == 200 and len(r.content) > 1000:
            return r.content
    except Exception:
        pass
    return None

def cache_public_image(url):
    b = download_public_image(url)
    if not b:
        return None
    return upload_image(b, "heritage-product-cache")
