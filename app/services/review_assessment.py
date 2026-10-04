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
    # Forces and motion
    FRICTION_ACTS_ALONG_MOTION = "friction_acts_along_motion"
    FRICTION_INCOMPLETE_SURFACE_CONTACT = "friction_incomplete_surface_contact"
    FRICTION_MISSING_SURFACE_CONTACT = "friction_missing_surface_contact"
    SECOND_LAW_ACCELERATION_IGNORES_MASS = "second_law_acceleration_ignores_mass"
    SECOND_LAW_FORCE_PROPORTIONAL_TO_SPEED = "second_law_force_proportional_to_speed"
    # Energy
    POTENTIAL_ENERGY_IGNORES_HEIGHT = "potential_energy_ignores_height"
    ENERGY_CREATED_FROM_NOTHING = "energy_created_from_nothing"
    ENERGY_INCOMPLETE_TRANSFORMATION_CHAIN = "energy_incomplete_transformation_chain"
    ENERGY_MISSING_TRANSFORMATION_CHAIN = "energy_missing_transformation_chain"
    # Waves
    SOUND_TRAVELS_THROUGH_VACUUM = "sound_travels_through_vacuum"
    REFLECTION_ANGLES_UNEQUAL = "reflection_angles_unequal"
    # Fractions
    FRACTION_LARGER_DENOMINATOR_LARGER_VALUE = "fraction_larger_denominator_larger_value"
    FRACTION_COMPARES_NUMERATORS_ONLY = "fraction_compares_numerators_only"
    FRACTION_ADDITION_ADDS_DENOMINATORS = "fraction_addition_adds_denominators"
    FRACTION_INCOMPLETE_COMMON_DENOMINATOR = "fraction_incomplete_common_denominator"
    FRACTION_MISSING_COMMON_DENOMINATOR = "fraction_missing_common_denominator"
    # Decimals
    DECIMAL_MORE_DIGITS_MEANS_LARGER = "decimal_more_digits_means_larger"
    ROUNDING_TRUNCATES_DIGITS = "rounding_truncates_digits"
    # Matter and change
    STATE_CHANGE_ALTERS_PARTICLE_IDENTITY = "state_change_alters_particle_identity"
    DISSOLVING_IS_A_CHEMICAL_CHANGE = "dissolving_is_a_chemical_change"
    CHANGE_INCOMPLETE_NEW_SUBSTANCE = "change_incomplete_new_substance"
    CHANGE_MISSING_NEW_SUBSTANCE = "change_missing_new_substance"


SUBJECT_ERROR_TAXONOMY: dict[str, frozenset[ReviewErrorType]] = {
    "physics": frozenset({
        ReviewErrorType.FORCE_PAIR_UNEQUAL_MAGNITUDE,
        ReviewErrorType.FORCE_PAIR_MISSING_REACTION,
        ReviewErrorType.FORCE_PAIR_INCOMPLETE_DISTINCT_OBJECTS,
        ReviewErrorType.FORCE_PAIR_MISSING_DISTINCT_OBJECTS,
        ReviewErrorType.BALANCED_FORCE_MEANS_STOPPED,
        ReviewErrorType.KINETIC_ENERGY_REQUIRES_MOTION,
        ReviewErrorType.FRICTION_ACTS_ALONG_MOTION,
        ReviewErrorType.FRICTION_INCOMPLETE_SURFACE_CONTACT,
        ReviewErrorType.FRICTION_MISSING_SURFACE_CONTACT,
        ReviewErrorType.SECOND_LAW_ACCELERATION_IGNORES_MASS,
        ReviewErrorType.SECOND_LAW_FORCE_PROPORTIONAL_TO_SPEED,
        ReviewErrorType.POTENTIAL_ENERGY_IGNORES_HEIGHT,
        ReviewErrorType.ENERGY_CREATED_FROM_NOTHING,
        ReviewErrorType.ENERGY_INCOMPLETE_TRANSFORMATION_CHAIN,
        ReviewErrorType.ENERGY_MISSING_TRANSFORMATION_CHAIN,
        ReviewErrorType.SOUND_TRAVELS_THROUGH_VACUUM,
        ReviewErrorType.REFLECTION_ANGLES_UNEQUAL,
    }),
    "mathematics": frozenset({
        ReviewErrorType.EQUIVALENT_FRACTION_DENOMINATOR_ONLY,
        ReviewErrorType.FRACTION_LARGER_DENOMINATOR_LARGER_VALUE,
        ReviewErrorType.FRACTION_COMPARES_NUMERATORS_ONLY,
        ReviewErrorType.FRACTION_ADDITION_ADDS_DENOMINATORS,
        ReviewErrorType.FRACTION_INCOMPLETE_COMMON_DENOMINATOR,
        ReviewErrorType.FRACTION_MISSING_COMMON_DENOMINATOR,
        ReviewErrorType.DECIMAL_MORE_DIGITS_MEANS_LARGER,
        ReviewErrorType.ROUNDING_TRUNCATES_DIGITS,
    }),
    "chemistry": frozenset({
        ReviewErrorType.STATE_CHANGE_ALTERS_PARTICLE_IDENTITY,
        ReviewErrorType.DISSOLVING_IS_A_CHEMICAL_CHANGE,
        ReviewErrorType.CHANGE_INCOMPLETE_NEW_SUBSTANCE,
        ReviewErrorType.CHANGE_MISSING_NEW_SUBSTANCE,
    }),
}

