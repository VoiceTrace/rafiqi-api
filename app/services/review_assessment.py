"""Deterministic D3 assessment metadata for the curated review catalog."""
from enum import StrEnum


class AssessmentMetadataError(ValueError):
    """The lesson cannot produce a complete, taxonomy-backed attempt record."""


class ReviewErrorType(StrEnum):
    FORCE_PAIR_UNEQUAL_MAGNITUDE = "force_pair_unequal_magnitude"
    FORCE_PAIR_MISSING_REACTION = "force_pair_missing_reaction"
    FORCE_PAIR_INCOMPLETE_DISTINCT_OBJECTS = "force_pair_incomplete_distinct_objects"
    FORCE_PAIR_MISSING_DISTINCT_OBJECTS = "force_pair_missing_distinct_objects"
    BALANCED_FORCE_MEANS_STOPPED = "balanced_force_means_stopped"
    KINETIC_ENERGY_REQUIRES_MOTION = "kinetic_energy_requires_motion"
    EQUIVALENT_FRACTION_DENOMINATOR_ONLY = "equivalent_fraction_denominator_only"


SUBJECT_ERROR_TAXONOMY: dict[str, frozenset[ReviewErrorType]] = {
    "physics": frozenset({
        ReviewErrorType.FORCE_PAIR_UNEQUAL_MAGNITUDE,
        ReviewErrorType.FORCE_PAIR_MISSING_REACTION,
        ReviewErrorType.FORCE_PAIR_INCOMPLETE_DISTINCT_OBJECTS,
        ReviewErrorType.FORCE_PAIR_MISSING_DISTINCT_OBJECTS,
        ReviewErrorType.BALANCED_FORCE_MEANS_STOPPED,
        ReviewErrorType.KINETIC_ENERGY_REQUIRES_MOTION,
    }),
    "mathematics": frozenset({ReviewErrorType.EQUIVALENT_FRACTION_DENOMINATOR_ONLY}),
}

_CHOICE_ERRORS: dict[tuple[str, str], ReviewErrorType] = {
    ("force-pairs", "smaller"): ReviewErrorType.FORCE_PAIR_UNEQUAL_MAGNITUDE,
    ("force-pairs", "none"): ReviewErrorType.FORCE_PAIR_MISSING_REACTION,
    ("balanced-forces-check", "other"): ReviewErrorType.BALANCED_FORCE_MEANS_STOPPED,
    ("kinetic-energy-check", "other"): ReviewErrorType.KINETIC_ENERGY_REQUIRES_MOTION,
    ("equivalent-fractions-check", "other"): ReviewErrorType.EQUIVALENT_FRACTION_DENOMINATOR_ONLY,
}


def classify_error(
    *, subject_id: str | None, question: dict, option_id: str | None, score: float,
) -> str | None:
    """Return a stable subject taxonomy code, or fail when metadata is incomplete."""
    concept_ref = question.get("concept_ref")
    if not subject_id or not concept_ref:
        raise AssessmentMetadataError("assessment_concept_required")
    taxonomy = SUBJECT_ERROR_TAXONOMY.get(subject_id)
    if taxonomy is None:
        raise AssessmentMetadataError("assessment_taxonomy_unavailable")
    if score == 1:
        return None

    if question["kind"] == "choice":
        error_type = _CHOICE_ERRORS.get((question["id"], option_id or ""))
    elif question["id"] == "different-objects":
        error_type = (
            ReviewErrorType.FORCE_PAIR_INCOMPLETE_DISTINCT_OBJECTS
            if score > 0
            else ReviewErrorType.FORCE_PAIR_MISSING_DISTINCT_OBJECTS
        )
    else:
        error_type = None

    if error_type is None or error_type not in taxonomy:
        raise AssessmentMetadataError("assessment_error_mapping_required")
    return error_type.value


def validate_question_assessment(subject_id: str, question: dict) -> None:
    """Reject catalog questions that cannot produce complete D3 attempt data."""
    if question["kind"] == "choice":
        for option in question["options"]:
            classify_error(
                subject_id=subject_id,
                question=question,
                option_id=option["id"],
                score=float(option["id"] == question["answer"]),
            )
    else:
        classify_error(subject_id=subject_id, question=question, option_id=None, score=0)
        classify_error(subject_id=subject_id, question=question, option_id=None, score=0.5)
        classify_error(subject_id=subject_id, question=question, option_id=None, score=1)
