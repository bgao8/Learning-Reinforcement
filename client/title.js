// Optional video title (#25). Shown when recording starts; hidden once saved, when the
// first quiz card opens, or when recording stops. The server sends it to question
// generation as LECTURE TITLE, so concepts get named at the course level even for the
// first quiz. Uses API from renderer.js.

const titleBox = document.getElementById("title-box")
const titleInput = document.getElementById("title-input")
const titleSave = document.getElementById("title-save")
const titleStatus = document.getElementById("title-status")
let titleSessionId = null

function showTitleBox(sessionId) {
    titleSessionId = sessionId
    titleInput.value = ""
    titleStatus.textContent = ""
    titleSave.disabled = false
    titleBox.hidden = false
    titleInput.focus()
}

function hideTitleBox() {
    titleBox.hidden = true
    titleSessionId = null
}

async function saveTitle() {
    const title = titleInput.value.trim()
    if (!title || !titleSessionId) return
    titleSave.disabled = true
    titleStatus.textContent = ""
    try {
        const res = await fetch(`${API}/sessions/${titleSessionId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title }),
        })
        if (!res.ok) throw new Error(`PATCH title failed: ${res.status}`)
        window.api.log(`title saved: ${title}`)
        hideTitleBox()
    } catch (err) {
        window.api.log(err.message)
        titleStatus.textContent = "Couldn't save the title. Try again."
        titleSave.disabled = false
    }
}

titleSave.addEventListener("click", saveTitle)
titleInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") saveTitle()
})
