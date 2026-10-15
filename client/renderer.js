const btn = document.getElementById("toggle-record")
let recording = null

btn.addEventListener("click", async () => {
    if (recording) {
        await stop()
    } 
    else {
        await start()
    }
})

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

    // creates a new context for the audio to live in, starts audio thread
    const context = new AudioContext()

    // context's audio thread will load (but not run) file capture-processor.js
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

    node.port.onmessage = (e) => { /* e.data = 4096 samples */}
    recording = { stream, track, context, source, node }
}

async function stop() {
    recording.source.disconnect()
    recording.node.disconnect()
    recording.track.stop()
    await recording.context.close()
    recording = null
}
