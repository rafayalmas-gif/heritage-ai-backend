from config import (
    MIN_MODEL_CONFIDENCE,
    MODEL_SIMILARITY_THRESHOLD,
    MODEL_MAX_RETRIES,
    LOW_CONFIDENCE_REPLY,
)


def calculate_confidence(analysis):
    """
    Practical showroom-friendly confidence scoring.

    This should NOT reject normal showroom photos.
    It should only reject genuinely unusable images.
    """

    category_conf = float(analysis.get("category_confidence", 0) or 0) * 100
    preservation_conf = float(analysis.get("product_preservation_confidence", 0) or 0) * 100

    # Use the better score if analyzer provides both
    confidence = max(category_conf, preservation_conf)

    quality = analysis.get("quality", {}) or {}
    issues = [str(x).lower() for x in (quality.get("issues", []) or [])]

    # Only heavy issues should reduce confidence strongly
    severe_keywords = [
        "very blurry",
        "heavily blurred",
        "mostly covered",
        "fully covered",
        "not visible",
        "cannot identify",
        "too small",
        "severely cropped",
        "missing product",
        "no jewelry visible",
    ]

    moderate_keywords = [
        "blur",
        "reflection",
        "cropped",
        "covered",
        "perspective",
        "screenshot",
        "low resolution",
        "hand",
        "finger",
    ]

    for issue in issues:
        if any(k in issue for k in severe_keywords):
            confidence -= 25
        elif any(k in issue for k in moderate_keywords):
            confidence -= 5

    # Do not punish normal showroom/product photos too harshly
    category = str(analysis.get("category", "")).lower()
    if category in ["ring", "earrings", "tops", "jhumka", "pendant", "necklace", "necklace set", "bangle", "bracelet"]:
        confidence += 5

    return max(0, min(100, int(confidence)))


def should_generate_model(analysis):
    """
    Decide whether /model should proceed.

    V9 practical rule:
    - Generate for most clear showroom photos.
    - Reject only genuinely unusable photos.
    """

    confidence = calculate_confidence(analysis)

    quality = analysis.get("quality", {}) or {}
    issues = [str(x).lower() for x in (quality.get("issues", []) or [])]

    hard_reject_keywords = [
        "no jewelry visible",
        "missing product",
        "cannot identify product",
        "cannot identify jewelry",
        "fully covered",
        "mostly covered",
        "severely cropped",
        "too blurry to analyze",
        "image is blank",
    ]

    if any(any(k in issue for k in hard_reject_keywords) for issue in issues):
        return False, confidence, LOW_CONFIDENCE_REPLY

    if confidence < MIN_MODEL_CONFIDENCE:
        return False, confidence, LOW_CONFIDENCE_REPLY

    return True, confidence, ""


def build_design_lock(analysis):
    """
    Build a strict but readable design lock for image generation.
    """

    dna = analysis.get("design_dna", {}) or {}
    geometry = analysis.get("geometry_lock", {}) or {}

    return f"""
LOCKED PRODUCT SPECIFICATION

Category:
{analysis.get("category", "unknown")}

Category Confidence:
{int(float(analysis.get("category_confidence", 0) or 0) * 100)}%

Product Preservation Confidence:
{int(float(analysis.get("product_preservation_confidence", 0) or 0) * 100)}%

Geometry:
- Silhouette: {geometry.get("silhouette", "")}
- Outer Shape: {geometry.get("outer_shape", "")}
- Proportions: {geometry.get("proportions", "")}
- Width / Thickness: {geometry.get("width_thickness", "")}
- Curve / Profile: {geometry.get("curve_profile", "")}
- Symmetry: {geometry.get("symmetry", "")}

Pattern Family:
{dna.get("pattern_family", [])}

Motif Structure:
{dna.get("motif_structure", [])}

Workmanship:
{dna.get("workmanship", [])}

Repeat Pattern:
{dna.get("repeat_pattern", "")}

Polish:
{dna.get("polish", "")}

Stone Style:
{dna.get("stone_style", "")}

Stone Colors:
{dna.get("stone_colors", [])}

Stone Zones:
{analysis.get("stone_zones", [])}

Drops / Bunches:
{analysis.get("drops_bunches", [])}

Pearls:
{analysis.get("pearls", [])}

White Stones:
{analysis.get("white_stones", "")}

Metal:
{analysis.get("metal", "")}

Scale Estimate:
{analysis.get("scale_estimate", "")}

Wear Position:
{analysis.get("wear_position", "")}

Locked Components:
{analysis.get("locked_components", [])}

Editable Components:
{analysis.get("editable_components", [])}

STRICT LOCK:
All visible jewelry geometry, motifs, stones, pearls, prongs, polish, proportions, and craftsmanship are locked.

ALLOWED EDITS:
Human model, pose, clothing, background, lighting, shadows, camera angle, and minor gemstone sparkle only.

FORBIDDEN:
No redesign.
No similar version.
No motif change.
No stone movement.
No pearl movement.
No proportion change.
No invented details.
"""


def validate_generation_placeholder(generated_image_bytes, original_analysis):
    return True


def get_retry_count():
    return MODEL_MAX_RETRIES


def get_similarity_threshold():
    return MODEL_SIMILARITY_THRESHOLD
