"""
Rafiqi interface contract.

This module defines the Protocol that the real Rafiqi AI layer must implement.
The service layer depends only on this Protocol — never on a concrete implementation.
MockRafiqi (rafiqi_mock.py) satisfies it for development until the real AI layer ships.

Contract notes for the AI layer developer:
- We never pass student_id or school_id — Rafiqi is stateless and identity-unaware.
- All context (question, answer key, student response) is passed per-call.
- internal_answer_key is Rafiqi's own output; we store it and pass it back on scoring/hints.
- Rafiqi is responsible for the academic intelligence; the service owns all side effects.
"""

from typing import Protocol, runtime_checkable
from dataclasses import dataclass


@dataclass
class SessionPlan:
    """Rafiqi's analysis of a lesson for a specific student."""
    concepts_order: list[str]        # ordered list of concept_refs to cover in this session
    recommended_stage: str           # where to start: "review" | "check_in" | "deepen"
    notes: str                       # internal reasoning — for logging, not shown to student


@dataclass
class GeneratedQuestion:
    """A question Rafiqi generated for a concept at a given stage."""
    question_text: str               # shown to student
    internal_answer_key: str         # stored server-side, used for scoring/hints, NEVER sent to student
    difficulty_hint: str             # "basic" | "applied" | "synthesis" — for Rafiqi's internal use


@dataclass
class ScoredResponse:
    """Rafiqi's evaluation of a student's answer."""
    correctness_score: float         # 0.0 – 1.0 (partial credit supported)
    error_type: str | None           # ErrorType taxonomy; null when score >= 0.8
    feedback_text: str               # short feedback shown to student (no answer revealed)
    concept_confirmed: bool          # True when Rafiqi is confident concept is understood


@dataclass
class HintResponse:
    """A hint appropriate for the current hint_level."""
    hint_text: str                   # shown to student
    reveals_answer: bool             # True only when hint_level == 3


@dataclass
class ConceptExplanation:
    """Rafiqi's explanation of a concept, anchored to lesson context."""
    explanation_text: str


@dataclass
class SessionSummary:
    """Post-session summary card for the student."""
    summary_text: str                # what you worked on today
    strong_concepts: list[str]       # concept_refs the student nailed
    gap_concepts: list[str]          # concept_refs that need more work
    encouragement: str               # motivational closing line


@runtime_checkable
class RafiqiInterface(Protocol):
    """
    Contract the AI layer must satisfy. All methods are async.

    Context passed to Rafiqi must NEVER include:
      - student_id / school_id (PDPL)
      - internal DB IDs
    """

    async def plan_session(
        self,
        lesson_content: dict,        # objectives, concepts, materials from B1
        student_profile: dict,       # traits, mastery_records — anonymised
    ) -> SessionPlan: ...

    async def generate_question(
        self,
        concept_ref: str,
        stage: str,                  # "check_in" | "deepen"
        lesson_context: dict,        # relevant lesson excerpt
        prior_errors: list[str],     # error types from previous attempts on this concept
    ) -> GeneratedQuestion: ...

    async def score_response(
        self,
        question_text: str,
        internal_answer_key: str,
        student_response: str,
        hint_level: int,             # how much help was already shown
    ) -> ScoredResponse: ...

    async def generate_hint(
        self,
        question_text: str,
        internal_answer_key: str,
        student_response: str,       # what they tried last
        hint_level: int,             # 1 = nudge, 2 = partial reveal, 3 = full answer
    ) -> HintResponse: ...

    async def explain_concept(
        self,
        concept_ref: str,
        lesson_context: dict,
        student_question: str | None,
    ) -> ConceptExplanation: ...

    async def generate_summary(
        self,
        session_concepts: list[str],
        mastery_by_concept: dict[str, float],
        error_summary: dict[str, str | None],
    ) -> SessionSummary: ...
