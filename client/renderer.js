// Capture and the session API. The UI (app.js) calls start() / stop() and reads
// currentSessionId(); capture.onEnded tells it when the track died on its own.
// { url, token } from main.js, asked once: every call awaits the same promise
const server = window.api.server()
let warnedAuth = false   // log the 401 fix once, not on every chunk

// fetch for the Frizz API: takes a path ("/sessions"), adds the server URL and this device's
// token (#33). Returns the Response like fetch does; callers still check res.ok.
async function apiFetch(path, options = {}) {
    const { url, token } = await server
    const headers = { ...options.headers }
    if (token) {
        headers.Authorization = `Bearer ${token}`
    }
    const res = await fetch(`${url}${path}`, { ...options, headers })
    if (res.status === 401 && !warnedAuth) {
        warnedAuth = true
        window.api.log("[auth] token missing or rejected: set FRIZZ_TOKEN and restart")
    }
    return res
}

async function createSession() {
    const res = await apiFetch(`/sessions`, {
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
    const res = await apiFetch(`/sessions/${sessionId}/end`, { 
        method: "PATCH" 
    })
    if (!res.ok) {
        throw new Error(`PATCH end failed: ${res.status}`)
    }
}

// optional video title (#25): sent to question generation as LECTURE TITLE
async function saveSessionTitle(sessionId, title) {
    const res = await apiFetch(`/sessions/${sessionId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
    })
    if (!res.ok) {
        throw new Error(`PATCH title failed: ${res.status}`)
    }
}

const CHUNK = 16000 * 5

async function uploadChunk(sessionId, seq, samples) {
    const res = await apiFetch(`/sessions/${sessionId}/chunks?seq=${seq}`, {
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


// #20: is something playing right now? Read by media.js before pressing ⏯, which is a toggle.
// A paused video sends digital silence, so any batch above the floor means "playing".
const LOUD_FLOOR = 0.0003          // same RMS floor as the server's silence gate (stt/silence.py)
const AUDIBLE_WINDOW_MS = 1500     // speech has short gaps, so look back a little
let lastLoudAt = 0

function batchRms(samples) {
    let sum = 0
    for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i]
    return Math.sqrt(sum / samples.length)
}

function isAudible() {
    return recording !== null && performance.now() - lastLoudAt < AUDIBLE_WINDOW_MS
}


let recording = null

const capture = {
    onEnded: () => {},   // set by app.js: capture stopped without the user asking
}

function currentSessionId() {
    return recording ? recording.sessionId : null
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
        capture.onEnded()
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
        lastLoudAt = 0
        node.port.onmessage = (e) => {
            // each batch is 4096 samples = 256 ms at 16 kHz
            if (batchRms(e.data) >= LOUD_FLOOR) lastLoudAt = performance.now()
            rec.pending.push(e.data)
            rec.pendingLen += e.data.length
            if (rec.sessionId && rec.pendingLen >= CHUNK) {
                queueUpload(rec, takePending(rec))
            }
        }

        rec.sessionId = await createSession()
        window.api.log(`Session started: ${rec.sessionId} sampleRate=${context.sampleRate}`)
        recording = { stream, track, context, source, node, sessionId: rec.sessionId, rec }
        startQuizPolling(rec.sessionId)
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
    endQuizPolling()

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

// says right away whether the token works, instead of a 401 on the first chunk
apiFetch("/users/me").then(
    (res) => window.api.log(res.ok ? "[auth] signed in" : `[auth] not signed in (${res.status}): set FRIZZ_TOKEN`),
    (err) => window.api.log(`[auth] server unreachable: ${err.message}`),
)
