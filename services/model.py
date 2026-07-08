import json

from services.analyzer import analyze_product
from services.openai_service import image_edit
from services.preservation import (
    build_design_lock,
    should_generate_model,
    get_retry_count,
)
from services.validator import validate_model_output, should_retry
from config import MANAGER_APPROVAL_TEXT, LOW_CONFIDENCE_REPLY


def _option_count(text):
    text = (text or "").lower()

    if any(x in text for x in ["3", "three", "teen", "تین"]):
        return 3

    return 2


def _build_base_prompt(analysis, design_lock, user_text):
    analysis_json = json.dumps(analysis, ensure_ascii=False, indent=2)

    return f"""
HERITAGE AI V9 MODEL VISUALIZATION

PRIMARY OBJECTIVE:
Create the illusion that the ORIGINAL uploaded jewelry was professionally photographed on a real human model.

The uploaded jewelry is the master reference.
The jewelry is the product.
The model is only for presentation.

USER REQUEST:
{user_text}

ANALYZER JSON:
{analysis_json}

{design_lock}

EXACT PRODUCT PRESERVATION:
- Use the exact uploaded jewelry only.
- Do not create a similar version.
- Do not redesign.
- Do not simplify.
- Do not enhance the design.
- Do not modernize.
- Do not replace craftsmanship.
- Do not invent missing details.
- Do not change geometry, silhouette, scale, width, thickness, curve, profile, motif, kaam, pattern, stone count, stone shape, stone size, stone position, pearl count, pearl position, prongs, halos, drops, bunches, chains, hooks, clasps, bail, polish, metal tone, or construction.

ONLY ALLOWED CHANGES:
- human model
- pose
- modest clothing
- background
- lighting
- shadows
- camera angle
- skin rendering
- minor stone sparkle/reflection

MODEL STYLING:
- Pakistani / South Asian model.
- Modest Pakistani / South Asian formal attire only.
- No deep neckline.
- No revealing styling.
- No extra jewelry.
- Jewelry must remain the hero.
- Face/model must not overpower product.

CATEGORY RULES:
- If ring: show one ring on one finger only. Never span two fingers.
- If earrings/tops/jhumka: show on ear.
- If pendant: show as pendant on chain.
- If necklace/necklace set: preserve full curve, strand count, drops, and motif spacing.
- If bangle/bracelet: show on wrist and preserve width, thickness, and repeat pattern.

FINAL OUTPUT RULES:
- No text.
- No logo.
- No watermark.
- No captions inside image.
- Customer-shareable luxury presentation.
- {MANAGER_APPROVAL_TEXT}
"""


def _view_prompts(base_prompt, count):
    prompts = [
        base_prompt + "\nVIEW 1: Close-up wearing view. Entire jewelry must be fully visible and product-focused.",
        base_prompt + "\nVIEW 2: Slightly wider modest styled model portrait. Jewelry remains the hero.",
    ]

    if count >= 3:
        prompts.append(
            base_prompt + "\nVIEW 3: Luxury campaign angle, modest formal styling, jewelry fully visible."
        )

    return prompts


def model_outputs(image_bytes, image_mime, text):
    """
    Heritage AI V9 /model workflow:
    1. Analyze jewelry
    2. Build exact product preservation lock
    3. Confidence gate
    4. Generate with retries
    5. Validate placeholder
    6. Return customer-shareable images
    """

    analysis = analyze_product(image_bytes, image_mime, text)

    allowed, confidence, reason = should_generate_model(analysis)

    if not allowed:
        return [LOW_CONFIDENCE_REPLY]

    design_lock = build_design_lock(analysis)

    count = _option_count(text)

    base_prompt = _build_base_prompt(
        analysis=analysis,
        design_lock=design_lock,
        user_text=text,
    )

    prompts = _view_prompts(base_prompt, count)

    outputs = []

    for prompt in prompts:
        final_image = None

        for _ in range(get_retry_count()):
            generated = image_edit(image_bytes, prompt)

            validation = validate_model_output(
                generated_image_bytes=generated,
                analysis=analysis,
            )

            if not should_retry(validation):
                final_image = generated
                break

            final_image = generated

        if final_image:
            outputs.append(final_image)

    if not outputs:
        return [reason or LOW_CONFIDENCE_REPLY]

    return outputs
