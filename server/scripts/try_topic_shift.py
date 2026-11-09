"""Run detect_shift on real Ollama and print what the model says."""
import asyncio
import time

from app.llm import make_client
from app.topic_shift import detect_shift

CASES = {
    "biology -> economics (shift)": (
        "The electron transport chain pumps protons across the inner mitochondrial membrane, "
        "and ATP synthase uses that gradient to produce most of the cell's ATP.",
        "Okay, now let's switch gears completely and talk about supply and demand. "
        "The demand curve slopes downward because as price rises, consumers buy less.",
    ),
    "more glycolysis detail (no shift)": (
        "First, glycolysis splits one glucose molecule into two molecules of pyruvate in the cytoplasm.",
        "In glycolysis the cell spends two ATP up front, then gets four back, "
        "so the net gain is two ATP plus two NADH per glucose.",
    ),
}


async def main():
    client = make_client("fast")
    for name, (previous, recent) in CASES.items():
        for run in range(3):
            start = time.perf_counter()
            result = await detect_shift(client, previous, recent)
            seconds = time.perf_counter() - start
            print(f"{name:36s} run {run}  shift={result.shift!s:5} "
                f"{result.relation:<17} {seconds:.2f}s  {result.reason}")


asyncio.run(main())