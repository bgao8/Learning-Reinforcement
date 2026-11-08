const API = "http://127.0.0.1:8000"

async function createSession() {
    const res = await fetch(`${API}/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: "system-audio" })
    })

    if (!res.ok) {
        throw new Error(`POST /sessions failed: ${res.status}`)
    }
    const session = await res.json()
    return session.session_id
}

async function endSession(sessionId) {
    const res = await fetch(`${API}/sessions/${sessionId}/end`, { 
        method: "PATCH" 
    })
    if (!res.ok) {
        throw new Error(`PATCH end failed: ${res.status}`)
    }
}

const CHUNK = 16000 * 5

async function uploadChunk(sessionId, seq, samples) {
    const res = await fetch(`${API}/sessions/${sessionId}/chunks?seq=${seq}`, {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: samples
    })
    if (!res.ok) {
        throw new Error(`chunk ${seq} failed: ${res.status}`)
    }
}

// joins the small worklet batches into one array and empties the pile
function takePending(rec) {
    const out = new Float32Array(rec.pendingLen)
    let offset = 0
    for (const batch of rec.pending) {
        out.set(batch, offset)
        offset += batch.length
    }
    rec.pending = []
    rec.pendingLen = 0
    return out
}

// sends a chunk only after the previous finishes
function queueUpload(rec, samples) {
    const seq = rec.seq++
    rec.uploads = rec.uploads
        .then(() => uploadChunk(rec.sessionId, seq, samples))
        .catch(err => window.api.log(err.message))
}


const btn = document.getElementById("toggle-record")
let recording = null

btn.addEventListener("click", async () => {
    // ignore clicks while starting/stopping so a double-click can't open two captures
    btn.disabled = true
    try {
        if (recording) {
            await stop()
            window.api.log("Recording stopped")
        } 
        else {
            await start()
            window.api.log(recording ? "Recording started" : "Recording failed to start")
        }
    } finally {
        btn.disabled = false
        updateButton()
    }
})

function updateButton() {
    btn.textContent = recording ? "Stop Recording" : "Start Recording"
}

async function start() {
    let stream
    try {
        stream = await navigator.mediaDevices.getDisplayMedia({ audio: true, video: false })
    } catch (err) {
        console.error("getDisplayMedia failed", err.message)
        return
    }
    
    const track = stream.getAudioTracks()[0]
    if (!track) {
        console.error("No audio track returned")
        stream.getTracks().forEach(t => t.stop())
        return
    }

    // fires only if the track dies on its own (e.g. capture permission revoked),
    // never for our own track.stop()
    track.onended = async () => {
        window.api.log("Capture ended unexpectedly")
        await stop()
        updateButton()
    }

    // creates a new context for the audio to live in, starts audio thread
    let context
    try {
        context = new AudioContext({ sampleRate: 16000 })

        // context's audio thread will load (but not run) file capture-processor.js
        // we do this to allow for multi-threading
        await context.audioWorklet.addModule("capture-processor.js") 

        // brings system audio into the context
        const source = context.createMediaStreamSource(stream)

        // runs capture-processor.js code and sends samples to the renderer
        const node = new AudioWorkletNode(context, "capture-processor")

        // volume knob
        const sink = context.createGain()
        // set to mute
        sink.gain.value = 0

        source.connect(node)
        node.connect(sink)
        sink.connect(context.destination)

        const rec = { pending: [], pendingLen: 0, seq: 0, uploads: Promise.resolve(), sessionId: null }
        node.port.onmessage = (e) => {
            rec.pending.push(e.data)
            rec.pendingLen += e.data.length
            if (rec.sessionId && rec.pendingLen >= CHUNK) {
                queueUpload(rec, takePending(rec))
            }
        }

        rec.sessionId = await createSession()
        window.api.log(`Session started: ${rec.sessionId} sampleRate=${context.sampleRate}`)
        recording = { stream, track, context, source, node, sessionId: rec.sessionId, rec }
    } catch(err) {
        window.api.log(`Audio setup failed: ${err.message}`)
        track.stop()
        // context is undefined if new AudioContext() itself threw
        context?.close()
        return
    }
}

async function stop() {
    // safe to call from onended even if a click already stopped it
    if (!recording) return
    const { sessionId, rec } = recording
    recording.source.disconnect()
    recording.node.disconnect()
    recording.track.stop()
    await recording.context.close()
    recording = null

    if (rec.pendingLen > 0) {
        queueUpload(rec, takePending(rec))
    }
    await rec.uploads

    try {
        await endSession(sessionId)
        window.api.log(`Session ended: ${sessionId}`)
    } catch(err) {
        window.api.log(`Error ending session: ${err.message}`)
    }
}
