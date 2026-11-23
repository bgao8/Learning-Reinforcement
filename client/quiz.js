// Quiz data: polls the server for pending questions and posts answers. No DOM here: the UI
// (app.js) gets questions through quiz.onPending and decides what to show; media.js hooks
// onQuizShown / onQuizDone to pause and resume the video (#20). Uses apiFetch from renderer.js.

const POLL_MS = 5000
const TAIL_MS = 30000   // keep polling this long after recording stops: questions land ~7 s after a trigger

const quiz = {
    sessionId: null,
    timer: null,
    stopAt: null,          // set when recording stops; polling ends at this time
    open: false,           // a quiz is on screen (set by app.js); no polling until it closes
    onPending: () => {},   // app.js: a quiz with unanswered questions is ready
    // #20 hooks, set by media.js: pause the video when a quiz opens, resume when it closes
    onQuizShown: () => {},
    onQuizDone: () => {},
}

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
        const res = await apiFetch(`/sessions/${quiz.sessionId}/questions/pending`)
        if (!res.ok) throw new Error(`pending failed: ${res.status}`)
        const pending = await res.json()
        if (pending.questions.length > 0 && !quiz.open) quiz.onPending(pending)
    } catch (err) {
        window.api.log(err.message)
    }
}

// grades and saves one answer ("" is a skip). Resolves the attempt, or null if the server
// couldn't be reached: the question stays unanswered and comes back in a later quiz.
async function postAttempt(questionId, answer) {
    try {
        const res = await apiFetch(`/questions/${questionId}/attempts`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_answer: answer }),
        })
        if (!res.ok) throw new Error(`attempt failed: ${res.status}`)
        return await res.json()
    } catch (err) {
        window.api.log(err.message)
        return null
    }
}
