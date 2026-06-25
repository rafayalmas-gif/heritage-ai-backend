from config import SIMILAR_PAGE_SIZE
from services.catalog import get_catalog, build_catalog, VISUAL_DNA_KEYWORDS
from services.analyzer import analyze_product
from services.whatsapp import send_text, send_image
from services.media import cache_public_image
from services.sessions import set_session, get_session

CATEGORY_ALIASES = {
    "ring": ["ring", "rings"],
    "earrings": ["earring", "earrings", "tops", "studs"],
    "pendant": ["pendant", "locket"],
    "pendant set": ["pendant set", "locket set"],
    "necklace set": ["necklace set", "necklace", "sets", "haar", "choker"],
    "bangle": ["bangle", "bangles", "kangan", "kada"],
    "bracelet": ["bracelet", "bracelets"],
}

def command_category(text):
    t = (text or "").lower()
    for cat, aliases in CATEGORY_ALIASES.items():
        for a in aliases:
            if a in t:
                return cat
    return None

def cat_match(product_cat, requested, image_cat=None):
    rc = (requested or image_cat or "").lower()
    pc = (product_cat or "").lower()
    if not rc:
        return True
    if rc == "necklace set":
        return pc == "necklace set"
    if rc == "pendant set":
        return pc == "pendant set"
    if rc == "bangle":
        return pc in ["bangle", "bracelet"]
    if rc == "bracelet":
        return pc in ["bracelet", "bangle"]
    if rc == "earrings":
        return pc in ["earrings", "tops"]
    return pc == rc

def analysis_tags(a):
    dna = a.get("design_dna", {}) or {}
    tags = []
    for k in ["pattern_family", "motif_structure", "workmanship", "stone_colors"]:
        v = dna.get(k)
        if isinstance(v, list):
            tags += [str(x).lower() for x in v]
        elif v:
            tags.append(str(v).lower())
    for k in ["repeat_pattern", "polish", "stone_style", "thickness", "construction", "complexity"]:
        if dna.get(k):
            tags.append(str(dna[k]).lower())
    if a.get("category"):
        tags.append(str(a["category"]).lower())
    return sorted(set([x for x in tags if x]))

def score_product(p, analysis, requested=None):
    pcat = p.get("category", "unknown")
    icat = analysis.get("category")
    if requested and not cat_match(pcat, requested, icat):
        return 0, ["Wrong category"]
    if not requested and icat and icat != "unknown" and not cat_match(pcat, icat, icat):
        return 0, ["Wrong category"]

    itags = set(analysis_tags(analysis))
    ptags = set(p.get("tags", []) or [])
    blob = f"{p.get('title','')} {p.get('url','')}".lower()
    for kw in VISUAL_DNA_KEYWORDS:
        if kw in blob:
            ptags.add(kw)

    score = 30
    reasons = [f"same category ({requested or icat or pcat})"]
    overlap = itags.intersection(ptags)
    if overlap:
        score += min(35, 8 * len(overlap))
        reasons.append("matching visual DNA: " + ", ".join(list(overlap)[:5]))

    # bangle-specific DNA boost
    if requested == "bangle" or icat == "bangle" or pcat in ["bangle", "bracelet"]:
        iblob = " ".join(itags)
        if "leaf" in iblob and ("leaf" in ptags or "vine" in ptags):
            score += 15
            reasons.append("similar leaf/vine repeat pattern")
        if "ganga jamni" in iblob and ("ganga jamni" in ptags or "white polish" in ptags):
            score += 8
            reasons.append("similar Ganga Jamni / two-tone finish")
        if "zircon" in iblob and ("zircon" in ptags or "diamond style" in blob):
            score += 8
            reasons.append("similar zircon/diamond-style work")

    if not (p.get("cached_image_url") or p.get("image_url")):
        score -= 25
    return max(0, min(96, int(score))), reasons

def similar_search(sender, text, image_bytes, image_mime):
    requested = command_category(text)
    analysis = analyze_product(image_bytes, image_mime, text)
    if not requested:
        requested = analysis.get("category") if analysis.get("category") != "unknown" else None

    products = get_catalog().get("products", [])
    scored = []
    for p in products:
        s, reasons = score_product(p, analysis, requested)
        if s > 0:
            q = dict(p)
            q["similarity"] = s
            q["reasons"] = reasons
            scored.append(q)

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    set_session(sender, {
        "type": "similar_results",
        "query": text,
        "requested_category": requested,
        "analysis": analysis,
        "offset": 0,
        "results": scored[:50],
    })
    send_similar_page(sender)

def send_similar_page(sender):
    session = get_session(sender)
    if not session or session.get("type") != "similar_results":
        send_text(sender, "No similar search session found. Please send a product image with /similar first.")
        return
    results = session.get("results", [])
    offset = int(session.get("offset", 0))
    page = results[offset:offset + SIMILAR_PAGE_SIZE]
    if not page:
        send_text(sender, "No more similar products found.")
        return
    for p in page:
        img = p.get("cached_image_url") or p.get("image_url")
        if img and not p.get("cached_image_url"):
            c = cache_public_image(img)
            img = c or img
        cap = (
            f"Code: {p.get('code','N/A')}\n"
            f"Price: {p.get('price') or 'Price not found'}\n"
            f"Similarity: {p.get('similarity',0)}%\n\n"
            + "\n".join([f"✓ {r}" for r in p.get("reasons", [])[:4]])
            + f"\n\n{p.get('url','')}"
        )[:1024]
        if img:
            send_image(sender, img, cap)
        else:
            send_text(sender, cap + "\nImage not available.")
    session["offset"] = offset + len(page)
    set_session(sender, session)
    remaining = max(0, len(results) - session["offset"])
    send_text(sender, f"Reply /more for next {min(SIMILAR_PAGE_SIZE, remaining)} options." if remaining else "End of similar results.")
