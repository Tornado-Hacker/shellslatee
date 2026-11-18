from __future__ import annotations

import re
from dataclasses import dataclass, field

from .templates import Template

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[a-z0-9]{4,}")

STOPWORDS = {
    "about", "after", "again", "also", "because", "been", "before", "being",
    "both", "build", "call", "case", "could", "does", "each", "from", "have",
    "here", "into", "just", "lesson", "like", "make", "many", "more", "most",
    "much", "need", "only", "other", "over", "same", "some", "such", "than",
    "that", "their", "them", "then", "there", "these", "they", "thing", "this",
    "those", "through", "under", "using", "very", "want", "well", "were",
    "what", "when", "where", "which", "while", "will", "with", "work", "your",
}


@dataclass
class Rubric:
    score: int
    issues: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.issues


def _sentences(text: str) -> int:
    parts = [part for part in _SENTENCE_RE.split(text.strip()) if part.strip()]
    return len(parts) if parts else 0


def _vocabulary(text: str) -> set[str]:
    return {word for word in _WORD_RE.findall(text.lower()) if word not in STOPWORDS}


def _title_grounded(title: str, vocabulary: set[str]) -> bool:
    words = {word for word in _WORD_RE.findall(title.lower()) if word not in STOPWORDS}
    if not words:
        return True
    return len(words & vocabulary) / len(words) >= 0.5


def score_note(note, transcript_text: str, duration: float, template: Template) -> Rubric:
    """Cheap, deterministic rubric. Returns a 0-100 score and the issues that lost points."""
    score = 0
    issues: list[str] = []
    metrics: dict[str, float] = {}

    sentences = _sentences(note.summary)
    metrics["summary_sentences"] = float(sentences)
    if 3 <= sentences <= 6:
        score += 15
    elif sentences:
        score += 6
        issues.append(f"summary has {sentences} sentence(s); aim for 3-6")
    else:
        issues.append("summary is empty")

    concepts = note.key_concepts
    metrics["concepts"] = float(len(concepts))
    if 3 <= len(concepts) <= 8:
        score += 8
    else:
        issues.append(f"key_concepts has {len(concepts)} item(s); aim for 3-8")

    defined = [item for item in concepts if item.get("definition")]
    metrics["defined_concepts"] = float(len(defined))
    if len(defined) == len(concepts) and concepts:
        score += 8
    else:
        issues.append("every key concept needs a definition")

    average_definition = (
        sum(len(item.get("definition", "")) for item in defined) / len(defined) if defined else 0
    )
    metrics["avg_definition_chars"] = round(average_definition, 1)
    if average_definition >= 12:
        score += 4
    elif defined:
        issues.append("concept definitions are too short to be useful")

    topics = note.topics
    metrics["topics"] = float(len(topics))
    if 3 <= len(topics) <= 12:
        score += 6
    else:
        issues.append(f"topics has {len(topics)} item(s); aim for 3-12")

    starts = [float(topic.get("start") or 0) for topic in topics]
    if starts and all(start >= 0 for start in starts) and starts == sorted(starts):
        score += 6
    elif starts:
        issues.append("topic timestamps are not in order")

    if not duration or all(start <= duration + 10 for start in starts):
        score += 4
    else:
        issues.append("a topic timestamp falls past the end of the video")

    thin = [topic for topic in topics if len(topic.get("details") or []) < template.min_topic_details]
    metrics["thin_topics"] = float(len(thin))
    if topics and not thin:
        score += 5
    elif thin:
        issues.append(
            f"{len(thin)} topic(s) have fewer than {template.min_topic_details} detail line(s)"
        )

    with_details = [topic for topic in topics if topic.get("details")]
    if topics and len(with_details) == len(topics):
        score += 4
    elif topics:
        issues.append("every topic needs at least one detail line")

    questions = note.review_questions
    metrics["review_questions"] = float(len(questions))
    if template.min_review_questions <= len(questions) <= 8:
        score += 15
    elif len(questions) >= template.min_review_questions:
        score += 8
        issues.append(f"review_questions has {len(questions)} item(s); aim for 3-6")
    else:
        score += 4
        issues.append(
            f"review_questions needs at least {template.min_review_questions} item(s) for a {template.label} template"
        )

    tags = note.tags
    metrics["tags"] = float(len(tags))
    if 2 <= len(tags) <= 6 and len(set(tags)) == len(tags):
        score += 10
    elif tags:
        score += 4
        issues.append("tags should be 2-6 unique lowercase strings")
    else:
        issues.append("tags are empty")

    vocabulary = _vocabulary(transcript_text)
    if vocabulary:
        grounded = [topic for topic in topics if _title_grounded(str(topic.get("title", "")), vocabulary)]
        ratio = len(grounded) / len(topics) if topics else 0.0
        metrics["grounded_topics"] = round(ratio, 2)
        if ratio >= 0.7:
            score += 15
        elif ratio >= 0.4:
            score += 7
            issues.append("some topic titles use words that never appear in the transcript")
        else:
            issues.append("topic titles drift from the transcript wording")

    if template.require_definitions and len(defined) != len(concepts):
        metrics["definitions_required"] = 1.0

    return Rubric(score=min(100, score), issues=issues, metrics=metrics)
