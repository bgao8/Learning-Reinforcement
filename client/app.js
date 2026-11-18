// Frizz overlay UI (#59). One state machine renders either the collapsed pill or the expanded
// panel (session, quiz, results).
//
// Real mode (in Electron): capture and the session API come from renderer.js, quiz data from
// quiz.js, pause/resume from media.js. Demo mode (a plain browser, or ?demo / ?preset=<name>)
// runs on built-in data, so every screen can be designed and screenshotted without the audio
// pipeline or the server. Presets: idle, empty, listening, title, session, stopped, ended,
// waiting, question, answered, short, graded, done. Add &ct=1 to see the click-through style.
//
// Rendering rebuilds #root from template strings in render(), the only place innerHTML is
// used. Every string from the server, the model or the user goes through esc(); the only raw
// markup is ICON and the templates themselves.

(function () {
    "use strict"

    // ------------------------------------------------------------ demo data

    const DEMO_QUIZ = {
        topic: "Training neural networks",
        questions: [
            {
                question_id: "q1", question_type: "multiple_choice",
                prompt: "What does the learning rate control in gradient descent?",
                options: ["How many layers the network has", "How big each weight update is", "How many examples are in a batch", "Which activation function is used"],
            },
            {
                question_id: "q2", question_type: "multiple_choice",
                prompt: "What does backpropagation compute?",
                options: ["The model's final predictions", "The best learning rate to use", "The gradient of the loss for every weight", "Which neurons to drop"],
            },
            {
                question_id: "q3", question_type: "short_answer",
                prompt: "In one sentence: why does an overfit model do worse on new data?",
                options: null,
            },
        ],
    }

    // demo only: what the server knows about each question (never sent to the real client)
    const DEMO_ANSWERS = {
        q1: { key: "How big each weight update is", concept: "gradient descent" },
        q2: { key: "The gradient of the loss for every weight", concept: "neural networks" },
        q3: {
            key: "It memorized noise in the training data instead of patterns that generalize.",
            concept: "model evaluation",
            words: ["memor", "noise", "general"],
            right: "Right: it fit the noise in its training data, and noise doesn't carry over to new data.",
            partial: "On track. Say why: it learned noise specific to the training data, which doesn't generalize.",
        },
    }

    // demo ratings before this quiz: one calibrated concept, one new, one on its last calibration answer
    const demoRatings = { "gradient descent": 1084, "neural networks": 1000, "model evaluation": 958 }
    const demoSeen = { "gradient descent": 5, "neural networks": 0, "model evaluation": 2 }

    const DEMO_TOPICS = [
        { name: "Gradient descent", time: "2:31", score: "3/3" },
        { name: "Backpropagation", time: "8:40", score: "2/3" },
        { name: "Training neural networks", time: "14:15", score: null },
    ]

    // the same rules as server/src/app/jobs/mastery.py, so demo numbers look real
    function demoGrade(q, answer) {
        const d = DEMO_ANSWERS[q.question_id]
        let score = 0
        if (q.question_type === "multiple_choice") {
            score = answer === d.key ? 1 : 0
        } else if (answer.trim()) {
            const hits = d.words.filter((w) => answer.toLowerCase().includes(w)).length
            score = hits >= 2 ? 1 : hits === 1 ? 0.5 : 0
        }
        let feedback
        if (q.question_type === "multiple_choice") feedback = score ? "Correct." : `Not quite. The answer is: ${d.key}`
        else feedback = score === 1 ? d.right : score > 0 ? d.partial : `The answer: ${d.key}`

        const seen = demoSeen[d.concept]
        const before = demoRatings[d.concept]
        const expected = 1 / (1 + 10 ** ((1000 - before) / 900))
        const after = seen < 3 ? before + 60 * (score - 0.5) : before + 42 * (score - expected)
        demoRatings[d.concept] = after
        demoSeen[d.concept] = seen + 1
        return {
            graded: true, is_correct: score === 1, score, feedback, answer_key: d.key,
            concept: d.concept, elo_before: before, elo_after: after, calibrating: seen + 1 < 3,
        }
    }

    // ------------------------------------------------------------ state

    const BASE = {
        expanded: false,
        rec: false,
        busy: false,          // starting or stopping: the record buttons are disabled
        error: "",
        view: "session",      // session | quiz | done
        topics: [],           // one row per quiz this session: { name, time, score }
        title: "",            // optional video title (#25)
        titleSaved: false,
        titleSaving: false,
        titleError: "",
        topic: "",            // the open quiz's topic
        quiz: [],             // its questions, from GET /sessions/{id}/questions/pending
        quizRow: -1,          // its row in topics
        q: 0,
        picked: null,         // the option text picked (multiple choice)
        text: "",             // the typed answer (short answer)
        grading: false,
        checked: false,       // the current question has a result
        result: null,         // its attempt; null after a check means the server couldn't be reached
        results: [],          // [{ question, attempt, answer }] for the questions answered so far
        ct: false,            // click-through is on
    }

    const params = new URLSearchParams(location.search)
    const DEMO = !window.api || params.has("demo") || params.has("preset")
    const log = (msg) => (window.api ? window.api.log(msg) : console.log(msg))

    // demo presets: each builds its state when chosen, so the demo ratings start fresh
    const A = [
        "How many layers the network has",          // q1, wrong
        "The gradient of the loss for every weight",  // q2, right
        "It memorizes the training data, noise included, so it doesn't generalize.",   // q3, right
    ]
    const T = (n) => DEMO_TOPICS.slice(0, n)

    function quizAt(q, answers) {
        const results = answers.map((answer, i) => {
            const question = DEMO_QUIZ.questions[i]
            return { question, attempt: demoGrade(question, answer), answer }
        })
        return {
            view: "quiz", topic: DEMO_QUIZ.topic, quiz: DEMO_QUIZ.questions, quizRow: 2,
            q, results, picked: null, text: "", checked: false, result: null,
        }
    }

    function answeredAt(q, answers) {
        const state = quizAt(q, answers)
        const last = state.results[state.results.length - 1]
        const mc = last.question.question_type === "multiple_choice"
        return Object.assign(state, {
            checked: true, result: last.attempt, picked: mc ? last.answer : null, text: mc ? "" : last.answer,
        })
    }

    const PRESETS = {
        idle: () => ({}),
        empty: () => ({ expanded: true }),
        listening: () => ({ rec: true }),
        title: () => ({ expanded: true, rec: true, title: "Stanford CS229: Lecture 4" }),
        session: () => ({ expanded: true, rec: true, titleSaved: true, title: "Stanford CS229: Lecture 4", topics: T(2) }),
        stopped: () => ({ topics: T(3) }),
        ended: () => ({ expanded: true, titleSaved: true, title: "Stanford CS229: Lecture 4", topics: T(3) }),
        waiting: () => Object.assign({ rec: true, topics: T(3) }, quizAt(1, A.slice(0, 1))),
        question: () => Object.assign({ expanded: true, rec: true, topics: T(3) }, quizAt(0, [])),
        answered: () => Object.assign({ expanded: true, rec: true, topics: T(3) }, answeredAt(0, A.slice(0, 1))),
        short: () => Object.assign({ expanded: true, rec: true, topics: T(3) }, quizAt(2, A.slice(0, 2)), { text: A[2] }),
        graded: () => Object.assign({ expanded: true, rec: true, topics: T(3) }, answeredAt(2, A)),
        done: () => Object.assign({ expanded: true, rec: true, topics: T(3) }, answeredAt(2, A), { view: "done" }),
    }

    const preset = PRESETS[params.get("preset")]
    let S = Object.assign({}, BASE, preset ? preset() : {})
    if (params.get("ct") === "1") S.ct = true
    let sessionStart = Date.now()
    let timers = []

    const root = document.getElementById("root")

    function set(patch) {
        S = Object.assign({}, S, patch)
        render()
    }

    // ------------------------------------------------------------ helpers

    const esc = (s) => String(s == null ? "" : s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;")

    const svg = (n, body, extra = "") =>
        `<svg width="${n}" height="${n}" viewBox="0 0 24 24" ${extra} aria-hidden="true">${body}</svg>`
    const stroke = (w) => `fill="none" stroke="currentColor" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"`

    const ICON = {
        mic: svg(14, '<path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z"/><path d="M19 11a7 7 0 0 1-14 0"/><path d="M12 18v3"/>', stroke(2)),
        stop: svg(12, '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>'),
        down: svg(14, '<path d="M6 9l6 6 6-6"/>', stroke(2.2)),
        up: svg(14, '<path d="M6 15l6-6 6 6"/>', stroke(2.2)),
        arrow: svg(14, '<path d="M5 12h14M13 6l6 6-6 6"/>', stroke(2.2)),
        check: (n) => svg(n, '<path d="M5 12.5l4.5 4.5L19 7.5"/>', stroke(3)),
        x: (n) => svg(n, '<path d="M7 7l10 10M17 7L7 17"/>', stroke(3)),
        half: (n) => svg(n, '<circle cx="12" cy="12" r="7.5" fill="none" stroke="currentColor" stroke-width="2.6"/><path d="M12 4.5a7.5 7.5 0 0 0 0 15z" fill="currentColor"/>'),
        dash: (n) => svg(n, '<path d="M7 12h10"/>', stroke(3)),
        grip: svg(14, [9, 15].flatMap((x) => [6, 12, 18].map((y) => `<circle cx="${x}" cy="${y}" r="1.7" fill="currentColor"/>`)).join("")),
        logo: (n) => `<svg width="${n}" height="${n}" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="9" fill="var(--accent)"/><path d="M5 10.5c1.5-3 3-3 4.5 0s3 3 4.5 0" stroke="#fff" stroke-width="1.8" fill="none" stroke-linecap="round"/></svg>`,
    }
    const wave = (live) => `<span class="wave ${live ? "live" : "off"}" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>`

    const lastTopic = () => (S.topics.length ? S.topics[S.topics.length - 1].name : "")
    const inQuiz = () => S.view !== "session"
    const remaining = () => S.quiz.length - S.results.length
    const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`
    const fmtElapsed = (ms) => {
        const s = Math.max(0, Math.floor(ms / 1000))
        return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0")
    }

    // how one answer went, for the feedback box and the results rows
    function verdict(attempt, { mc = false, skipped = false } = {}) {
        if (!attempt) {
            return {
                cls: "neutral", icon: ICON.dash, title: "Couldn't reach the server", short: "Not saved",
                body: "Your answer wasn't saved. This question will come back in a later quiz.",
            }
        }
        if (!attempt.graded) {
            return { cls: "neutral", icon: ICON.dash, title: "Couldn't grade this one", short: "Not graded", body: "Your answer was saved." }
        }
        // multiple choice: the marked options already say it all
        const body = mc ? "" : attempt.feedback
        if (attempt.is_correct) return { cls: "ok", icon: ICON.check, title: "Correct", short: "Correct", body }
        if (attempt.score > 0) return { cls: "partial", icon: ICON.half, title: "Partly right", short: "Partly", body }
        return { cls: "miss", icon: ICON.x, title: skipped ? "Skipped" : "Not quite", short: "Review", body }
    }

    // #25: the change from the server's rating, rounded first so the numbers shown always add up
    function ratingChange(attempt) {
        if (!attempt || attempt.elo_after == null) return null
        const before = Math.round(attempt.elo_before)
        const after = Math.round(attempt.elo_after)
        return { delta: after - before, after, calibrating: !!attempt.calibrating }
    }

    function deltaView(delta) {
        const cls = delta > 0 ? "up" : delta < 0 ? "down" : ""
        const text = delta > 0 ? `+${delta}` : delta < 0 ? `−${-delta}` : "±0"
        return `<span class="delta ${cls}">${text}</span>`
    }

    // ------------------------------------------------------------ views

    function recButton(cls) {
        const label = S.rec ? "Stop listening" : "Start listening"
        return `<button type="button" class="${cls}" data-action="toggleRec" aria-label="${label}" title="${label}" ${S.busy ? "disabled" : ""}>${S.rec ? ICON.stop : ICON.mic}</button>`
    }

    function pillView() {
        const idle = !S.rec && !S.topics.length && !inQuiz()
        let main
        if (idle) main = `${ICON.logo(22)}<span class="brand">Frizz</span>`
        else if (inQuiz()) main = `${wave(false)}<span class="pill-topic">${esc(S.topic)}</span>`
        else if (S.rec) main = `${wave(true)}<span class="pill-topic">Listening</span>`
        else main = `${wave(false)}<span class="pill-topic paused">Stopped · ${esc(plural(S.topics.length, "quiz", "quizzes"))}</span>`

        let right
        if (idle) {
            right = `<button type="button" class="btn btn-blue btn-sm" data-action="toggleRec" ${S.busy ? "disabled" : ""}>${ICON.mic}Start listening</button>`
        } else if (inQuiz()) {
            right = S.view === "done"
                ? `<button type="button" class="btn btn-blue btn-sm" data-action="expand">Results</button>`
                : `<button type="button" class="btn btn-blue btn-sm" data-action="expand" aria-label="Back to the quiz, ${plural(remaining(), "question")} left">Quiz <span class="count">${remaining()}</span></button>`
        } else {
            right = recButton("icon-btn round")
        }
        if (!idle) right += `<button type="button" class="icon-btn ghost" data-action="expand" aria-label="Expand">${ICON.down}</button>`

        // the grip is the pill's only drag area: in Electron a drag region swallows clicks, so the
        // rest of the pill stays buttons
        return `<div class="pill glass ${inQuiz() ? "ready" : ""}">
            <div class="grip" title="Drag to move">${ICON.grip}</div>
            <button type="button" class="pill-main" data-action="expand" aria-label="Open Frizz panel">${main}</button>
            ${right}
        </div>`
    }

    function headView() {
        const status = S.rec ? "Listening" : S.topics.length ? "Stopped" : "Off"
        return `<div class="head drag">
            ${ICON.logo(20)}<span class="brand">Frizz</span>
            <span class="status"><span class="dot ${S.rec ? "live" : ""}"></span>${status}</span>
            <span class="spacer"></span>
            ${recButton("icon-btn")}
            <button type="button" class="icon-btn" data-action="collapse" aria-label="Minimize" title="Minimize">${ICON.up}</button>
        </div>`
    }

    function errorView() {
        return S.error ? `<div class="error" role="alert">${esc(S.error)}</div>` : ""
    }

    // optional video title (#25): offered while listening, until saved or the first quiz
    function titleView() {
        if (!S.rec || S.titleSaved || S.topics.length) return ""
        const can = S.title.trim().length > 0 && !S.titleSaving
        return `<div class="card pad">
            <div class="eyebrow">Video title · optional</div>
            <div class="title-row">
                <input id="title-input" type="text" maxlength="300" placeholder="Paste the lecture or video title" value="${esc(S.title)}" ${S.titleSaving ? "disabled" : ""}>
                <button type="button" class="btn btn-white btn-sm" id="title-save" data-action="saveTitle" ${can ? "" : "disabled"}>${S.titleSaving ? "Saving…" : "Save"}</button>
            </div>
            <div class="hint ${S.titleError ? "warn" : ""}">${esc(S.titleError || "Helps name concepts the way a course would.")}</div>
        </div>`
    }

    function sessionView() {
        if (!S.rec && !S.topics.length) {
            return `<div class="body"><div class="stack-12">
                <div class="lead">Ready when you are</div>
                <div class="copy">Play a lecture or video. Frizz listens, notices when the topic changes, and pauses the video for a short quiz.</div>
                <button type="button" class="btn btn-blue btn-lg" data-action="toggleRec" ${S.busy ? "disabled" : ""}>${ICON.mic}Start listening</button>
                ${errorView()}
            </div></div>`
        }

        const heading = S.rec
            ? { eyebrow: "Now", title: S.titleSaved ? S.title : "Listening…" }
            : { eyebrow: "Session ended", title: S.titleSaved ? S.title : plural(S.topics.length, "quiz", "quizzes") }
        const note = S.rec && !S.topics.length ? `<div class="copy">The first quiz comes after a few minutes.</div>` : ""

        const rows = S.topics.map((t) =>
            `<div class="row"><span class="time">${esc(t.time)}</span><span class="name">${esc(t.name)}</span><span class="hint">${esc(t.score || "In progress")}</span></div>`
        ).join("")
        const topics = S.topics.length ? `<div class="card"><div class="eyebrow">Topics this session</div>${rows}</div>` : ""

        const cta = S.rec
            ? `<div class="center-note">Questions appear here as topics wrap up.</div>`
            : `<button type="button" class="btn btn-blue btn-lg" data-action="toggleRec" ${S.busy ? "disabled" : ""}>${ICON.mic}Start a new session</button>`

        return `<div class="body">
            <div class="stack-4"><div class="eyebrow">${heading.eyebrow}</div><div class="title">${esc(heading.title)}</div>${note}</div>
            ${titleView()}${topics}${cta}${errorView()}
        </div>`
    }

    function optionState(label) {
        if (!S.checked) return S.picked === label ? "picked" : ""
        const a = S.result
        if (!a || !a.graded) return label === S.picked ? "picked" : "dim"
        if (label === a.answer_key) return "right"
        return label === S.picked ? "wrong" : "dim"
    }

    function ratingView(attempt) {
        const r = ratingChange(attempt)
        if (!r) return ""
        return `<div class="fb-rating">
            <span class="concept">${esc(attempt.concept)}</span>${deltaView(r.delta)}<span class="to">→ ${r.after}</span>
            ${r.calibrating ? `<span class="tag">calibrating</span>` : ""}
        </div>`
    }

    function quizView() {
        const q = S.quiz[S.q]
        if (!q) return ""
        const n = S.quiz.length
        const mc = q.question_type === "multiple_choice" && Array.isArray(q.options)
        const segs = S.quiz.map((_, i) => {
            const on = i < S.q || (i === S.q && S.checked)
            const cur = i === S.q && !S.checked
            return `<i class="${on ? "on" : cur ? "cur" : ""}"></i>`
        }).join("")

        let input
        if (mc) {
            input = `<div class="options">${q.options.map((label, i) => {
                const st = optionState(label)
                const mark = st === "right" ? ICON.check(12) : st === "wrong" ? ICON.x(12) : "ABCD".charAt(i)
                return `<button type="button" class="opt ${st}" data-action="pick" data-i="${i}" ${S.checked || S.grading ? "disabled" : ""}><span class="mark">${mark}</span><span>${esc(label)}</span></button>`
            }).join("")}</div>`
        } else {
            input = `<label class="answer"><span>Your answer</span>
                <textarea id="answer" placeholder="Type a sentence…" ${S.checked || S.grading ? "disabled" : ""}>${esc(S.text)}</textarea></label>`
        }

        let fb = ""
        if (S.checked) {
            const last = S.results[S.results.length - 1]
            const v = verdict(S.result, { mc, skipped: last && last.answer === "" })
            fb = `<div class="feedback ${v.cls}" role="status">
                <div class="fb-title">${v.icon(14)}${esc(v.title)}</div>
                ${v.body ? `<div class="fb-body">${esc(v.body)}</div>` : ""}
                ${ratingView(S.result)}
            </div>`
        }

        let actions
        if (S.checked) {
            actions = `<span></span><button type="button" class="btn btn-blue" data-action="next">${S.q < n - 1 ? "Next" : "See results"} ${ICON.arrow}</button>`
        } else if (mc) {
            actions = `<button type="button" class="btn btn-white" data-action="skip" ${S.grading ? "disabled" : ""}>Skip</button>
                <span class="hint">${S.grading ? "Checking…" : "Pick one to check"}</span>`
        } else {
            const can = S.text.trim().length > 0 && !S.grading
            actions = `<button type="button" class="btn btn-white" data-action="skip" ${S.grading ? "disabled" : ""}>Skip</button>
                <span class="right"><span class="hint">Enter ↵</span>
                <button type="button" class="btn btn-blue" id="check-btn" data-action="checkShort" ${can ? "" : "disabled"}>${S.grading ? "Checking…" : "Check"}</button></span>`
        }

        return `<div class="body">
            <div class="stack-8">
                <div class="meta"><span class="eyebrow">${esc(S.topic)}</span><span class="hint">${S.q + 1} / ${n}</span></div>
                <div class="progress" aria-hidden="true">${segs}</div>
            </div>
            <div class="question">${esc(q.prompt)}</div>
            ${input}${fb}
            <div class="actions">${actions}</div>
        </div>`
    }

    function doneView() {
        const n = S.results.length
        const right = S.results.filter((r) => r.attempt && r.attempt.is_correct).length
        const msg = right === n ? "Perfect run" : right >= n - 1 ? "Solid, one to review" : "Worth another pass"
        const rows = S.results.map(({ question, attempt, answer }) => {
            const v = verdict(attempt, { mc: question.question_type === "multiple_choice", skipped: answer === "" })
            const r = ratingChange(attempt)
            const end = r
                ? `${deltaView(r.delta)}<span class="to">→ ${r.after}</span>`
                : `<span class="hint">${v.short}</span>`
            return `<div class="row"><span class="res-icon ${v.cls}">${v.icon(11)}</span>
                <span class="name">${esc((attempt && attempt.concept) || S.topic)}</span><span class="row-end">${end}</span></div>`
        }).join("")
        return `<div class="body">
            <div class="score-row">
                <div class="stack-4"><span class="eyebrow">Quiz complete</span><span class="lead">${msg}</span></div>
                <span class="score">${right}/${n}</span>
            </div>
            <div class="card"><div class="eyebrow">Mastery</div>${rows}</div>
            <button type="button" class="btn btn-blue btn-lg" data-action="finish">${S.rec ? "Back to listening" : "Done"} ${ICON.arrow}</button>
        </div>`
    }

    function panelView() {
        const body = S.view === "quiz" ? quizView() : S.view === "done" ? doneView() : sessionView()
        return `<section class="panel glass" aria-label="Frizz">
            ${headView()}
            ${body}
            <div class="foot"><kbd>⌘</kbd><kbd>⇧</kbd><kbd>K</kbd>
                <span>${S.ct ? "Click-through on: clicks pass to the apps below" : "to toggle click-through"}</span></div>
        </section>`
    }

    const KEEP_FOCUS = ["answer", "title-input"]

    function render() {
        const active = document.activeElement
        const keep = active && KEEP_FOCUS.includes(active.id) ? active.id : null
        document.body.classList.toggle("ct", S.ct)
        root.innerHTML = S.expanded ? panelView() : pillView()

        // a rebuild drops focus: give it back to the field being typed in, or to the next step
        const field = keep && document.getElementById(keep)
        if (field && !field.disabled) {
            field.focus()
            field.setSelectionRange(field.value.length, field.value.length)
        } else if (S.expanded && S.view === "quiz") {
            const target = S.checked ? root.querySelector('[data-action="next"]') : document.getElementById("answer")
            if (target && !target.disabled) target.focus()
        }
    }

    // ------------------------------------------------------------ actions

    function clearTimers() {
        timers.forEach(clearTimeout)
        timers = []
    }

    function later(ms, fn) {
        timers.push(setTimeout(fn, ms))
    }

    async function startListening() {
        // a new session: forget the last one's topics and title, and open the panel for the title box
        set({ busy: true, error: "", expanded: true, topics: [], title: "", titleSaved: false, titleError: "" })
        if (DEMO) {
            sessionStart = Date.now()
            set({ busy: false, rec: true })
            later(4000, () => openQuiz(DEMO_QUIZ.topic, DEMO_QUIZ.questions))
            return
        }
        await start()   // renderer.js: logs its own errors and leaves no session on failure
        if (currentSessionId()) {
            sessionStart = Date.now()
            log("Recording started")
            set({ busy: false, rec: true })
        } else {
            log("Recording failed to start")
            set({ busy: false, error: "Couldn't start listening. Is the server running, and is screen recording allowed?" })
        }
    }

    async function stopListening() {
        set({ busy: true })
        clearTimers()
        if (!DEMO) {
            await stop()   // renderer.js: flushes the last audio and ends the session
            log("Recording stopped")
        }
        set({ busy: false, rec: false })
    }

    function toggleRec() {
        if (S.busy) return
        return S.rec ? stopListening() : startListening()
    }

    // push, not pull: a ready quiz opens on its own and pauses the video, so it can't be ignored
    function openQuiz(topic, questions) {
        quiz.open = true
        const name = topic || "Quick check"
        set({
            expanded: true, view: "quiz", topic: name, quiz: questions,
            topics: S.topics.concat([{ name, time: fmtElapsed(Date.now() - sessionStart), score: null }]),
            quizRow: S.topics.length,
            q: 0, picked: null, text: "", grading: false, checked: false, result: null, results: [],
        })
        if (!DEMO) {
            window.api.quizShown()   // main turns click-through off and focuses the window
            quiz.onQuizShown()       // media.js pauses the video
        }
    }

    // every answer goes to the server, multiple choice included, so grading and ratings stay there
    async function submit(answer) {
        const q = S.quiz[S.q]
        if (!q || S.checked || S.grading) return
        set({ grading: true, picked: q.question_type === "multiple_choice" ? answer : null })
        let attempt
        if (DEMO) {
            await new Promise((done) => setTimeout(done, q.question_type === "multiple_choice" ? 250 : 900))
            attempt = demoGrade(q, answer)
        } else {
            attempt = await postAttempt(q.question_id, answer)
        }
        set({ grading: false, checked: true, result: attempt, results: S.results.concat([{ question: q, attempt, answer }]) })
    }

    function next() {
        if (S.q < S.quiz.length - 1) {
            set({ q: S.q + 1, picked: null, text: "", grading: false, checked: false, result: null })
            return
        }
        const right = S.results.filter((r) => r.attempt && r.attempt.is_correct).length
        const topics = S.topics.slice()
        if (topics[S.quizRow]) topics[S.quizRow] = Object.assign({}, topics[S.quizRow], { score: `${right}/${S.results.length}` })
        set({ view: "done", topics })
    }

    // results screen → back to the video
    async function finish() {
        quiz.open = false
        set({ view: "session", expanded: false, quiz: [], results: [], checked: false, result: null, picked: null, text: "" })
        if (DEMO) {
            if (S.rec) later(8000, () => openQuiz(DEMO_QUIZ.topic, DEMO_QUIZ.questions))
            return
        }
        await pollPending()                  // another quiz may already be waiting...
        if (!quiz.open) quiz.onQuizDone()    // ...if so, stay paused through it
    }

    async function saveTitle() {
        const title = S.title.trim()
        const sessionId = DEMO ? "demo" : currentSessionId()
        if (!title || S.titleSaving || !sessionId) return
        set({ titleSaving: true, titleError: "" })
        try {
            if (!DEMO) await saveSessionTitle(sessionId, title)
            log(`title saved: ${title}`)
            set({ titleSaving: false, titleSaved: true, title })
        } catch (err) {
            log(err.message)
            set({ titleSaving: false, titleError: "Couldn't save the title. Try again." })
        }
    }

    const ACTIONS = {
        expand: () => set({ expanded: true }),
        collapse: () => set({ expanded: false }),
        toggleRec,
        saveTitle,
        pick: (el) => {
            const q = S.quiz[S.q]
            if (q && q.options) submit(q.options[Number(el.dataset.i)])
        },
        checkShort: () => { if (S.text.trim()) submit(S.text.trim()) },
        skip: () => submit(""),   // graded as blank: wrong, and the feedback gives the answer
        next,
        finish,
    }

    root.addEventListener("click", (e) => {
        const el = e.target.closest("[data-action]")
        if (!el || el.disabled) return
        const fn = ACTIONS[el.dataset.action]
        if (fn) fn(el)
    })

    // typing updates state without a re-render, so the caret stays put
    root.addEventListener("input", (e) => {
        if (e.target.id === "answer") {
            S.text = e.target.value
            const btn = document.getElementById("check-btn")
            if (btn) btn.disabled = !S.text.trim() || S.grading
        } else if (e.target.id === "title-input") {
            S.title = e.target.value
            const btn = document.getElementById("title-save")
            if (btn) btn.disabled = !S.title.trim() || S.titleSaving
        }
    })

    document.addEventListener("keydown", (e) => {
        if (e.target.id === "answer" && e.key === "Enter" && !e.shiftKey) {
            e.preventDefault()
            ACTIONS.checkShort()
        } else if (e.target.id === "title-input" && e.key === "Enter") {
            saveTitle()
        } else if (e.key === "Escape" && S.expanded) {
            set({ expanded: false })
        }
    })

    // ------------------------------------------------------------ Electron wiring

    if (window.api) {
        // keep the window exactly the size of the UI (main.js keeps its right edge in place)
        new ResizeObserver(() => {
            const r = root.getBoundingClientRect()
            window.api.resize(Math.ceil(r.width), Math.ceil(r.height))
        }).observe(root)
        window.api.onClickThrough((on) => set({ ct: !!on }))
    }

    if (!DEMO) {
        quiz.onPending = (pending) => openQuiz(pending.topic, pending.questions)
        capture.onEnded = () => set({ rec: false, busy: false, error: "Listening stopped: the audio capture ended." })
    }

    render()
})()
