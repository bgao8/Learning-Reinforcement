### What the model will be doing

**Job:** Topic-shift / checkpoint detection
**Issue:** #18
**Input → output:** recent transcript → shift, confidence, reason → a quizzes row with trigger_reason
**LLM?:** yes, but only after a cheap code gate
**Model tier:** local, small (e.g. a ~3B model via Ollama / MLX)

**Trigger:** every new batch of transcript (~every 30 s of speech)
**Gate:** code, before any model call
- skip if less than ~3 min of transcript since the last quiz (cooldown)
- force a checkpoint if more than ~10 min since the last quiz, with trigger_reason "length" (no model call)
- otherwise ask the model
**Input:** a short summary or tail of the previous segment + the last ~60 s of transcript
**Output schema:** shift (bool), confidence (0–1), reason (one sentence)
- code decides: shift and confidence ≥ threshold → checkpoint with trigger_reason "topic_shift"
**Latency budget:** ~2 s. Runs in the background, but has to keep up with incoming transcript.
**Tools:** none
**On failure:** local model down or invalid output
- fall back to length-only checkpoints (no API fallback: this runs too often to pay for)
- log a trace
────────────────────────────────────────
**Job:** Concept extraction
**Issue:** #23
**Input → output:** transcript span → list of {name, description}
**LLM?:** yes
**Model tier:** local or Claude (an eval question)
────────────────────────────────────────
**Job:** Concept dedup
**Issue:** #24
**Input → output:** new concept → match an existing concepts row, or create one
**LLM?:** embeddings, plus maybe an LLM judge for borderline matches
**Model tier:** local embeddings
────────────────────────────────────────
**Job:** Question generation
**Issue:** #19
**Input → output:** span, concept, mastery and preferences → questions row with span_* fields
**LLM?:** yes
**Model tier:** Claude Sonnet 5 (question quality and grounding are the product; worst place to save money)

**Trigger:** topic-shift detector (#18) fires → backend generates the question in the background → only when it's ready (and passes the grounding check) does the client pause the video. The user never watches a paused video wait on generation.
**Input:** all preloaded by code, every call
- transcript chunks since the last quiz, each labeled with its seq number (e.g. [42] ...text...)
- target concept(s): the user's weak concepts from mastery (#26)
- users.preferences (preferred question styles)
- the session's recent questions, so it doesn't repeat itself
**Output schema:** model vs. code
- model: prompt, answer_key, question_type, options (MC only), span_start_chunk, span_end_chunk, span_text (a verbatim quote), concept_name
- code: span_start_ts / span_end_ts (looked up from the chunk rows; the model never sees timestamps), concept_id (resolved from concept_name; the model never sees UUIDs), session_id, quiz_id
**Grounding check:** code, after the call
- span_text must appear in the text of chunks span_start_chunk - span_end_chunk, compared after normalizing case/whitespace/punctuation, with a fuzzy match (~90% similarity) to tolerate tiny rewordings
- chunk range must be within the transcript the model was given
- fail → retry once with the failure reason in the prompt → still fails → no question
**Latency budget:** ~5 s soft, 10 s hard timeout. Runs in the background, so it can be slower than grading; it only delays when the pause happens.
**Tools:** none for MVP; single call, everything preloaded (tutor needs the same data every time, so tools would only add round trips). Candidate later: get_transcript_span(start, end) for references to earlier material, if evals (#27) show questions failing on those.
**On failure:** timeout, API error, invalid JSON, grounding check fails after 1 retry
- don't pause the video; skip this checkpoint and log a trace
- the next checkpoint tries again with the accumulated transcript
- never show an ungrounded question
────────────────────────────────────────
**Job:** Grading
**Issue:** #22
**Input → output:** question, answer key, user answer, span → is_correct, score, feedback
**LLM?:** yes
**Model tier:** Claude Sonnet 5

**Trigger:** renderer -> FastAPI endpoint -> grader
**Input:** questions, answer key, user answer, transcript span
**Output schema:** is_correct, score (can give half-points for partial credit)
**Latency budget:** 3000ms
**Tools:** none
**On failure:** show answer key, let user self-grade. Elo won't be affected on failure.
────────────────────────────────────────
**Job:** Adaptive targeting
**Issue:** #26
**Input → output:** mastery + users.preferences → which concepts and question styles to use
**LLM?:** no: a database query and code that builds the prompt
**Model tier:** –
────────────────────────────────────────
**Job:** Elo update
**Issue:** #25
**Input → output:** grade → new mastery.elo
**LLM?:** no: a math formula
**Model tier:** –
────────────────────────────────────────
**Job:** Transcription
**Issue:** #15
**Input → output:** audio → text
**LLM?:** -
**Model tier:** local Whisper

## Framework decisions

1. **Single calls are first-class.** The agent loop (#11) is built on top of single calls. No MVP job requires tools.
2. **Async.** Every model call is async (FastAPI backend, background jobs).
3. **Structured output:** one Pydantic schema per job. Validate the response; on failure, retry once with the validation error in the prompt; then raise.
4. **Per-job config:** model tier, timeout, and retry count live in config per job, not hardcoded.
5. **Typed errors:** the client raises ModelTimeout, ModelUnavailable, or InvalidOutput. Callers choose the fallback. Never invent a result.
6. **The model outputs only what it saw.** Code computes derived and lookup fields (is_correct, ids, timestamps, checkpoint decisions).
7. **Tracing (#12):** one agent_traces row per model call, including retries and failures. Payload: job, model, prompt version, input, output, tokens, latency, error.
8. **Embeddings get a separate interface** (Embedder), not part of generate.
9. **No streaming for MVP:** no job shows text to the user as it generates.
10. **Prompts are versioned files;** the version id is recorded in every trace so evals (#27) can compare prompt versions.

## Open questions
- Which local model for #18 (decide by evals)
- Fuzzy-match threshold for the grounding check
- Cooldown / max-length values for checkpoints (tune on real lectures)
- Capability flags vs. lowest common denominator for local models
