const {app, BrowserWindow, desktopCapturer, ipcMain, session } = require("electron")
const fs = require("node:fs")
const path = require("node:path")

const OUT_DIR = path.join(__dirname, "out")

function createWindow() {
    const win = new BrowserWindow({
        width: 640,
        height: 620,
        title: "Unnamed Learning Reinforcement Tool",
        webPreferences: {
            preload: path.join(__dirname, "preload.js")
        }
    })
    win.loadFile("index.html")
    return win;
}

app.whenReady().then(() => {
    ipcMain.handle("log", (_e, msg) => {
        console.log(`[renderer] ${msg}`)
    })

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

    createWindow()

    app.on("activate", () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            createWindow()
        }
    })

})

app.on("window-all-closed", () => {
    if (process.platform !== "darwin") {
        app.quit()
    }
})