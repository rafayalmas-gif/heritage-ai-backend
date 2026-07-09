import json
from services.openai_service import text_response, HERITAGE_SYSTEM


def analyze_product(image_bytes, image_mime="image/jpeg", user_text=""):
    """
    Heritage AI V9 Product Analyzer
    Returns structured JSON describing the uploaded jewelry.
    """

    schema = {
        "category": "ring|earrings|tops|jhumka|pendant|pendant set|necklace|necklace set|bangle|bracelet|chain|unknown",
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
            "complexity": "",
        },

        "stone_zones": [],

        "drops_bunches": [],
        "pearls": [],
        "white_stones": "",

        "metal": "",
        "scale_estimate": "",
        "wear_position": "",

        "quality": {
            "is_clear": True,
            "issues": []
        },

        "clarification_needed_for_stone": False,
        "stone_question": ""
    }

    instructions = HERITAGE_SYSTEM + """

You are Heritage AI V9 Product Analyzer.

Return ONLY valid JSON.

Your job is to analyze the uploaded jewelry exactly as it appears.

Never redesign.

Never imagine missing details.

Identify:

• category
• confidence
• motif
• workmanship
• pattern family
• polish
• metal tone
• construction
• stone layout
• stone colors
• stone shapes
• stone sizes
• stone count
• pearl layout
• drops
• bunches
• thickness
• scale
• wear position

If image quality is poor:

quality.is_clear = false

List every issue inside quality.issues.

If category is uncertain:

needs_product_type_confirmation = true

If stone edit command may be ambiguous:

clarification_needed_for_stone = true

Return JSON only.

"""

    try:

        raw = text_response(
            "Staff context:\n"
            + str(user_text)
            + "\n\nReturn JSON using this schema:\n"
            + json.dumps(schema, ensure_ascii=False),
            image_bytes=image_bytes,
            image_mime=image_mime,
            instructions=instructions,
            json_mode=True,
        )

        return json.loads(raw)

    except Exception:

        return {
            "category": "unknown",
            "category_confidence": 0.0,
            "needs_product_type_confirmation": True,
            "possible_categories": [
                "ring",
                "earrings",
                "jhumka",
                "pendant",
                "necklace",
                "bangle",
                "bracelet",
            ],
            "design_dna": {},
            "stone_zones": [],
            "drops_bunches": [],
            "pearls": [],
            "quality": {
                "is_clear": False,
                "issues": ["analysis failed"]
            },
            "clarification_needed_for_stone": False,
            "stone_question": ""
        }


def format_analysis(a):

    dna = a.get("design_dna", {}) or {}

    lines = [
        "Heritage Analysis",
        "",
        f"Category: {a.get('category','unknown')}",
        f"Confidence: {int(float(a.get('category_confidence',0))*100)}%",
        f"Scale: {a.get('scale_estimate','')}",
        f"Wear Position: {a.get('wear_position','')}",
        "",
        "Design DNA",
        f"- Pattern: {', '.join(dna.get('pattern_family',[]) or [])}",
        f"- Workmanship: {', '.join(dna.get('workmanship',[]) or [])}",
        f"- Polish: {dna.get('polish','')}",
        f"- Thickness: {dna.get('thickness','')}",
        "",
        "Stone Zones",
    ]

    zones = a.get("stone_zones", [])

    if zones:

        for z in zones:

            lines.append(
                f"- {z.get('zone','')} | "
                f"{z.get('count','')} | "
                f"{z.get('color','')} | "
                f"{z.get('shape','')} | "
                f"{z.get('size','')}"
            )

    else:

        lines.append("- No colored stone zones detected.")

    return "\n".join(lines)[:4000]
