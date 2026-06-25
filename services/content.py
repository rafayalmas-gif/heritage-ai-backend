from services.openai_service import text_response

def content_command(text, image_bytes=None, image_mime="image/jpeg"):
    lower = (text or "").lower()
    tasks = {
        "/caption": "Write premium Instagram caption, short version, long version and hashtags.",
        "/product": "Write website title, short description, full description, styling notes and SEO keywords.",
        "/cad": "Write CAD/manufacturing brief with setting, construction, stone placement, comfort and production notes.",
        "/bridal": "Create Heritage bridal version concept preserving design DNA.",
        "/collection": "Create matching Heritage collection: earrings, pendant, ring, bracelet/bangle, necklace.",
    }
    task = next((v for k, v in tasks.items() if lower.startswith(k)), "Answer as Heritage Jewelry Design Director.")
    return text_response(f"Staff message: {text}\nTask: {task}", image_bytes, image_mime)
