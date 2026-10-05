// Capture processor — runs on the dedicated audio render thread (AudioWorklet),
// NOT the main/UI thread. This is the whole point of the migration: UI, network,
// and STT work on the main thread can never stall sample pulling here.
//
// The render thread hands us audio in fixed 128-frame quanta. Posting a message
// per quantum would be ~375 messages/sec — so we batch into larger chunks first
// and ship those, keeping messaging overhead low.

const BATCH = 4096; // frames per message (~85 ms @ 48 kHz), matches the old block size

class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buf = new Float32Array(BATCH);
    this._n = 0;
  }

  process(inputs) {
    // inputs[0] = first input; [0] = first channel (left). Mono analysis, same
    // as the ScriptProcessor version. Return true to stay alive even when no
    // input is connected this quantum (e.g. right before the track stops).
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;

    for (let i = 0; i < ch.length; i++) {
      this._buf[this._n++] = ch[i];
      if (this._n === BATCH) {
        // Transfer the buffer (zero-copy) and allocate a fresh one for the
        // next batch. The main thread now owns the transferred buffer.
        this.port.postMessage(this._buf, [this._buf.buffer]);
        this._buf = new Float32Array(BATCH);
        this._n = 0;
      }
    }
    return true;
  }
}

registerProcessor("capture-processor", CaptureProcessor);
