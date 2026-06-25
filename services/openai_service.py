import base64
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_IMAGE_MODEL
from services.media import prepare_png

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

HERITAGE_SYSTEM = """You are Heritage Jewelry Design Director for Heritage Jewellers.
Expert in Pakistani, South Asian, Mughal-inspired, bridal, kundan, jadau, meenakari,
gold, silver, moissanite, lab diamond, emerald, ruby, sapphire, pearl and colored-stone jewelry.
Never create generic Western minimalist jewelry. Manager approval required before customer sharing."""

def text_response(text, image_bytes=None, image_mime="image/jpeg", instructions=HERITAGE_SYSTEM, json_mode=False):
    if not client:
        raise RuntimeError("OPENAI_API_KEY is missing.")
    content = [{"type": "input_text", "text": text}]
    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        content.append({"type": "input_image", "image_url": f"data:{image_mime};base64,{b64}"})
    kwargs = {
        "model": OPENAI_MODEL,
        "instructions": instructions,
        "input": [{"role": "user", "content": content}],
    }
    if json_mode:
        kwargs["text"] = {"format": {"type": "json_object"}}
    return client.responses.create(**kwargs).output_text

def image_edit(image_bytes, prompt):
    if not client:
        raise RuntimeError("OPENAI_API_KEY is missing.")
    result = client.images.edit(
        model=OPENAI_IMAGE_MODEL,
        image=prepare_png(image_bytes),
        prompt=prompt,
        size="1024x1024",
        n=1,
    )
    return base64.b64decode(result.data[0].b64_json)

def friendly_error(exc):
    s = str(exc)
    if "insufficient_quota" in s or "exceeded your current quota" in s:
        return "⚠ Heritage AI is temporarily unavailable because OpenAI quota/billing limit has been reached. Please contact admin."
    if "429" in s or "rate_limit" in s:
        return "⚠ Heritage AI is busy/rate-limited. Please try again shortly."
    return "Sorry, Heritage AI had an error: " + s[:700]
