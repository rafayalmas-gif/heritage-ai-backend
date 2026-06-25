import json
from services.analyzer import analyze_product
from services.openai_service import image_edit

def requested_polish(text):
    t = (text or "").lower()
    if "white" in t:
        return "white gold polish, cool bright luxury white metal"
    if "rose" in t:
        return "rose gold polish, warm pink luxury metal"
    if "silver" in t:
        return "silver polish, bright cool silver tone"
    if "ganga" in t or "jamni" in t:
        return "Ganga Jamni two-tone polish: yellow gold plus white polish"
    return "yellow gold polish, rich warm yellow gold tone"

def polish_edit(image_bytes, image_mime, text):
    polish = requested_polish(text)
    analysis = analyze_product(image_bytes, image_mime, text)
    prompt = f"""Edit this jewelry photo for Heritage Jewellers.

TASK: Change ONLY metal polish to {polish}.

PRODUCT LOCK:
{json.dumps(analysis, ensure_ascii=False, indent=2)}

RULES:
- Edit metal only.
- Do not edit gemstones, pearls, diamonds, zircons, CZ, moissanite, skin, hand, background.
- Preserve design, motif, prongs, chain, bail, clasp, lock, stone count, stone color and camera angle.
Return only edited image."""
    return image_edit(image_bytes, prompt)
