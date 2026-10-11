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