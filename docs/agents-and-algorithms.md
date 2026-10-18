### What the model will be doing

**Job:** Topic-shift / checkpoint detection
**Issue:** #18
**Input → output:** recent transcript → {shift: bool, reason} → a quizzes.trigger_reason row
**LLM?:** yes
**Model tier:** local, small
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
**Model tier:** Claude
────────────────────────────────────────
**Job:** Grading
**Issue:** #22
**Input → output:** question, answer key, user answer, span → is_correct, score, feedback
**LLM?:** yes
**Model tier:** Claude
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