from config import MODEL_SIMILARITY_THRESHOLD


def validate_model_output(generated_image_bytes, analysis):
    """
    Heritage AI V9 validation layer.

    Current version is a safe placeholder.
    It does not block outputs yet.

    Later this file can be upgraded to check:
    - jewelry silhouette
    - stone count
    - pearl count
    - motif preservation
    - geometry similarity
    """

    return {
        "passed": True,
        "score": 100,
        "threshold": MODEL_SIMILARITY_THRESHOLD,
        "issues": [],
    }


def should_retry(validation_result):
    """
    Decide whether generation should retry.
    """

    if not validation_result.get("passed", False):
        return True

    score = validation_result.get("score", 0)

    if score < MODEL_SIMILARITY_THRESHOLD:
        return True

    return False
