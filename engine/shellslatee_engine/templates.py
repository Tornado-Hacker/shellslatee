from __future__ import annotations

from dataclasses import dataclass

DEFAULT_TEMPLATE = "lecture"


@dataclass(frozen=True)
class Template:
    name: str
    label: str
    guidance: str
    min_review_questions: int = 3
    min_topic_details: int = 1
    require_definitions: bool = False
    quality_floor: int = 80


TEMPLATES: dict[str, Template] = {
    "lecture": Template(
        name="lecture",
        label="Lecture",
        guidance=(
            "Shape the notes for a student revising a lecture: one clear arc from problem to rule, "
            "concepts defined as the lecturer uses them, and a walkthrough that follows the recording."
        ),
    ),
    "tutorial": Template(
        name="tutorial",
        label="Tutorial",
        guidance=(
            "Shape the notes for someone rebuilding the workflow: name prerequisites first, keep the "
            "walkthrough in execution order, and make every topic detail an actionable step or a check."
        ),
        min_topic_details=2,
    ),
    "interview": Template(
        name="interview",
        label="Interview prep",
        guidance=(
            "Shape the notes as technical-interview preparation: for each topic, the question it answers, "
            "precise term definitions, and review questions phrased the way an interviewer would ask them."
        ),
        min_review_questions=4,
    ),
    "exam": Template(
        name="exam",
        label="Exam prep",
        guidance=(
            "Shape the notes for closed-book exam preparation: every key concept needs a precise, "
            "self-contained definition, and review questions must be answerable from memory alone."
        ),
        min_review_questions=5,
        require_definitions=True,
    ),
}


def get_template(name: str | None) -> Template:
    if not name:
        return TEMPLATES[DEFAULT_TEMPLATE]
    return TEMPLATES.get(name.strip().lower(), TEMPLATES[DEFAULT_TEMPLATE])


def template_names() -> tuple[str, ...]:
    return tuple(TEMPLATES)
