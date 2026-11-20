const {app, BrowserWindow, desktopCapturer, ipcMain, screen, session, globalShortcut, systemPreferences } = require("electron")
const path = require("node:path")
const { execFile, execFileSync } = require("node:child_process")

// presses the system play/pause key; built from native/mediakey.swift (npm run build:native)
const MEDIAKEY = path.join(__dirname, "native", "mediakey")
// prints the notch's size and position; built from native/notch.swift
const NOTCH = path.join(__dirname, "native", "notch")
// prints the playing video's browser window title; built from native/videotitle.swift
const VIDEOTITLE = path.join(__dirname, "native", "videotitle")

// The island overlay: one fixed, transparent window centered on the notch, big enough for the
// open panel. The UI animates inside it, so the window itself never moves or resizes (and if
// macOS moves it, keepHome puts it back). Its empty area passes clicks through to the apps
// below (see watchCursor).
const WIN_WIDTH = 440
const WIN_HEIGHT = 720
const FALLBACK_NOTCH = { width: 185, height: 32 }   // 14" MacBook Pro, used for sizing when there's no notch

const HIT_TEST_MS = 33     // how often to check whether the cursor is over the island (~30/s)

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

function createWindow() {
    const place = findNotch()
    geometry = place.geometry
    console.log(`[main] island: ${geometry.notch ? `notch ${geometry.width}x${geometry.height}` : "no notch, floating"}`)
    home = { x: Math.round(place.centerX - WIN_WIDTH / 2), y: place.top, width: WIN_WIDTH, height: WIN_HEIGHT }
    win = new BrowserWindow({
        ...home,
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
    // clicks pass through until the cursor is over the island (watchCursor)
    catching = false
    win.setIgnoreMouseEvents(true, { forward: true })
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

// "(3) Lecture 4: Linear Regression - YouTube 🔊" -> "Lecture 4: Linear Regression"
function cleanTitle(raw) {
    return raw
        .replace(/\s*🔊\s*$/u, "")                                       // Chrome's "playing sound" marker
        .replace(/^\(\d+\+?\)\s*/, "")                                    // unread-notification count
        .replace(/\s+[-–—]\s+(YouTube|Mozilla Firefox|Google Chrome)$/, "")  // site or browser name
        .trim()
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

    shortcut("CommandOrControl+Shift+K", "panel")   // open the panel / back to where it was

    ipcMain.handle("log", (_e, msg) => {
        console.log(`[renderer] ${msg}`)
    })

    ipcMain.handle("geometry", () => geometry)

    // the panel opened (a quiz, or the shortcut): take keyboard focus so it can be typed in
    ipcMain.handle("focus", () => {
        if (win && !win.isDestroyed()) { win.focus() }
    })

    // the island's clickable area changed (mode, panel height, hover bulge): watchCursor uses it
    ipcMain.on("island-rect", (_e, r) => {
        const ok = r && ["x", "y", "width", "height"].every((k) => Number.isFinite(r[k]))
        islandRect = ok ? { x: r.x, y: r.y, width: r.width, height: r.height } : null
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

    // the playing video's title, for the session title. Never throws: resolves { title, source }
    // (source: "sound" | "site" | "front", see native/videotitle.swift) or { title: null }, so a
    // missing helper or permission only means no auto-title.
    ipcMain.handle("video-title", () => new Promise((resolve) => {
        execFile(VIDEOTITLE, { timeout: 2000, encoding: "utf8" }, (err, stdout) => {
            if (err) {
                const reason = err.code === "ENOENT" ? "native/videotitle not built (run npm run build:native)" : err.message
                console.error(`[main] video-title failed: ${reason}`)
                return resolve({ title: null })
            }
            try {
                const out = JSON.parse(stdout)
                const title = out.title ? cleanTitle(out.title) : ""
                resolve(title ? { title, source: out.source } : { title: null })
            } catch (parseErr) {
                console.error(`[main] video-title printed bad JSON: ${parseErr.message}`)
                resolve({ title: null })
            }
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