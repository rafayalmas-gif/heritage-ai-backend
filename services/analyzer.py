import json
from services.openai_service import text_response, HERITAGE_SYSTEM

def analyze_product(image_bytes, image_mime="image/jpeg", user_text=""):
    schema = {
        "category": "ring|earrings|tops|pendant|pendant set|necklace set|bangle|bracelet|chain|unknown",
        "category_confidence": 0.0,
        "needs_product_type_confirmation": False,
        "possible_categories": [],
        "design_dna": {
            "pattern_family": [],
            "motif_structure": [],
            "workmanship": [],
            "repeat_pattern": "",
            "polish": "",
            "stone_style": "",
            "stone_colors": [],
            "thickness": "",
            "construction": "",
            "complexity": ""
        },
        "stone_zones": [],
        "drops_bunches": [],
        "pearls": [],
        "white_stones": "",
        "metal": "",
        "scale_estimate": "",
        "wear_position": "",
        "quality": {"is_clear": True, "issues": []},
        "clarification_needed_for_stone": False,
        "stone_question": ""
    }
    instructions = HERITAGE_SYSTEM + """
You are a strict jewelry product analyzer. Return ONLY valid JSON.
Do not invent colored stones if none are visible.
Identify visual DNA: kaam/workmanship, leaf/floral/paisley/jaali, Ganga Jamni polish, zircon work, thickness, construction.
For stone commands, identify main stones, side stones, drops, bunches, pearls, and white stones separately.
If product category confidence is low, set needs_product_type_confirmation=true.
"""
    try:
        raw = text_response(
            "Staff context: " + str(user_text) + "\nReturn JSON using this schema:\n" + json.dumps(schema),
            image_bytes, image_mime, instructions, json_mode=True
        )
        return json.loads(raw)
    except Exception:
        return {
            "category": "unknown",
            "category_confidence": 0,
            "needs_product_type_confirmation": True,
            "possible_categories": ["ring", "pendant", "earrings", "necklace set", "bangle", "bracelet"],
            "design_dna": {},
            "stone_zones": [],
            "clarification_needed_for_stone": False,
            "quality": {"is_clear": False, "issues": ["analysis failed"]}
        }

def format_analysis(a):
    dna = a.get("design_dna", {}) or {}
    lines = [
        "Heritage Analysis",
        "",
        f"Category: {a.get('category','unknown')} ({int(float(a.get('category_confidence',0))*100)}%)",
        f"Scale: {a.get('scale_estimate','')}",
        f"Wear Position: {a.get('wear_position','')}",
        "",
        "Design DNA:",
        f"- Pattern: {', '.join(dna.get('pattern_family',[]) or [])}",
        f"- Workmanship: {', '.join(dna.get('workmanship',[]) or [])}",
        f"- Polish: {dna.get('polish','')}",
        f"- Thickness: {dna.get('thickness','')}",
        "",
        "Stone Zones:",
    ]
    zones = a.get("stone_zones", []) or []
    if zones:
        for z in zones:
            lines.append(f"- {z.get('zone')}: {z.get('count')} {z.get('color')} {z.get('shape')} {z.get('size')}")
    else:
        lines.append("- No clear colored stone zones detected.")
    return "\n".join(lines)[:4000]
