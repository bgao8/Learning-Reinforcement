const {app, BrowserWindow, desktopCapturer, ipcMain, screen, session, globalShortcut, systemPreferences } = require("electron")
const path = require("node:path")
const { execFile } = require("node:child_process")

// presses the system play/pause key; built from native/mediakey.swift (npm run build:native)
const MEDIAKEY = path.join(__dirname, "native", "mediakey")

const MARGIN = 16          // gap between the overlay and the screen's top-right corner
const MAX_SIZE = 2000      // sanity cap on sizes the renderer asks for

let clickThrough = false
let win = null

// sets click-through and tells the renderer, which dims the UI while it's on
function setClickThrough(on, why) {
    if (!win || win.isDestroyed()) { return }
    clickThrough = on
    win.setIgnoreMouseEvents(on)
    win.webContents.send("click-through", on)
    console.log(`[main] click-through ${on ? "ON" : "OFF"}${why ? ` (${why})` : ""}`)
}

function createWindow() {
    const width = 400
    const height = 120
    const area = screen.getPrimaryDisplay().workArea
    win = new BrowserWindow({
        width,
        height,
        x: area.x + area.width - width - MARGIN,
        y: area.y + MARGIN,
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
    // a reload resets the renderer's state; tell it the real click-through setting
    win.webContents.on("did-finish-load", () => win.webContents.send("click-through", clickThrough))
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
        setClickThrough(!clickThrough)
    })

    if (!ok) { console.error("[main] hotkey already taken by another app") }

    ipcMain.handle("log", (_e, msg) => {
        console.log(`[renderer] ${msg}`)
    })

    // a question card opened: it must be clickable and accept typing
    ipcMain.handle("quiz-shown", () => {
        if (!win || win.isDestroyed()) { return }
        if (clickThrough) { setClickThrough(false, "quiz shown") }
        win.focus()
    })

    // #59: the renderer reports its UI's size and the window shrinks to fit, so the transparent
    // area around the pill/panel never blocks clicks on the video. The right edge stays put, so
    // expanding the pill into the panel grows the window leftward and down.
    ipcMain.handle("resize", (_e, width, height) => {
        if (!win || win.isDestroyed()) { return }
        if (!Number.isFinite(width) || !Number.isFinite(height)) { return }
        const w = Math.min(MAX_SIZE, Math.max(1, Math.round(width)))
        const h = Math.min(MAX_SIZE, Math.max(1, Math.round(height)))
        const b = win.getBounds()
        if (b.width === w && b.height === h) { return }
        win.setBounds({ x: b.x + b.width - w, y: b.y, width: w, height: h })
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