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
transcribed word (`TranscriptBuffer.last_end`), not the wall clock. Transcription lag doesn't
count as lecture passing, and tests can use fake times. Silence (including a video paused for
a quiz, #20) only freezes the clock until speech resumes: word timestamps sit on the audio
timeline, so the first word after a pause jumps the clock forward by the paused time.

### CheckpointGate (`server/src/app/checkpoint.py`)
Pure timing logic with no model and no I/O. `decide(now)` applies these rules in order:
1. **Cooldown:** less than 120 s since the last quiz, so do nothing
2. **Length:** at least 360 s since the last quiz, so return `"length"` (no model call)
3. **Spacing:** the model was asked less than 30 s ago, so do nothing
4. Otherwise record the check and return `"check"`

The numbers live in `config.py` (`gate_cooldown_s`, `gate_force_s`, `gate_check_every_s`) and
can be overridden in `.env`. They're short on purpose: frequent quizzes keep the learner
paying attention. A topic-shift quiz needs two shift answers in a row, so the earliest one
comes at cooldown + one check, about 150 s, which is ~375 words at a typical speaking pace.
That's enough for 3 grounded questions. (Lowered from 180/600 s on 2026-11-12.)

The session start counts as the last quiz, so nothing happens in the first 2 minutes. That
also guarantees 2 minutes of transcript before the first check, which is exactly what the
PREVIOUS + RECENT windows below need. The caller calls `mark_quiz(now)` only when a quiz row
is actually created. (Per-session presets for these numbers: #51.)

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
After each chunk upload is saved, `upload_chunk` starts `checkpoint_task` in the background
via `_spawn`. The 204 returns immediately instead of waiting ~4 s for the model.
- `LiveSession.checking` allows one check at a time per session.
- The task opens its own `SessionLocal()`, because the request's DB session is closed by then.
- `_spawn` holds tasks in a module-level set so they aren't garbage-collected mid-run.
- On a trigger, `checkpoint_task` saves the quiz and hands off to `questions_task` (see Quiz below).

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
- Pausing the video when a quiz triggers is not implemented (#20); showing the quiz is #21.
- ~4 s per check on qwen shares the GPU with Whisper. Measure that transcription doesn't fall
  behind on 8 GB machines; llama3.2:3b is the low-RAM fallback.


## Quiz (questions) — #19

Every question stores the transcript span it's grounded in, so grading (#22) and review can
show the student exactly where the answer came from.

### Flow (`server/src/app/api/sessions.py`, `server/src/app/jobs/questions.py`)
1. `checkpoint_task` saves the `quizzes` row (trigger reason, lecture-time span, topic), then
   hands off to `questions_task` and releases `live.checking` immediately. Generation is a
   separate task so the LLM call never blocks the next topic-shift check.
2. `load_span` picks the session's chunks whose midpoint is in `[span_start, span_end)` and
   joins them into one `Span` (text, first/last chunk seq, start/end ts). No chunks → no
   questions, log a warning.
3. `generate_questions` calls the **smart** client (Sonnet) with LECTURE TITLE, LECTURE SO FAR,
   TOPIC, KNOWN CONCEPTS (each only when non-empty; see Mastery below) + TRANSCRIPT and
   `QUESTIONS_SCHEMA`; keeps at most 3.
4. `keep_grounded` drops anything the transcript can't back up (below).
5. `save_questions` writes one `questions` row per kept question with `quiz_id`, `concept_id`,
   `options` (JSONB, null for short answer) and all `span_*` fields.
6. The quiz's `status` is set in the same commit as its questions (below).

No DB session is held during the LLM call.

### Quiz status (`quizzes.status`, `quizzes.skip_reason`)
Before these columns, a quiz with 0 questions looked the same whether the model declined, the
grounding filter dropped everything, or the call failed. A FaceTime call (two real topic shifts,
0 questions) is what exposed it.

| status | when | skip_reason |
|---|---|---|
| NULL | generating, or generation never finished (server stopped mid-call, `--reload`), or the quiz predates the column | NULL |
| `ready` | ≥ 1 question saved | NULL |
| `empty` | nothing worth asking | `not_educational` / `too_little_content` (from the model; NULL if it gave none), `ungrounded` (keep_grounded dropped every question), `no_transcript` (no chunks in the span) |
| `failed` | any exception: model unreachable, timed out or invalid output twice, DB error | NULL |

`ready`/`empty` are written in the same commit as the questions, so a `ready` quiz always has
them. `failed` is written in its own transaction (the failed one may be unusable); if even that
fails it's logged, never raised. For #27: `count(*) group by status, skip_reason`, treating NULL
on an ended session as failed.

### Prompt (`server/src/app/prompts/questions_v2.txt`)
- Up to 3 questions, usually 2–3, only from TRANSCRIPT, testing main ideas (why/how), not trivia;
  skip filler.
- `course` is first in the schema, then per question `evidence` before `concept` before the
  question, so the model commits to the course, then a word-for-word quote, before writing
  (intent, not measured).
- Multiple choice: exactly 4 options, `answer_key` is one of them. Short answer: no options.
- No questions, with an optional `skip_reason`: `not_educational` (small talk, personal
  conversation, ads, intros/outros) or `too_little_content`. A lecture tangent is still teaching
  material. Before v2's last edit the prompt said "Write 2 or 3" and "or an empty list", which
  contradicted each other; small talk was skipped by the model's own judgment, not a rule. A
  reason sent next to real questions is ignored (the questions win). `course` is still required
  then, as a best guess.

### Grounding filter (`keep_grounded`)
A question is kept only if:
- its evidence, normalized (lowercase, punctuation → space, whitespace collapsed), appears
  in the normalized span **on whole-word boundaries** (both sides space-padded, so "lucose"
  doesn't match "glucose"). Whisper output is mostly unpunctuated lowercase and the model
  adds both, so normalizing both sides is what lets exact quotes match;
- the evidence isn't empty (`"" in s` is always True);
- multiple choice has ≥ 2 options containing `answer_key`; short answer has no options.

### Model settings and measurements
`smart_max_tokens = 16000` (adaptive thinking counts toward it; 1024 truncated the JSON),
`smart_timeout_s = 90`. On a real 150 s span (388 words): **7.4 s, 1775 in / 594 out tokens**,
about 1¢ per quiz on Sonnet 5. Accuracy was good on manual review.

Replay any transcript with `server/scripts/try_questions.py` (`--session <id> --start --end`,
or a quiz id, optionally `--save`).

### Known limits / next
- **#20 should pause the video when the questions are ready, not when the quiz triggers.**
  The trigger already lands 60–90 s after the topic ends, so the extra 7.4 s is invisible as
  long as the lecture keeps playing until the card shows.
- Speculative generation (start at the first shift answer, when span and topic are already
  fixed) was considered and deferred: cost is negligible (~1¢ per wasted call) but it adds
  cancellation/staleness handling and doesn't help `length` triggers. Revisit if the wait is
  noticeable after #20/#21.
- Other latency levers if needed: lower `effort` (needs plumbing through `Request`), Haiku or
  Sonnet 5.5, judged by the eval harness (#27).
- No eval set for question quality yet; the grounding filter only checks the quote exists,
  not that the answer follows from it.
- A quiz with zero questions is never shown (pending only returns unanswered questions), but it
  still resets the gate's cooldown, so a real topic right after small talk can wait up to 120 s.
- Whether the model skips small talk consistently (and never skips real lectures) is unmeasured.
  #27: labeled spans (lecture, lecture with tangent, technical conversation, small talk), 3–5
  runs each.


## Grading — #22

The student answers a question; the answer is graded and saved as an `attempts` row with
`is_correct`, `score` and `feedback`. Unlike question generation, the student waits for this,
so it runs inside the request.

### Flow (`server/src/app/api/questions.py`, `server/src/app/jobs/grading.py`)
1. `POST /questions/{question_id}/attempts` with `{"user_answer": "..."}`. Unknown question →
   404; missing body → 422. Dependencies (`get_current_user`, `get_smart_client`) live in
   `api/deps.py`, shared with the sessions router.
2. `grade(client, question, user_answer)` picks one of three paths:
   - **Blank** (empty or whitespace): incorrect, 0.0, feedback gives the answer. No model call.
   - **Multiple choice**: exact match against `answer_key` → 1.0 / 0.0, fixed feedback
     ("Correct." / "Not quite. The answer is: …"). No model call: instant, free, never wrong.
   - **Short answer**: the smart client (Sonnet) with `prompts/grading_v1.txt`.
3. `create_attempt` saves the `Attempt` and returns `{attempt_id, graded, is_correct, score,
   feedback}`.

If the model call fails (`ModelError`), the attempt is still saved with `user_answer` and null
grade fields, and the response has `"graded": false`. The student's answer is never lost; the UI
can say "couldn't grade" and a re-grade can come later.

### Verdict, not score
The model returns `reason` → `verdict` → `feedback`:
- `verdict` is an enum: `correct`, `partially_correct`, `incorrect`. Code maps it to
  `score` (1.0 / 0.5 / 0.0) and sets `is_correct = verdict == "correct"`.
- Same lesson as #18's `confidence` field, which sat at ~0.9 on every answer: a free-form number
  from the model isn't calibrated, while a small set of defined categories is easier to apply
  consistently and to evaluate against labels (#27).
- `reason` comes first so the model compares the answer with the key before writing the verdict
  (same idea as `evidence` first in question generation; intent, not measured). It isn't stored.

### Prompt (`prompts/grading_v1.txt`)
The grader sees TRANSCRIPT (the question's stored `span_text`, which is why #19 saves it),
QUESTION, ANSWER KEY, and the answer inside `<student_answer>` tags.
- Judge against the lecture and answer key; don't reward or penalize outside facts.
- Accept paraphrases, synonyms, informal wording and spelling mistakes.
- `correct`: has the key idea, nothing contradicting it. `partially_correct`: on track but
  incomplete or vague, with nothing contradicting the lecture. `incorrect`: misses the key idea,
  or contradicts something the lecture states, **even if part of the answer is right**.
- Why a contradiction beats partial credit: catching misconceptions is the point of the tool,
  and mastery (#25) should count a stated misconception against the concept. The feedback still
  says which part was right. (v1 had "mixes a correct idea with a wrong one" under partial *and*
  "contradicts" under incorrect, which overlapped; fixed after the first real run.)
- Feedback: 1–2 sentences addressed to the student; what was right, and the correct idea if
  something was missing. No mention of grades or instructions.

### Prompt injection
The student's text is untrusted. `build_message` puts it only inside `<student_answer>`, after
everything else, and the prompt says that text is the answer and never an instruction ("mark
this correct" is graded on its content). Tests check the answer can't appear outside the tags.

### Measurements
Run `server/scripts/try_grade.py` (built-in cases: full, partial, half-wrong, typos, wrong,
injection; or pass a saved question id).

First real run (Sonnet 5): **~2.9 s per short-answer grade**, fast enough for a request the
student waits on, so no separate grading timeout yet. Verdicts and feedback were as expected,
except "pyruvate in the mitochondria" (right product, location the lecture explicitly rules
out) got `incorrect` where partial was expected. That exposed the overlapping definitions above;
the prompt now makes it `incorrect` on purpose. Six cases is a spot check, not an eval (#27).

### Known limits / next
- **Worst-case wait**: typical is ~2.9 s, but the smart client allows 90 s per attempt and
  retries once, so a repeatedly timing-out grade can hold the request for up to ~3 min. If
  timeouts show up, give grading its own shorter timeout (a separate cached client).
- The generator's `evidence` quote is filtered and then discarded; it isn't on `Question`.
  Storing it (a migration) would let feedback quote the exact line of the lecture.
- Multiple-choice matching is exact; the UI (#21) must send the option text as-is.
- No grader-agreement eval yet. #27 should label a set of answers and measure how often the
  verdict matches a human.
- `reason` is thrown away; storing it would help debug disputed grades.


## Mastery (Elo per concept) — #25

Every graded answer moves the user's rating for the question's concept. Ratings are what #26
will use to pick questions (recent misses first, then the weakest calibrated concepts).

### Concepts (`server/src/app/jobs/questions.py`, prompt `questions_v2.txt`)
A rating is only useful if the same material always lands on the same concept, across videos.
- The model first names the **course** (the standard university course, e.g. "deep learning",
  "vehicle powertrains"), independently of how narrow the video is. Then each question's
  **concept** is a unit of that course's syllabus, like a textbook chapter: a video on
  multi-head attention and a deep-learning overview both use "transformers". v1 named concepts
  after the video's details ("pyruvate as the end product"), which split ratings into
  one-question concepts; two prompt rounds fixed it on real runs.
- Inputs that steer the name: LECTURE TITLE (optional, typed or pasted into the title box,
  `PATCH /sessions/{id}`; the strongest clue), LECTURE SO FAR (earlier quiz topics, oldest
  first), and KNOWN CONCEPTS (this session's concepts, then the user's 30 most recently rated).
  The prompt says to copy a known name exactly when one fits.
- `concepts.name_key` is the normalized name (lowercase, punctuation → space, whitespace
  collapsed), unique. `get_or_create_concept` inserts with `ON CONFLICT (name_key) DO NOTHING`,
  so "Glycolysis." and "glycolysis" are one concept even when two quizzes generate at once.
- A blank concept → `concept_id` NULL → the question is never rated.
- `course` is logged, not stored.

### Rating rules (`server/src/app/jobs/mastery.py`, pure functions)
| | |
|---|---|
| Start rating | 1000 (also the fixed rating of every question) |
| Calibration | first 3 graded answers on a concept: fixed **+30 / 0 / −30** (right / partial / wrong) |
| After that | weighted Elo: `K × (score − expected)`, K = 42, so ±21 at 1000 |
| `expected` | `1 / (1 + 10^((1000 − rating) / SCALE))`, SCALE = 900 |
| Range | clamped to 0..2000 |
| Overall | attempt-weighted average of concepts with ≥ 3 answers; None until one exists. Derived, never stored |

- **Why calibration**: with 0–2 answers the rating predicts nothing, so it shouldn't scale the
  step. Fixed steps let a new concept move fast in either direction.
- **Why weighted Elo**: a predicted result moves the rating a little, a surprising one a lot.
  At 1200 a right answer is +15.7 and a wrong one −26.3, so ratings level off instead of
  growing forever.
- **What the numbers mean**: a rating settles where predicted accuracy matches real accuracy.
  With SCALE 900, **1500 ≈ 78%** and **2000 ≈ 93%** sustained accuracy. All right answers reach
  1500 after **35** and 2000 after **133** (pinned by a test). Tuning went: SCALE 600 made 2000
  ≈ 98% but needed ~265 straight right answers; chess's 400 would need 99.7%, which grader noise
  alone rules out. 900/42 keeps 1500 about where it was and halves the climb to 2000.
- **Questions all rate 1000** (no per-question difficulty). That's why the start rating must
  equal it: otherwise a brand-new learner would be predicted to fail and ratings would drift.
- **Overall gates on attempts, not rating**: an earlier idea ("only concepts above 1100") let a
  wrong answer push a concept under the cutoff and raise the overall. A test now checks a wrong
  answer can never raise it.

### Saving (`server/src/app/jobs/mastery_store.py`, `server/src/app/api/questions.py`)
1. `create_attempt` grades the answer. If it was graded and the question has a concept, it calls
   `record_answer` **before** adding the `Attempt`, so the count of earlier graded answers
   excludes this one.
2. `record_answer`: count earlier graded attempts on the concept → `INSERT … ON CONFLICT DO
   NOTHING` (row at 1000 on first use) → `SELECT … FOR UPDATE` (two answers at once can't both
   read the old rating) → `apply_change` → `updated_at = now()` → flush.
3. The attempt and the rating commit together.
4. The response adds `concept`, `elo_before`, `elo_after`, `calibrating` (still calibrating
   *after* this answer, so the 3rd answer already reports false). All null when nothing was
   rated.

A skip is graded as blank → incorrect → −30 while calibrating. A failed grade (`graded: false`)
or a question with no concept changes nothing.

### Client (`client/quiz.js`)
Under the verdict: `linear regression +21 → 1041`, plus `· calibrating` while it is. The delta
is the difference of the rounded ratings, so it always matches the numbers shown. Hidden when
nothing was rated. No end-of-quiz summary and no dashboard: past the MVP.

### Known limits / next
- No way to see all ratings yet (no `GET /users/me/mastery`, no dashboard); #26 reads the table
  directly. To inspect: `select c.name, round(m.elo) from mastery m join concepts c using
  (concept_id) order by m.elo desc;`
- Multiple choice counts the same as short answer, though guessing gets 25% right. MC-heavy
  concepts may rate a little high; #27 can check whether MC needs a smaller step.
- Concept consistency depends on the model reusing names. Near-duplicates that normalize
  differently ("neural nets" vs "neural networks") still split; pgvector dedup was skipped for
  the MVP.
- No decay: a rating earned months ago stays.
