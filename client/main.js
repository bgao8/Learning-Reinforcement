const {app, BrowserWindow, desktopCapturer, ipcMain, session, globalShortcut, systemPreferences } = require("electron")
const path = require("node:path")
const { execFile } = require("node:child_process")

// presses the system play/pause key; built from native/mediakey.swift (npm run build:native)
const MEDIAKEY = path.join(__dirname, "native", "mediakey")

let clickThrough = false
let win = null

function createWindow() {
    win = new BrowserWindow({
        width: 640,
        height: 620,
        title: "Frizz",
        webPreferences: {
            preload: path.join(__dirname, "preload.js")
        },
        transparent: true,
        frame: false,
        hasShadow: false,
    })
    win.setAlwaysOnTop(true, "screen-saver")
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
    win.loadFile("index.html")
    return win
}


app.whenReady().then(() => {
    // Accessibility lets native/mediakey post the play/pause key (#20). Passing true shows
    // the macOS prompt if it's missing. The app still works without it; videos just won't
    // auto-pause. macOS applies a new grant only after the launching app restarts.
    const trusted = systemPreferences.isTrustedAccessibilityClient(true)
    console.log(`[main] accessibility ${trusted ? "granted" : "missing (auto-pause disabled until granted and relaunched)"}`)

    const ok = globalShortcut.register("CommandOrControl+Shift+K", () => {
        if (!win || win.isDestroyed()) { return }
        clickThrough = !clickThrough
        win.setIgnoreMouseEvents(clickThrough)
        console.log(`[main] click-through ${clickThrough ? "ON" : "OFF"}`)
    })

    if (!ok) { console.error("[main] hotkey already taken by another app") }

    ipcMain.handle("log", (_e, msg) => {
        console.log(`[renderer] ${msg}`)
    })

    // a question card opened: it must be clickable and accept typing
    ipcMain.handle("quiz-shown", () => {
        if (!win || win.isDestroyed()) { return }
        if (clickThrough) {
            clickThrough = false
            win.setIgnoreMouseEvents(false)
            console.log("[main] click-through OFF (quiz shown)")
        }
        win.focus()
    })

    // press ⏯ once (#20). Never throws: resolves { ok } or { ok: false, reason } so the
    // renderer can log why and keep the quiz working without auto-pause.
    ipcMain.handle("media-toggle", () => new Promise((resolve) => {
        execFile(MEDIAKEY, (err, _stdout, stderr) => {
            if (!err) return resolve({ ok: true })
            const reason =
                err.code === "ENOENT" ? "native/mediakey not built (run npm run build:native)"
                : err.code === 2 ? "accessibility permission missing"
                : (stderr.trim() || err.message)
            console.error(`[main] media-toggle failed: ${reason}`)
            resolve({ ok: false, reason })
        })
    }))

    session.defaultSession.setDisplayMediaRequestHandler(async (_request, callback) => {
        try {
            const sources = await desktopCapturer.getSources({ types: ["screen"] });
            console.log(`[main] screen sources: ${sources.map((s) => s.name).join(", ") || "(none)"}`)
            callback({ video: sources[0], audio: "loopback" })
            console.log("[main] responded with audio=loopback + first screen source")
        } catch (err) {
            console.error("[main] failed to provide display media source:", err)
            callback({ video: null, audio: null })
        }
    });

    win = createWindow()

    app.on("activate", () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            win = createWindow()
            clickThrough = false
        }
    })

})

app.on("will-quit", () => {
    globalShortcut.unregisterAll()
})

app.on("window-all-closed", () => {
    if (process.platform !== "darwin") {
        app.quit()
    }
})