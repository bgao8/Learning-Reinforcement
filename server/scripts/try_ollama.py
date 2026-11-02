"""Throwaway: grade one answer with a local Ollama model through ModelClient."""
import asyncio

from app.jobs.grading import GRADE_SCHEMA
from app.llm.client import ModelClient
from app.llm.providers.ollama import OllamaProvider
from app.llm.types import Message


async def main():
    client = ModelClient(provider=OllamaProvider(), model="llama3.2:3b")
    r = await client.generate(
        system="You grade quiz answers. score is 0.0-1.0. feedback is 1-2 sentences.",
        messages=[Message(
            role="user",
            content="Question: What do mitochondria produce?\nAnswer key: ATP\nStudent answer: ATP",
        )],
        schema=GRADE_SCHEMA,
    )
    print("output:  ", r.output)
    print("attempts:", r.attempts)
    print("latency: ", round(r.latency_ms), "ms")


asyncio.run(main())