const {app, BrowserWindow, desktopCapturer, ipcMain, session, globalShortcut } = require("electron")
const path = require("node:path")

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
    win.loadFile("index.html")
    return win
}


app.whenReady().then(() => {
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