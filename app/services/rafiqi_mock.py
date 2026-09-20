"""
MockRafiqi — dev-only stand-in for the real Rafiqi AI layer.

Drop-in implementation of RafiqiInterface. Returns deterministic, plausible
responses so the rest of the stack can be developed and tested without the
real AI layer.

Usage:
    from app.services.rafiqi_mock import MockRafiqi
    rafiqi: RafiqiInterface = MockRafiqi()

Replace with the real implementation when the AI layer ships.
"""

from app.services.rafiqi_interface import (
    RafiqiInterface,
    SessionPlan,
    GeneratedQuestion,
    ScoredResponse,
    HintResponse,
    ConceptExplanation,
    SessionSummary,
)


class MockRafiqi:
    """Satisfies RafiqiInterface. All responses are deterministic stubs."""

    async def plan_session(
        self,
        lesson_content: dict,
        student_profile: dict,
    ) -> SessionPlan:
        concepts = lesson_content.get("concepts", ["concept_1", "concept_2", "concept_3"])
        return SessionPlan(
            concepts_order=concepts,
            recommended_stage="review",
            notes="[mock] No prior gaps detected — starting from review.",
        )

    async def generate_question(
        self,
        concept_ref: str,
        stage: str,
        lesson_context: dict,
        prior_errors: list[str],
    ) -> GeneratedQuestion:
        difficulty = "applied" if stage == "deepen" else "basic"
        return GeneratedQuestion(
            question_text=f"[mock] Explain the concept of '{concept_ref}' in your own words.",
            internal_answer_key=f"[mock answer key for {concept_ref}] The student should demonstrate understanding of the core definition and one application.",
            difficulty_hint=difficulty,
        )

    async def score_response(
        self,
        question_text: str,
        internal_answer_key: str,
        student_response: str,
        hint_level: int,
    ) -> ScoredResponse:
        response_len = len(student_response.strip())
        if response_len >= 80:
            score = 0.9
            error_type = None
            feedback = "[mock] Great answer! You clearly understand this concept."
            confirmed = True
        elif response_len >= 30:
            score = 0.6
            error_type = "application_error"
            feedback = "[mock] You have the right idea but the explanation could be more precise."
            confirmed = False
        else:
            score = 0.2
            error_type = "recall_error"
            feedback = "[mock] Try to give a more complete answer — think about the definition first."
            confirmed = False

        return ScoredResponse(
            correctness_score=score,
            error_type=error_type,
            feedback_text=feedback,
            concept_confirmed=confirmed,
        )

    async def generate_hint(
        self,
        question_text: str,
        internal_answer_key: str,
        student_response: str,
        hint_level: int,
    ) -> HintResponse:
        hints = {
            1: ("[mock] Think about the key term — what does it mean in this subject?", False),
            2: ("[mock] Here's a partial clue: the answer involves the relationship between the parts you mentioned.", False),
            3: ("[mock] The answer is: " + internal_answer_key[:100] + "...", True),
        }
        text, reveals = hints.get(hint_level, ("[mock] Think carefully.", False))
        return HintResponse(hint_text=text, reveals_answer=reveals)

    async def explain_concept(
        self,
        concept_ref: str,
        lesson_context: dict,
        student_question: str | None,
    ) -> ConceptExplanation:
        base = f"[mock] '{concept_ref}' refers to a fundamental idea in this lesson."
        if student_question:
            base += f" Regarding your question '{student_question[:60]}' — this is explained by the core definition."
        return ConceptExplanation(explanation_text=base)

    async def generate_summary(
        self,
        session_concepts: list[str],
        mastery_by_concept: dict[str, float],
        error_summary: dict[str, str | None],
    ) -> SessionSummary:
        strong = [c for c, m in mastery_by_concept.items() if m >= 0.75]
        gaps = [c for c, m in mastery_by_concept.items() if m < 0.4]
        return SessionSummary(
            summary_text=f"[mock] You worked through {len(session_concepts)} concept(s) today.",
            strong_concepts=strong,
            gap_concepts=gaps,
            encouragement="[mock] Keep going — every session makes you stronger!",
        )


# Verify the mock satisfies the Protocol at import time
assert isinstance(MockRafiqi(), RafiqiInterface), "MockRafiqi must satisfy RafiqiInterface"
