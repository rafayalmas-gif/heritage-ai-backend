import json
from services.analyzer import analyze_product
from services.openai_service import image_edit

def model_outputs(image_bytes, image_mime, text):
    analysis = analyze_product(image_bytes, image_mime, text)
    lock = json.dumps(analysis, ensure_ascii=False, indent=2)
    count = 3 if any(x in text.lower() for x in ["3", "three", "options"]) else 2

    base = f"""Create a customer-shareable Heritage Jewellers model visualization.

UPLOADED JEWELRY IS THE MASTER REFERENCE.

DESIGN LOCK:
{lock}

ABSOLUTE PRODUCT PRESERVATION:
- Use the exact uploaded jewelry product only.
- Do NOT redesign, simplify, mirror, change motifs, open spaces, jaali/filigree scrollwork, leaf pattern, floral pattern, stone count, stone shape, stone size, stone color, pearl count, drop count, prongs, metal polish, chain, bail, clasp, hook or lock.
- Preserve real-world scale. Do not exaggerate size.
- If ring: one finger only, never span two fingers.
- If pendant: show as pendant on chain.
- If earrings: show on ear.
- If necklace: preserve full necklace/strand count.
- If bangle/bracelet: show on wrist and preserve width/thickness/repeating pattern.
- Pakistani/South Asian model.
- Modest Pakistani/South Asian formal attire only.
- No deep neckline, no revealing styling.
- Jewelry is hero.
- No text/logo/watermark."""

    prompts = [
        base + "\nVIEW 1: Close-up wearing view. Entire jewelry visible.",
        base + "\nVIEW 2: Slightly wider modest styled model portrait."
    ]
    if count >= 3:
        prompts.append(base + "\nVIEW 3: Luxury campaign/banner angle, modest formal styling.")
    return [image_edit(image_bytes, p) for p in prompts]
