import json
from services.analyzer import analyze_product
from services.openai_service import image_edit

STONE_PROFILES = {
    "ruby": ("deep pigeon-blood ruby red gemstone", False),
    "red": ("deep pigeon-blood ruby red gemstone", False),
    "laal": ("deep pigeon-blood ruby red gemstone", False),
    "emerald": ("deep premium Colombian emerald green gemstone", False),
    "green": ("deep premium Colombian emerald green gemstone", False),
    "panna": ("deep premium Colombian emerald green gemstone", False),
    "zamarud": ("deep premium Colombian emerald green gemstone", False),
    "sapphire": ("royal dark blue Kashmir sapphire gemstone", False),
    "blue sapphire": ("royal dark blue Kashmir sapphire gemstone", False),
    "blue": ("royal dark blue Kashmir sapphire gemstone", False),
    "neelam": ("royal dark blue Kashmir sapphire gemstone", False),
    "yellow sapphire": ("rich golden yellow pukhraj sapphire gemstone", False),
    "yellow": ("rich golden yellow pukhraj sapphire gemstone", False),
    "pukhraj": ("rich golden yellow pukhraj sapphire gemstone", False),
    "amethyst": ("deep royal purple amethyst gemstone", False),
    "falsa": ("dark falsa blackberry-purple gemstone", False),
    "topaz": ("Swiss blue topaz gemstone", False),
    "champagne": ("warm champagne golden-brown gemstone", False),
    "garnet": ("deep wine-red garnet gemstone", False),
    "turquoise": ("natural turquoise blue-green gemstone", False),
    "onyx": ("deep black onyx gemstone", False),
    "pink": ("rich pink sapphire gemstone", False),
    "pearl": ("smooth white pearl with natural pearl luster", True),
    "white pearl": ("smooth white pearl with natural pearl luster", True),
    "grey pearl": ("smooth grey pearl with natural pearl luster", True),
    "gray pearl": ("smooth grey pearl with natural pearl luster", True),
    "pink pearl": ("smooth pink pearl with natural pearl luster", True),
    "black pearl": ("smooth black pearl with natural pearl luster", True),
}

def requested_stone(text):
    t = (text or "").lower()
    for k in sorted(STONE_PROFILES, key=len, reverse=True):
        if k in t:
            return k, STONE_PROFILES[k][0], STONE_PROFILES[k][1]
    return "ruby", STONE_PROFILES["ruby"][0], False

def has_scope(text):
    t = (text or "").lower()
    return any(w in t for w in ["main", "center", "centre", "big", "large", "all", "side", "accent", "drop", "drops", "bunch", "bunches", "pearl", "pearls", "only", "sab", "saray"])

def clarification_text(analysis):
    choices = [
        ("main", "Main / large center stones only"),
        ("all_colored", "All colored stones"),
        ("main_side", "Main + side colored stones"),
    ]
    if analysis.get("drops_bunches"):
        choices += [("drops", "Drops / hanging stones only"), ("main_drops", "Main stones + drops")]
    if analysis.get("pearls"):
        choices.append(("pearls", "Pearls only"))
    choices.append(("custom", "Custom instruction"))
    lines = ["I detected multiple stone zones.", "", "Please choose what to change:"]
    for i, (_, label) in enumerate(choices, 1):
        lines.append(f"{i}. {label}")
    lines += ["", "Reply with number, for example: 1"]
    return "\n".join(lines), choices

def stone_edit(image_bytes, image_mime, text):
    _, profile, _ = requested_stone(text)
    analysis = analyze_product(image_bytes, image_mime, text)
    lock = json.dumps(analysis, ensure_ascii=False, indent=2)
    prompt = f"""Edit this jewelry photo for Heritage Jewellers.

TASK: Change ONLY selected mounted gemstone zones to {profile}.

PRODUCT LOCK:
{lock}

ABSOLUTE RULES:
- Do NOT redesign jewelry.
- Do NOT change category, outline, motif, jaali, filigree, leaf, floral, paisley, kundan/jadau work.
- Do NOT change prong count, prong position, prong thickness, bezels, hooks, bail, chain, lock or clasp.
- Do NOT enlarge or shrink stones.
- Preserve exact stone shape, cut, orientation, count, size and position.
- Preserve diamonds/zircon/CZ/white halo stones unless explicitly requested.
- Preserve pearls/drops/bunches unless explicitly requested.
- Preserve skin, hand, ear, neck, model, dummy, chair, shop, showcase, tag, box, tray, floor and background.
- Use realistic faceted gemstone material with deep luxury tone, not painted color.
- If SCOPE_SELECTED is present: main=main/large only; all_colored=all colored gems; main_side=main+side colored; drops=hanging drops; main_drops=main+drops; pearls=pearls only.
Return only edited image."""
    return image_edit(image_bytes, prompt)
