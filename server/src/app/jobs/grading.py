"""Grading job (#22): grade one answer to a question.

Multiple choice and blank answers are graded in code. Short answers go to the smart model,
which picks a verdict; the score is derived from the verdict in code.
"""
from dataclasses import dataclass
from pathlib import Path

from app.db.models import Question
from app.llm import Message, ModelClient

PROMPT = (Path(__file__).parent.parent / "prompts" / "grading_v1.txt").read_text()

GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},  # first: compare the answer with the key before writing the verdict
        "verdict": {"type": "string", "enum": ["correct", "partially_correct", "incorrect"]},
        "feedback": {"type": "string"},  # 1-2 sentences shown to the student
    },
    "required": ["reason", "verdict", "feedback"],
    "additionalProperties": False,
}

SCORES = {"correct": 1.0, "partially_correct": 0.5, "incorrect": 0.0}


@dataclass(frozen=True)
class GradeResult:
    is_correct: bool
    score: float
    feedback: str


async def grade(client: ModelClient, question: Question, user_answer: str) -> GradeResult:
    """Raises ModelError if the model call fails (short answers only)."""
    if not user_answer.strip():
        return GradeResult(False, 0.0, f"No answer given. The answer is: {question.answer_key}")
    if question.question_type == "multiple_choice":
        return _grade_choice(question, user_answer)
    return await _grade_with_model(client, question, user_answer)


def _grade_choice(question: Question, user_answer: str) -> GradeResult:
    if user_answer.strip() == (question.answer_key or "").strip():
        return GradeResult(True, 1.0, "Correct.")
    return GradeResult(False, 0.0, f"Not quite. The answer is: {question.answer_key}")


def build_message(question: Question, user_answer: str) -> str:
    # the student's text only ever appears inside <student_answer>; the prompt says it's data
    return (
        f"TRANSCRIPT\n{question.span_text or ''}\n\n"
        f"QUESTION\n{question.prompt}\n\n"
        f"ANSWER KEY\n{question.answer_key or ''}\n\n"
        f"<student_answer>\n{user_answer}\n</student_answer>"
    )


async def _grade_with_model(client: ModelClient, question: Question, user_answer: str) -> GradeResult:
    response = await client.generate(
        system=PROMPT,
        messages=[Message(role="user", content=build_message(question, user_answer))],
        schema=GRADE_SCHEMA,
    )
    verdict = response.output["verdict"]
    return GradeResult(is_correct=verdict == "correct", score=SCORES[verdict], feedback=response.output["feedback"])
