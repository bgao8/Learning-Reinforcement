// #20: pause the video while a question card is open, resume it when the card closes.
//
// native/mediakey presses the system ⏯ key, which is a toggle, so two rules keep it safe:
//   - only pause if audio is actually playing (isAudible, from renderer.js)
//   - only resume what we paused (pausedByUs), and skip it if it's already playing again
// Pressing exactly twice puts whichever app received the key back the way it was.

const PAUSE_CHECK_MS = 2000   // > AUDIBLE_WINDOW_MS, so pre-pause audio has aged out

const media = {
    pausedByUs: false,
    pausing: Promise.resolve(),   // the in-flight pause, so a resume never overtakes it
}

async function pauseForQuiz() {
    if (media.pausedByUs) return   // still paused from the quiz before this one
    if (!isAudible()) {
        window.api.log("quiz shown: nothing playing, not pausing")
        return
    }
    const res = await window.api.mediaToggle()
    if (!res.ok) {
        window.api.log(`pause failed: ${res.reason}`)
        return
    }
    media.pausedByUs = true
    window.api.log("quiz shown: paused media")

    // diagnostic only: if audio didn't stop, the key probably went to another "Now Playing" app
    setTimeout(() => {
        if (media.pausedByUs && isAudible()) {
            window.api.log("still hearing audio after pausing: the key may have gone to another app")
        }
    }, PAUSE_CHECK_MS)
}

async function resumeAfterQuiz() {
    await media.pausing
    if (!media.pausedByUs) return
    media.pausedByUs = false
    if (isAudible()) {
        window.api.log("quiz done: media already playing again, not toggling")
        return
    }
    const res = await window.api.mediaToggle()
    window.api.log(res.ok ? "quiz done: resumed media" : `resume failed: ${res.reason}`)
}

quiz.onQuizShown = () => {
    media.pausing = pauseForQuiz().catch((err) => window.api.log(`pause error: ${err.message}`))
}

quiz.onQuizDone = () => {
    resumeAfterQuiz().catch((err) => window.api.log(`resume error: ${err.message}`))
}
