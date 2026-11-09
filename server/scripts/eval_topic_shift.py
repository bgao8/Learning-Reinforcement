"""Score the topic-shift prompt against the labeled cases in evals/topic_shift.jsonl.

Run from server/ with the venv active and Ollama running:
    python scripts/eval_topic_shift.py
"""

import asyncio
import json
import time
from pathlib import Path

from app.config import settings
from app.llm import make_client
from app.topic_shift import detect_shift

CASES = Path(__file__).parent.parent / "evals" / "topic_shift.jsonl"


def ratio(num: int, den: int) -> float:
    return num / den if den else 0.0


async def main():
    client = make_client("fast")
    cases = [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]

    print(f"model={settings.fast_model}  cases={len(cases)}\n")

    tp = fp = fn = tn = 0
    misses = []
    times = []

    for case in cases:
        start = time.perf_counter()
        result = await detect_shift(client, case["previous"], case["recent"], case.get("topic_so_far"))
        times.append(time.perf_counter() - start)
        predicted, expected = result.shift, case["shift"]

        if predicted and expected:
            tp += 1
        elif predicted and not expected:
            fp += 1
        elif not predicted and expected:
            fn += 1
        else:
            tn += 1

        mark = "ok  " if predicted == expected else "MISS"
        print(f"{mark} {case['id']:<24} {case['kind']:<15} pred={predicted!s:<5} {result.relation:<17} {times[-1]:.2f}s")
        if predicted != expected:
            misses.append((case, result))

    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    accuracy = ratio(tp + tn, len(cases))

    print(f"\nTP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"precision={precision:.2f}  recall={recall:.2f}  accuracy={accuracy:.2f}")
    print(f"latency: mean={sum(times) / len(times):.2f}s  max={max(times):.2f}s")

    if misses:
        print("\nWrong cases:")
        for case, result in misses:
            label = "shift" if case["shift"] else "no shift"
            print(f"- {case['id']} ({case['kind']}, expected {label}, got {result.relation})")
            print(f"    topics: {result.previous_topic!r} -> {result.recent_topic!r}")
            print(f"    reason: {result.reason}")


if __name__ == "__main__":
    asyncio.run(main())
