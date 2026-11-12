// Question card: polls the server for pending questions, shows them one at a time,
// posts answers to /questions/{id}/attempts and shows the grade + feedback.
// Every server/LLM string goes in with textContent, never innerHTML.

const QUIZ_API = "http://127.0.0.1:8000"
const POLL_MS = 5000
const TAIL_MS = 30000   // keep polling this long after recording stops: questions land ~7 s after a trigger

const quiz = {
    sessionId: null,
    timer: null,
    stopAt: null,       // set when recording stops; polling ends at this time
    open: false,
    questions: [],
    index: 0,
    // #20 hooks: pause the video when a card opens, resume when it closes
    onQuizShown: () => {},
    onQuizDone: () => {},
}

const el = (id) => document.getElementById(id)
const card = el("quiz-card")

function startQuizPolling(sessionId) {
    stopQuizTimer()
    quiz.sessionId = sessionId
    quiz.stopAt = null
    quiz.timer = setInterval(pollPending, POLL_MS)
}

// called when recording stops: keep polling a little longer, then quit
function endQuizPolling() {
    quiz.stopAt = Date.now() + TAIL_MS
}

function stopQuizTimer() {
    if (quiz.timer) clearInterval(quiz.timer)
    quiz.timer = null
}

async function pollPending() {
    if (quiz.stopAt && Date.now() > quiz.stopAt && !quiz.open) {
        stopQuizTimer()
        return
    }
    if (quiz.open || !quiz.sessionId) return
    try {
        const res = await fetch(`${QUIZ_API}/sessions/${quiz.sessionId}/questions/pending`)
        if (!res.ok) throw new Error(`pending failed: ${res.status}`)
        const pending = await res.json()
        if (pending.questions.length > 0 && !quiz.open) showQuiz(pending)
    } catch (err) {
        window.api.log(err.message)
    }
}

function showQuiz(pending) {
    quiz.open = true
    quiz.questions = pending.questions
    quiz.index = 0
    el("quiz-topic").textContent = pending.topic || "Quick check"
    card.hidden = false
    window.api.quizShown()   // main process turns click-through off and focuses the window
    quiz.onQuizShown()
    renderQuestion()
}

function renderQuestion() {
    const q = quiz.questions[quiz.index]
    el("quiz-progress").textContent = `${quiz.index + 1} / ${quiz.questions.length}`
    el("quiz-prompt").textContent = q.prompt
    el("quiz-ask").hidden = false
    el("quiz-result").hidden = true

    const options = el("quiz-options")
    options.replaceChildren()
    const text = el("quiz-text")
    text.value = ""

    if (q.question_type === "multiple_choice" && q.options) {
        text.hidden = true
        for (const option of q.options) {
            const label = document.createElement("label")
            const radio = document.createElement("input")
            radio.type = "radio"
            radio.name = "quiz-option"
            radio.value = option      // grading matches the option text exactly
            label.append(radio, " ", option)
            options.append(label)
        }
    } else {
        text.hidden = false
        text.focus()
    }
    setButtonsDisabled(false)
}

function currentAnswer() {
    const q = quiz.questions[quiz.index]
    if (q.question_type === "multiple_choice") {
        return document.querySelector('input[name="quiz-option"]:checked')?.value ?? ""
    }
    return el("quiz-text").value
}

async function submitAnswer(answer) {
    const q = quiz.questions[quiz.index]
    setButtonsDisabled(true)
    try {
        const res = await fetch(`${QUIZ_API}/questions/${q.question_id}/attempts`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_answer: answer }),
        })
        if (!res.ok) throw new Error(`attempt failed: ${res.status}`)
        showResult(await res.json())
    } catch (err) {
        window.api.log(err.message)
        showResult(null)
    }
}

function showResult(attempt) {
    const verdict = el("quiz-verdict")
    if (!attempt) {
        verdict.textContent = "Couldn't reach the server. Try again later."
        verdict.className = "verdict-ungraded"
        el("quiz-feedback").textContent = ""
    } else if (!attempt.graded) {
        verdict.textContent = "Couldn't grade this right now. Your answer was saved."
        verdict.className = "verdict-ungraded"
        el("quiz-feedback").textContent = ""
    } else {
        const [label, cls] =
            attempt.is_correct ? ["✓ Correct", "verdict-correct"]
            : attempt.score > 0 ? ["◐ Partly right", "verdict-partial"]
            : ["✗ Not quite", "verdict-incorrect"]
        verdict.textContent = label
        verdict.className = cls
        el("quiz-feedback").textContent = attempt.feedback
    }
    el("quiz-ask").hidden = true
    el("quiz-result").hidden = false
    el("quiz-next").textContent = quiz.index + 1 < quiz.questions.length ? "Next" : "Done"
    el("quiz-next").disabled = false
    el("quiz-next").focus()
}

function nextQuestion() {
    quiz.index += 1
    if (quiz.index < quiz.questions.length) {
        renderQuestion()
        return
    }
    card.hidden = true
    quiz.open = false
    quiz.onQuizDone()
    pollPending()   // another quiz may already be waiting
}

function setButtonsDisabled(disabled) {
    el("quiz-submit").disabled = disabled
    el("quiz-skip").disabled = disabled
}

el("quiz-submit").addEventListener("click", () => submitAnswer(currentAnswer()))
el("quiz-skip").addEventListener("click", () => submitAnswer(""))   // graded as blank: shows the answer
el("quiz-next").addEventListener("click", nextQuestion)
