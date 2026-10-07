// Audio capture spike — main process.
//
// Goal: prove we can capture NON-SILENT macOS system audio from Electron,
// using the native loopback path (ScreenCaptureKit)

const { app, BrowserWindow, desktopCapturer, ipcMain, session } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

const OUT_DIR = path.join(__dirname, "out");

function createWindow() {
  const win = new BrowserWindow({
    width: 640,
    height: 620,
    title: "Audio Capture Spike",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
    },
  });
  win.loadFile("index.html");
  return win;
}

app.whenReady().then(() => {
  // Relay renderer logs to the terminal so the result is visible from the CLI too.
  ipcMain.handle("log", (_e, msg) => {
    console.log(`[renderer] ${msg}`);
  });

  // Persist the captured WAV + a machine-readable verdict so the result can be
  // inspected after the run without watching the UI.
  ipcMain.handle("save-result", (_e, { wav, result }) => {
    fs.mkdirSync(OUT_DIR, { recursive: true });
    const wavPath = path.join(OUT_DIR, "capture.wav");
    const jsonPath = path.join(OUT_DIR, "result.json");
    fs.writeFileSync(wavPath, Buffer.from(wav));
    fs.writeFileSync(jsonPath, JSON.stringify({ ...result, wavPath }, null, 2));
    console.log(`[main] wrote ${wavPath} (${Buffer.from(wav).length} bytes)`);
    console.log(`[main] verdict: ${result.verdict}  peak=${result.peak}  rms=${result.rms}`);
    return { wavPath, jsonPath };
  });

  // The native loopback hook: provide a screen source for video and 'loopback'
  // for audio. The renderer requests audio-only; Electron returns just the
  // system-audio track.
  session.defaultSession.setDisplayMediaRequestHandler(async (_request, callback) => {
    try {
      const sources = await desktopCapturer.getSources({ types: ["screen"] });
      console.log(`[main] screen sources: ${sources.map((s) => s.name).join(", ") || "(none)"}`);
      callback({ video: sources[0], audio: "loopback" });
      console.log("[main] responded with audio=loopback + first screen source");
    } catch (err) {
      console.error("[main] failed to provide display media source:", err);
      callback({ video: null, audio: null });
    }
  });

  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
