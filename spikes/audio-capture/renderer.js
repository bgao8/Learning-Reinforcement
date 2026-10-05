// Audio capture spike — renderer.
//
// Captures ~6s of system audio via the native loopback path, measures the
// signal (peak + RMS) to prove it is NOT silence, encodes a WAV, and writes
// both the WAV and a result.json to ./out via the main process.

const DURATION_MS = 6000;

// Thresholds for the verdict. A live-but-silent track (the classic loopback
// failure mode) sits at ~0. Real playback is orders of magnitude above these.
const PEAK_FLOOR = 0.003; // ~ -50 dBFS
const RMS_FLOOR = 0.0003; // ~ -70 dBFS

const startBtn = document.getElementById("start");
const bar = document.getElementById("bar");
const verdictEl = document.getElementById("verdict");
const logEl = document.getElementById("log");

function log(msg) {
  const line = `[${new Date().toLocaleTimeString()}] ${msg}`;
  logEl.textContent += line + "\n";
  logEl.scrollTop = logEl.scrollHeight;
  window.spike?.log?.(msg);
}

function setVerdict(text, cls) {
  verdictEl.textContent = text;
  verdictEl.className = `verdict ${cls}`;
}

// Mono Float32 samples -> 16-bit PCM WAV (ArrayBuffer).
function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeStr = (offset, str) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true); // PCM chunk size
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeStr(36, "data");
  view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    offset += 2;
  }
  return buffer;
}

async function run() {
  startBtn.disabled = true;
  setVerdict("Requesting system audio…", "pending");

  let stream;
  try {
    // video:false — we only want the lecture's audio. The main-process handler
    // supplies a screen source for video and 'loopback' for audio; Electron
    // returns just the audio track here.
    stream = await navigator.mediaDevices.getDisplayMedia({ audio: true, video: false });
  } catch (err) {
    log(`getDisplayMedia failed: ${err.name} — ${err.message}`);
    setVerdict("NO-GO — capture was denied or unavailable.", "nogo");
    startBtn.disabled = false;
    return;
  }

  const track = stream.getAudioTracks()[0];
  if (!track) {
    log("No audio track returned.");
    setVerdict("NO-GO — no system-audio track in the stream.", "nogo");
    startBtn.disabled = false;
    return;
  }
  log(`audio track: label="${track.label}" readyState=${track.readyState} muted=${track.muted}`);
  // The real failure mode: the track ends ON ITS OWN mid-capture (loopback not
  // granted). The 'ended' event fires only for spontaneous ends, NOT for our own
  // track.stop() below — so this flag, not readyState, is the honest signal.
  let endedEarly = false;
  track.onended = () => {
    endedEarly = true;
    log("audio track ENDED early (this is the known failure mode)");
  };

  const ctx = new AudioContext();
  await ctx.resume();
  const sampleRate = ctx.sampleRate;
  log(`AudioContext sampleRate=${sampleRate} state=${ctx.state}`);

  const srcNode = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(4096, 1, 1);

  const blocks = [];
  let peak = 0;
  let sumSq = 0;
  let count = 0;

  proc.onaudioprocess = (e) => {
    const ch = e.inputBuffer.getChannelData(0);
    blocks.push(new Float32Array(ch));
    let blockPeak = 0;
    for (let i = 0; i < ch.length; i++) {
      const v = Math.abs(ch[i]);
      if (v > blockPeak) blockPeak = v;
      if (v > peak) peak = v;
      sumSq += ch[i] * ch[i];
      count++;
    }
    bar.style.width = `${Math.min(100, blockPeak * 140).toFixed(1)}%`;
  };

  // A zero-gain sink keeps the graph pulling audio without echoing it back out
  // of the speakers (which would cause feedback).
  const sink = ctx.createGain();
  sink.gain.value = 0;
  srcNode.connect(proc);
  proc.connect(sink);
  sink.connect(ctx.destination);

  setVerdict(`Recording ${DURATION_MS / 1000}s… play some audio now.`, "pending");
  log("recording started");

  await new Promise((r) => setTimeout(r, DURATION_MS));

  proc.disconnect();
  srcNode.disconnect();
  track.stop();
  await ctx.close();
  bar.style.width = "0%";

  const samples = new Float32Array(count);
  let o = 0;
  for (const b of blocks) {
    samples.set(b, o);
    o += b.length;
  }
  const rms = count ? Math.sqrt(sumSq / count) : 0;
  const durationSec = count / sampleRate;
  const isGo = !endedEarly && peak >= PEAK_FLOOR && rms >= RMS_FLOOR;

  log(`samples=${count} duration=${durationSec.toFixed(2)}s peak=${peak.toFixed(5)} rms=${rms.toFixed(5)}`);

  const result = {
    verdict: isGo ? "GO" : "NO-GO",
    peak: Number(peak.toFixed(6)),
    rms: Number(rms.toFixed(6)),
    sampleRate,
    durationSec: Number(durationSec.toFixed(3)),
    trackLabel: track.label,
    trackEnded: endedEarly,
    capturedAt: new Date().toISOString(),
  };

  try {
    const wav = encodeWav(samples, sampleRate);
    const { wavPath } = await window.spike.saveResult({ wav, result });
    log(`saved WAV + result.json to ${wavPath.replace(/capture\.wav$/, "")}`);
  } catch (err) {
    log(`save failed: ${err.message}`);
  }

  if (isGo) {
    setVerdict(`GO ✅  peak=${result.peak} rms=${result.rms} — real system audio captured.`, "go");
  } else if (endedEarly) {
    setVerdict("NO-GO — track ended during capture (loopback not granted).", "nogo");
  } else {
    setVerdict(`NO-GO — signal too quiet (peak=${result.peak}). Was audio actually playing?`, "nogo");
  }

  startBtn.disabled = false;
}

startBtn.addEventListener("click", () => run().catch((e) => log(`unexpected: ${e.message}`)));
