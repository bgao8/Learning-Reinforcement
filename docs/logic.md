## Transcription
- Look at ScreenCaptureKit output, run through Whisper
- Run Whisper locally on Apple Silicon first (whisper.cpp / faster-whisper / mlx-whisper); Whisper API as fallback
- Whisper wants 16 kHz mono: resample from the AudioContext rate (usually 48 kHz)


## Checkpoints (when to quiz) — #18

A **checkpoint** is a moment where a quiz should happen. There are two kinds, saved as a
`quizzes` row with `trigger_reason`:
- `topic_shift`: the lecture moved on to a new topic, so quiz the one that just ended
- `length`: too long without a quiz, so quiz anyway (a safety net for single-topic lectures and missed shifts)

Writing the actual questions is #19. This part only decides *when*.

### Time
All timing uses **lecture time**: seconds since recording started, taken from the newest
transcribed word (`TranscriptBuffer.last_end`), not the wall clock. Transcription lag, paused
videos and silence don't count as lecture passing, and tests can use fake times.

### CheckpointGate (`server/src/app/checkpoint.py`)
Pure timing logic with no model and no I/O. `decide(now)` applies these rules in order:
1. **Cooldown:** less than 180 s since the last quiz, so do nothing
2. **Length:** at least 600 s since the last quiz, so return `"length"` (no model call)
3. **Spacing:** the model was asked less than 30 s ago, so do nothing
4. Otherwise record the check and return `"check"`

The session start counts as the last quiz, so nothing happens in the first 3 minutes. That
also guarantees 2 minutes of transcript before the first check. The caller calls
`mark_quiz(now)` only when a quiz row is actually created. (Per-session presets for these
numbers: #51.)

### What the model sees
- **PREVIOUS:** transcript from 1–2 min ago (`buffer.between(now-120, now-60)`)
- **RECENT:** the last minute (`buffer.last(60)`)
- **TOPIC SO FAR:** a short label for what the lecture has been about (absent on the first check)

The model gets raw transcript rather than its own earlier output, so one bad answer can't
compound. TOPIC SO FAR is the one exception: a single label that code only changes on a
*confirmed* shift. It exists because without it the model had no context. In a car review it
flagged every passing mention of another car as a new topic.

If either slice is empty (a silent minute), the check is skipped.

### How it decides (`server/src/app/topic_shift.py`, prompt `prompts/topic_shift_v4.txt`)
- The model names `previous_topic` and `recent_topic`, then picks **one relation** from a fixed enum:
  `new_concept`, `different_subject` (→ shift) or `more_detail`, `example`, `tangent`,
  `recap`, `housekeeping` (→ no shift).
- **Code, not the model, maps relation to shift.** With a bare true/false the model used its
  own idea of "shift" and flagged examples, stories and announcements. Choosing from our
  categories forces it to use our definition.
- **Two shift answers in a row** are required before a quiz. A real shift persists into the
  next check (30 s later); a passing mention doesn't. The first shift answer only sets
  `pending_shift`, and any no-shift answer clears it.
- On a confirmed shift, TOPIC SO FAR becomes the new `recent_topic`. The first check seeds it
  with `previous_topic`.
- If the model call fails (Ollama down, timeout, invalid JSON), log it and skip this round.
  Recording is never affected.

### Runtime wiring (`server/src/app/api/sessions.py`)
After each chunk upload is saved, `upload_chunk` starts `checkpoint_task` with
`asyncio.create_task`. The 204 returns immediately instead of waiting ~4 s for the model.
- `LiveSession.checking` allows one check at a time per session.
- The task opens its own `SessionLocal()`, because the request's DB session is closed by then.
- Tasks are held in a module-level set so they aren't garbage-collected mid-run.

### Model choice and evaluation
Topic shift uses the local **fast** client (Ollama, `temperature: 0`), currently `qwen2.5:7b`.
This is the small-local-model side of the hybrid split.

Prompts are scored with `server/scripts/eval_topic_shift.py` against
`server/evals/topic_shift.jsonl`: 20 hand-labeled PREVIOUS/RECENT pairs, 10 shift and
10 no-shift, covering hard shifts, subtopics, signposted and unsignposted shifts, more detail,
examples, tangents, a recap, housekeeping, and a "next step" false signpost. **Precision
matters most**, because a false shift interrupts the lecture, while a missed one is covered by
the `length` quiz.

| Prompt | Model | Precision | Recall | Mean latency |
|---|---|---|---|---|
| v1: shift true/false + confidence | llama3.2:3b | 0.59 | 1.00 | ~1.3 s |
| v2: + topics, stricter rules | llama3.2:3b | 0.71 | 1.00 | ~1.3 s |
| v2 | qwen2.5:7b | 0.53 | 1.00 | — |
| v3: relation enum, code decides | llama3.2:3b | 0.90 | 0.90 | 2.1 s |
| v3 | qwen2.5:7b | 1.00 | 1.00 | 3.9 s |
| v4: + TOPIC SO FAR | qwen2.5:7b | 0.90 | 0.90 | 3.8 s |

Lessons:
- A bigger model is not automatically better. qwen did worse than llama on v2 and best on v3.
- `confidence` was useless: it was ~0.9 on almost every answer, right or wrong. It was removed.
- Prompt examples must not reuse eval cases. The v3 numbers are from after replacing leaked examples.
- v4 scores slightly lower on this set because none of these cases has a TOPIC SO FAR, so the
  anchor's benefit doesn't show here. In manual testing on a real car review, v4 plus the
  two-in-a-row rule fixed the "passing mention of another car" false shifts.

### Known limits / next
- The eval set is small (each case is 5–10 points) and the prompts were partly tuned on it.
  Add held-out cases from real transcripts, including car-review-style comparisons with a
  `topic_so_far` field.
- A quiz row records only `triggered_at` (wall clock) and `trigger_reason`, not which span of
  the lecture or which topic it covers. #19 needs both (a migration: lecture-time start/end, topic).
- Pausing the video when a quiz triggers is not implemented (#20); showing the quiz is #21.
- ~4 s per check on qwen shares the GPU with Whisper. Measure that transcription doesn't fall
  behind on 8 GB machines; llama3.2:3b is the low-RAM fallback.


## Quiz
- How to extract from logic base
- Prompt
