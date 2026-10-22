"""Throwaway: grade one answer with Claude, then validate the reply."""

import anthropic

from app.jobs.grading import GRADE_SCHEMA
from app.llm.schema import validate
from app.config import settings

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

response = client.messages.create(
    model="claude-sonnet-5",
    max_tokens=1024,
    system="You grade quiz answers against a lecture excerpt. "
        "score is 0.0-1.0 (partial credit allowed). feedback is 1-2 sentences.",
    messages=[{
        "role": "user",
        "content": (
            "Lecture excerpt: Mitochondria produces ATP through cellular respiration," 
            " therefore it can be seen as the powerhouse of the cell.\n"
            "Question: What do mitochondria produce?"
            "Answer key: ATP\n"
            "Student answer: Mitochondria is the powerhouse of the cell\n"
        ),
    }],
    output_config={"format": {"type": "json_schema", "schema": GRADE_SCHEMA}},
)

# text is the first text block since API response can contain other data
for b in response.content:
    if b.type == "text":
        text = b.text
        break

# test that output text is valid JSON format
data = validate(text, GRADE_SCHEMA)

print("Raw text: ", text)
print("Stop: ", response.stop_reason)
print("Input tokens: ", response.usage.input_tokens, "| Output tokens: ", response.usage.output_tokens)
print("Validated:", data)