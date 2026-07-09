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
The jewelry is the final product.
The jewelry is NOT inspiration.
The model is only for presentation.

USER REQUEST:
{user_text}

ANALYZER JSON:
{analysis_json}

{design_lock}

EXACT PRODUCT PRESERVATION — HIGHEST PRIORITY:
- Treat the uploaded jewelry exactly like a finished commercial product.
- Imagine a professional photographer placed THAT SAME jewelry onto a model.
- Do NOT recreate the jewelry.
- Do NOT redraw the jewelry.
- Do NOT reinterpret the jewelry.
- Do NOT improve the jewelry design.
- Do NOT beautify the jewelry design.
- Do NOT simplify the jewelry.
- Do NOT modernize the jewelry.
- Do NOT repair imperfections.
- Do NOT make it more symmetrical.
- Do NOT replace craftsmanship.
- Do NOT invent missing details.
- Do NOT create a similar version.
- Every visible design detail must remain identical.
- If uncertain, preserve the uploaded jewelry exactly instead of guessing.

FORBIDDEN JEWELRY CHANGES:
Never change:
- silhouette
- outline
- geometry
- proportions
- scale
- width
- thickness
- depth
- curve
- profile
- motif
- kaam
- pattern
- motif spacing
- repeat pattern
- engraving
- filigree
- jaali
- kundan
- meenakari
- texture
- craftsmanship
- stone count
- stone shape
- stone size
- stone cut
- stone color
- stone position
- stone orientation
- stone spacing
- diamond layout
- halo layout
- prongs
- bezels
- pavé
- pearl count
- pearl size
- pearl position
- pearl spacing
- drop count
- bunches
- chains
- hooks
- clasps
- bail
- polish
- metal tone
- construction
- symmetry
- ring shank
- gallery
- shoulder design
- under-gallery

ONLY ALLOWED CHANGES:
- human model
- pose
- modest clothing
- background
- lighting
- shadows
- camera angle
- skin rendering
- depth of field
- minor stone sparkle
- minor stone reflection

PRODUCT PHOTOGRAPHY RULE:
Think like a luxury jewelry product photographer and CAD quality inspector.
The product should look like the original photograph was physically moved onto the model.
Never create a CGI interpretation.
Never redesign the product.

VISUAL ATTENTION RULE:
Jewelry should receive approximately 80% visual attention.
Model should receive approximately 20% visual attention.
The customer's eye must immediately focus on the jewelry.

MODEL STYLING:
- Pakistani / South Asian model.
- Modest Pakistani / South Asian formal attire only.
- No deep neckline.
- No revealing styling.
- No extra jewelry.
- No distracting accessories.
- Face/model must not overpower product.
- Jewelry must remain the hero.

CATEGORY-SPECIFIC LOCKS:

RING LOCK:
- Preserve exact shank width.
- Preserve band profile.
- Preserve shoulder angle.
- Preserve gallery height.
- Preserve under-gallery.
- Preserve center stone position.
- Preserve center stone cut.
- Preserve side stone layout.
- Preserve bypass/crossover direction.
- Show one ring on one finger only.
- Never span two fingers.

EARRING / TOPS / JHUMKA LOCK:
- Preserve top stud.
- Preserve connector.
- Preserve lower dome.
- Preserve dome height.
- Preserve dome diameter.
- Preserve hook/screw/post.
- Preserve pearl count.
- Preserve pearl spacing.
- Preserve pearl hanging length.
- Preserve kundan/meenakari/jaali layout.
- Show on ear only.

PENDANT LOCK:
- Preserve bail.
- Preserve pendant outline.
- Preserve center stone.
- Preserve drop layout.
- Show as pendant on chain.

NECKLACE / NECKLACE SET LOCK:
- Preserve full necklace curve.
- Preserve strand count.
- Preserve motif spacing.
- Preserve pendant/drop count.
- Preserve hanging elements.
- Preserve side motifs.
- Preserve full visible construction.

BANGLE / BRACELET LOCK:
- Show on wrist.
- Preserve width.
- Preserve thickness.
- Preserve circumference appearance.
- Preserve repeat pattern.
- Preserve clasp/opening.
- Preserve every visible motif.
- Preserve handcrafted surface texture.

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
        base_prompt
        + """
VIEW 1:
Close-up macro jewelry wearing view.
Entire jewelry must be fully visible and product-focused.
Jewelry should occupy approximately 45–65% of the image area.
""",
        base_prompt
        + """
VIEW 2:
Slightly wider modest styled model portrait.
Jewelry remains the hero.
Model should not overpower the product.
""",
    ]

    if count >= 3:
        prompts.append(
            base_prompt
            + """
VIEW 3:
Luxury campaign angle.
Modest formal styling.
Jewelry fully visible.
Product accuracy is more important than campaign beauty.
"""
        )

    return prompts


def _retry_instruction(attempt):
    if attempt == 0:
        return ""

    if attempt == 1:
        return """

RETRY STRICTNESS:
Previous output may have modified jewelry details.
Preserve the uploaded jewelry more strictly.
Do NOT redesign any visible element.
Do NOT alter stones, pearls, motifs, prongs, polish, or proportions.
"""

    return """

FINAL RETRY STRICTNESS:
Previous generation failed exact product preservation.
Generate the identical uploaded jewelry.
The only allowed change is placing the same jewelry onto a real model environment.
If any jewelry detail is uncertain, preserve the original visible detail instead of inventing.
"""


def model_outputs(image_bytes, image_mime, text):
    """
    Heritage AI V9 /model workflow:
    1. Analyze jewelry
    2. Build exact product preservation lock
    3. Confidence gate
    4. Generate with retry strictness
    5. Validate output
    6. Return customer-shareable images or text clarification
    """

    analysis = analyze_product(image_bytes, image_mime, text)

    allowed, confidence, reason = should_generate_model(analysis)

    if not allowed:
        return [reason or LOW_CONFIDENCE_REPLY]

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

        for attempt in range(get_retry_count()):
            attempt_prompt = prompt + _retry_instruction(attempt)

            generated = image_edit(image_bytes, attempt_prompt)

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
