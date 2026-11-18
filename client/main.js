const {app, BrowserWindow, desktopCapturer, ipcMain, screen, session, globalShortcut, systemPreferences } = require("electron")
const path = require("node:path")
const { execFile, execFileSync } = require("node:child_process")

// presses the system play/pause key; built from native/mediakey.swift (npm run build:native)
const MEDIAKEY = path.join(__dirname, "native", "mediakey")
// prints the notch's size and position; built from native/notch.swift
const NOTCH = path.join(__dirname, "native", "notch")

// The island overlay: one fixed, transparent window centered on the notch, big enough for the
// open panel. The UI animates inside it, so the window itself never moves or resizes (and if
// macOS moves it, keepHome puts it back). Its empty area passes clicks through to the apps
// below (see watchCursor).
const WIN_WIDTH = 440
const WIN_HEIGHT = 720
const FALLBACK_NOTCH = { width: 185, height: 32 }   // 14" MacBook Pro, used for sizing when there's no notch

const HIT_TEST_MS = 33     // how often to check whether the cursor is over the island (~30/s)

const MARGIN = 16          // gap between the overlay and the screen's top-right corner
const MAX_SIZE = 2000      // sanity cap on sizes the renderer asks for

let clickThrough = false
let win = null
let home = null       // where the window belongs: { x, y, width, height }, centered on the notch
let geometry = null   // { notch, width, height }: sent to the renderer
let islandRect = null // the island's clickable area in window coordinates, from the renderer
let catching = false  // the window is catching clicks (the cursor is over the island)
let cursorTimer = null

// where the notch is, via native/notch. Never throws: without the helper or a notched screen,
// the island floats as a capsule under the menu bar of the primary display.
function findNotch() {
    let info = { notch: false }
    try {
        info = JSON.parse(execFileSync(NOTCH, { timeout: 2000, encoding: "utf8" }))
    } catch (err) {
        console.error(`[main] notch helper failed (run npm run build:native): ${err.message}`)
    }
    const displays = screen.getAllDisplays()
    const display = info.notch
        ? displays.find((d) => d.bounds.x === info.screenX && d.bounds.width === info.screenWidth)
        : null
    if (!display) {
        const primary = screen.getPrimaryDisplay()
        const b = primary.bounds
        return {
            geometry: Object.assign({ notch: false }, FALLBACK_NOTCH),
            centerX: b.x + b.width / 2,
            top: primary.workArea.y,   // below the menu bar
        }
    }
    return {
        geometry: { notch: true, width: info.width, height: info.height },
        centerX: display.bounds.x + info.left + info.width / 2,
        top: display.bounds.y,         // over the menu bar, flush with the notch
    }
}

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
        resizable: false,
        enableLargerThanScreen: true,   // lets the window sit over the menu bar
        acceptFirstMouse: true,         // a click while another app is in front still counts
    })
    win.setAlwaysOnTop(true, "screen-saver")   // above the menu bar and fullscreen apps
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
    // a reload resets the renderer's state; tell it the real click-through setting
    win.webContents.on("did-finish-load", () => win.webContents.send("click-through", clickThrough))
    win.loadFile("index.html")
    watchCursor()
    return win
}

// Switching to a full-screen app's Space, macOS moves the window up by the notch's height
// (to y = -32, 32 taller), which puts the collapsed island above the top of the screen. Put
// it back wherever it was moved. Returns the window's bounds once it's home.
function keepHome() {
    const b = win.getBounds()
    if (b.x === home.x && b.y === home.y && b.width === home.width && b.height === home.height) { return b }
    console.log(`[main] window was moved to ${b.x},${b.y} ${b.width}x${b.height}; putting it back at ${home.x},${home.y}`)
    win.setBounds(home)
    return win.getBounds()
}

// Catch clicks only while the cursor is over the island. This checks the cursor's position
// itself rather than waiting for the renderer to see the mouse arrive: a window that ignores
// the mouse only gets mouse moves (forward) while its app is in front, so with a video in
// front, the island would never notice the mouse and every click would go through it.
function watchCursor() {
    clearInterval(cursorTimer)
    cursorTimer = setInterval(() => {
        if (!win || win.isDestroyed()) { return }
        const p = screen.getCursorScreenPoint()
        const b = keepHome()
        const r = islandRect
        const inside = !!r
            && p.x >= b.x + r.x && p.x < b.x + r.x + r.width
            && p.y >= b.y + r.y && p.y < b.y + r.y + r.height
        if (inside === catching) { return }
        catching = inside
        win.setIgnoreMouseEvents(!inside, { forward: true })
    }, HIT_TEST_MS)
}

// a global shortcut: tell the renderer, which owns the island's state
function shortcut(accelerator, name) {
    const ok = globalShortcut.register(accelerator, () => {
        if (win && !win.isDestroyed()) { win.webContents.send("shortcut", name) }
    })
    if (!ok) { console.error(`[main] ${accelerator} already taken by another app`) }
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