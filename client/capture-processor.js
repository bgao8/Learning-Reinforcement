const BATCH = 4096 // frames per message (~85 ms @ 48 kHz), matches the old block size

// CaptureProcessor class, inherits audioWorklet, which we
// use in renderer.js
class CaptureProcessor extends AudioWorkletProcessor {
    constructor() {
        super()
        this._buf = new Float32Array(BATCH)
        this._n = 0
    }

    process(inputs) {
        // capture always returns stereo
        // inputs[0] = first input [0] = only left side channel. We ignore right
        // same as the ScriptProcessor version. Return true to stay alive even when no
        // input is connected this quantum (e.g. right before the track stops).
        const ch = inputs[0] && inputs[0][0]
        if (!ch) return true

        for (let i = 0; i < ch.length; i++) {
            // _buf is a holding array where the processor collects samples until 
            // it has 4096 samples
            // _n is the sample counter
            this._buf[this._n++] = ch[i]
            if (this._n === BATCH) {
                // Transfer the buffer (zero-copy) and allocate a fresh one for the
                // next batch. The main thread now owns the transferred buffer.
                this.port.postMessage(this._buf, [this._buf.buffer])
                this._buf = new Float32Array(BATCH)
                this._n = 0
            }
        }
        return true
  }
}

registerProcessor("capture-processor", CaptureProcessor)
