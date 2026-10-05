# Audio capture spike (Week 1 go/no-go)

**Question:** can we capture non-silent macOS **system audio** from Electron,
natively, without BlackHole or any extra driver?

**Approach:** Electron 44 on macOS 13+ exposes system-audio loopback through
ScreenCaptureKit. The main process intercepts `getDisplayMedia()` via
`setDisplayMediaRequestHandler` and answers with a screen source for `video`
plus `audio: 'loopback'`. The renderer records ~6s, measures peak/RMS to prove
the signal isn't silence, and writes `out/capture.wav` + `out/result.json`.

## Run

```bash
cd spikes/audio-capture
npm install
npm start
```

Then, in the app window:

1. Start playing audio on your Mac (a YouTube video, music — anything).
2. Click **Record 6s of system audio**.
3. On first run macOS will prompt for **Screen & System Audio Recording**
   permission. Grant it (System Settings ▸ Privacy & Security ▸ Screen & System
   Audio Recording), then quit and `npm start` again — the permission only takes
   effect on the next launch.

## Reading the result

- **GO** — a WAV with real (non-silent) system audio lands in `out/`. The path
  (native ScreenCaptureKit loopback) works; no BlackHole needed. ✅
- **NO-GO, "track ended"** — loopback wasn't granted; re-check the Screen &
  System Audio Recording permission and relaunch.
- **NO-GO, "too quiet"** — the track is live but silent; make sure audio was
  actually playing out loud during the 6s window.

`out/result.json` holds the machine-readable verdict (`peak`, `rms`,
`sampleRate`, `trackEnded`).

## Notes / fallbacks

- If native loopback misbehaves on this exact macOS build, the documented
  fallbacks are: (a) build a signed `.app` (`electron-builder` with the audio
  entitlements) which is more reliable than the dev binary for TCC, or
  (b) the `electron-audio-loopback` package (Electron 31–38), or (c) BlackHole.
- The WAV is mono 16-bit PCM at the AudioContext sample rate (48 kHz) — the
  shape Whisper wants in Week 2.
