from config import (
    MIN_MODEL_CONFIDENCE,
    MODEL_SIMILARITY_THRESHOLD,
    MODEL_MAX_RETRIES,
    LOW_CONFIDENCE_REPLY,
)


def calculate_confidence(analysis):
    category_conf = float(analysis.get("category_confidence", 0)) * 100
    quality = analysis.get("quality", {}) or {}
    issues = quality.get("issues", []) or []

    confidence = category_conf

    if not quality.get("is_clear", True):
        confidence -= 20

    confidence -= min(len(issues) * 8, 40)

    complexity = (
        analysis.get("design_dna", {})
        .get("complexity", "")
        .lower()
    )

    if complexity in ["high", "very high", "complex"]:
        confidence -= 5

    return max(0, min(100, int(confidence)))


def should_generate_model(analysis):
    confidence = calculate_confidence(analysis)

    if confidence < MIN_MODEL_CONFIDENCE:
        return False, confidence, LOW_CONFIDENCE_REPLY

    return True, confidence, ""


def build_design_lock(analysis):
    dna = analysis.get("design_dna", {}) or {}

    return f"""
LOCKED PRODUCT SPECIFICATION

Category:
{analysis.get("category", "unknown")}

Category Confidence:
{int(float(analysis.get("category_confidence", 0)) * 100)}%

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

STRICT LOCK:
All visible jewelry geometry, motifs, stones, pearls, prongs, polish, proportions, and craftsmanship are locked.

ALLOWED EDITS:
Human model, pose, clothing, background, lighting, shadows, camera angle, and minor gemstone sparkle only.

FORBIDDEN:
No redesign. No similar version. No motif change. No stone movement. No pearl movement. No proportion change. No invented details.
"""


def validate_generation_placeholder(generated_image_bytes, original_analysis):
    """
    V9 placeholder validation.

    Real image similarity validation can be added later with computer vision.
    For now, this allows retries structure without breaking the system.
    """
    return True


def get_retry_count():
    return MODEL_MAX_RETRIES


def get_similarity_threshold():
    return MODEL_SIMILARITY_THRESHOLD
