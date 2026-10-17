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
        context = new AudioContext()

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

        // log every 50th recorded chunk
        let chunks = 0
        node.port.onmessage = (e) => {
            chunks++
            if (chunks % 50 === 0) window.api.log(`chunks=${chunks} sampleRate=${context.sampleRate}`)
        }

        recording = { stream, track, context, source, node }
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
    recording.source.disconnect()
    recording.node.disconnect()
    recording.track.stop()
    await recording.context.close()
    recording = null
}
