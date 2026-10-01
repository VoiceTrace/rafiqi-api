"""Ship review catalog v2: more lessons, and the error codes they classify.

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9

The catalog grows by twelve lessons covering friction, Newton's second law,
potential energy, conservation of energy, waves, decimals and chemistry. Two
things have to move together for that content to work, which is why they are one
revision: the rows themselves, and the review_attempts error-code allow-list that
the new lessons' misconceptions are classified into.

Catalog content ships through migrations (see f6b2c3d4e5f6) so a migrated database
serves lessons without anyone running scripts/seed.py. Earlier fixtures stay frozen
and each version adds its own, so a database migrated last month and one migrated
today end up with identical content.
"""
import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert

revision = "c5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None

CONSTRAINT = "ck_review_attempt_error_type"

CURRENT_ERROR_TYPES = (
    "error_type IS NULL OR error_type IN ("
        "'balanced_force_means_stopped', 'change_incomplete_new_substance', "
        "'change_missing_new_substance', 'decimal_more_digits_means_larger', "
        "'dissolving_is_a_chemical_change', 'energy_created_from_nothing', "
        "'energy_incomplete_transformation_chain', 'energy_missing_transformation_chain', "
        "'equivalent_fraction_denominator_only', 'force_pair_incomplete_distinct_objects', "
        "'force_pair_missing_distinct_objects', 'force_pair_missing_reaction', "
        "'force_pair_unequal_magnitude', 'fraction_addition_adds_denominators', "
        "'fraction_compares_numerators_only', 'fraction_incomplete_common_denominator', "
        "'fraction_larger_denominator_larger_value', 'fraction_missing_common_denominator', "
        "'friction_acts_along_motion', 'friction_incomplete_surface_contact', "
        "'friction_missing_surface_contact', 'kinetic_energy_requires_motion', "
        "'potential_energy_ignores_height', 'reflection_angles_unequal', "
        "'rounding_truncates_digits', 'second_law_acceleration_ignores_mass', "
        "'second_law_force_proportional_to_speed', 'sound_travels_through_vacuum', "
        "'state_change_alters_particle_identity'"
    ")"
)

PREVIOUS_ERROR_TYPES = (
    "error_type IS NULL OR error_type IN ("
        "'force_pair_unequal_magnitude', 'force_pair_missing_reaction', "
        "'force_pair_incomplete_distinct_objects', 'force_pair_missing_distinct_objects', "
        "'balanced_force_means_stopped', 'kinetic_energy_requires_motion', "
        "'equivalent_fraction_denominator_only'"
    ")"
)

SUBJECTS = sa.table("review_subjects", sa.column("id", sa.String), sa.column("title", sa.JSON))
CHAPTERS = sa.table(
    "review_chapters", sa.column("id", sa.String),
    sa.column("subject_id", sa.String), sa.column("title", sa.JSON),
)
LESSONS = sa.table(
    "review_lessons", sa.column("id", sa.String),
    sa.column("chapter_id", sa.String), sa.column("content", sa.JSON),
)


def upgrade():
    op.drop_constraint(CONSTRAINT, "review_attempts", type_="check")
    op.create_check_constraint(CONSTRAINT, "review_attempts", CURRENT_ERROR_TYPES)

    fixture = json.loads(
        (Path(__file__).parent / "fixtures/review-catalog-v2.json").read_text(encoding="utf-8")
    )
    db = op.get_bind()
    # Insert-only, in dependency order. on_conflict_do_nothing keeps this safe on a
    # database where scripts/seed.py already inserted the same rows, and guarantees
    # locally edited content is never overwritten.
    for table, key in ((SUBJECTS, "subjects"), (CHAPTERS, "chapters"), (LESSONS, "lessons")):
        for row in fixture[key]:
            db.execute(insert(table).values(**row).on_conflict_do_nothing(index_elements=["id"]))


def downgrade():
    # The v1 migration deliberately keeps seeded lessons on the way down, because a
    # review_session snapshot points at its lesson and deleting the row would take
    # student work with it. The same applies here, so content stays.
    #
    # The allow-list does narrow again, and that will fail loudly if any attempt has
    # already recorded one of the new codes — the honest outcome, since that evidence
    # cannot be expressed in the old taxonomy.
    op.drop_constraint(CONSTRAINT, "review_attempts", type_="check")
    op.create_check_constraint(CONSTRAINT, "review_attempts", PREVIOUS_ERROR_TYPES)