# One entry per (question id, chosen distractor). A choice question only seeds
# once every option is mapped, which is what keeps the attempt taxonomy complete
# instead of silently recording a NULL error type for an unmapped distractor.
_CHOICE_ERRORS: dict[tuple[str, str], ReviewErrorType] = {
    ("force-pairs", "smaller"): ReviewErrorType.FORCE_PAIR_UNEQUAL_MAGNITUDE,
    ("force-pairs", "none"): ReviewErrorType.FORCE_PAIR_MISSING_REACTION,
    ("balanced-forces-check", "other"): ReviewErrorType.BALANCED_FORCE_MEANS_STOPPED,
    ("kinetic-energy-check", "other"): ReviewErrorType.KINETIC_ENERGY_REQUIRES_MOTION,
    ("equivalent-fractions-check", "other"): ReviewErrorType.EQUIVALENT_FRACTION_DENOMINATOR_ONLY,
    ("friction-direction-check", "other"): ReviewErrorType.FRICTION_ACTS_ALONG_MOTION,
    ("second-law-check", "other"): ReviewErrorType.SECOND_LAW_ACCELERATION_IGNORES_MASS,
    ("second-law-check", "speed"): ReviewErrorType.SECOND_LAW_FORCE_PROPORTIONAL_TO_SPEED,
    ("potential-energy-check", "other"): ReviewErrorType.POTENTIAL_ENERGY_IGNORES_HEIGHT,
    ("energy-conservation-check", "other"): ReviewErrorType.ENERGY_CREATED_FROM_NOTHING,
    ("sound-medium-check", "other"): ReviewErrorType.SOUND_TRAVELS_THROUGH_VACUUM,
    ("reflection-angle-check", "other"): ReviewErrorType.REFLECTION_ANGLES_UNEQUAL,
    ("comparing-fractions-check", "other"): ReviewErrorType.FRACTION_LARGER_DENOMINATOR_LARGER_VALUE,
    ("comparing-fractions-check", "numerator"): ReviewErrorType.FRACTION_COMPARES_NUMERATORS_ONLY,
    ("adding-fractions-check", "other"): ReviewErrorType.FRACTION_ADDITION_ADDS_DENOMINATORS,
    ("decimal-place-value-check", "other"): ReviewErrorType.DECIMAL_MORE_DIGITS_MEANS_LARGER,
    ("rounding-decimals-check", "other"): ReviewErrorType.ROUNDING_TRUNCATES_DIGITS,
    ("states-of-matter-check", "other"): ReviewErrorType.STATE_CHANGE_ALTERS_PARTICLE_IDENTITY,
    ("change-type-check", "other"): ReviewErrorType.DISSOLVING_IS_A_CHEMICAL_CHANGE,
}

# Written answers are scored by keyword coverage, so the only distinction the
# rubric can draw is between partially and wholly missing the concept. Each
# written question names both codes here rather than being special-cased by id.
_WRITTEN_ERRORS: dict[str, tuple[ReviewErrorType, ReviewErrorType]] = {
    "different-objects": (
        ReviewErrorType.FORCE_PAIR_INCOMPLETE_DISTINCT_OBJECTS,
        ReviewErrorType.FORCE_PAIR_MISSING_DISTINCT_OBJECTS,
    ),
    "friction-surface-note": (
        ReviewErrorType.FRICTION_INCOMPLETE_SURFACE_CONTACT,
        ReviewErrorType.FRICTION_MISSING_SURFACE_CONTACT,
    ),
    "energy-conservation-note": (
        ReviewErrorType.ENERGY_INCOMPLETE_TRANSFORMATION_CHAIN,
        ReviewErrorType.ENERGY_MISSING_TRANSFORMATION_CHAIN,
    ),
    "adding-fractions-note": (
        ReviewErrorType.FRACTION_INCOMPLETE_COMMON_DENOMINATOR,
        ReviewErrorType.FRACTION_MISSING_COMMON_DENOMINATOR,
    ),
    "change-type-note": (
        ReviewErrorType.CHANGE_INCOMPLETE_NEW_SUBSTANCE,
        ReviewErrorType.CHANGE_MISSING_NEW_SUBSTANCE,
    ),
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
    else:
        incomplete, missing = _WRITTEN_ERRORS.get(question["id"], (None, None))
        error_type = incomplete if score > 0 else missing

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
