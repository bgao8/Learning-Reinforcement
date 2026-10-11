const {app, BrowserWindow, desktopCapturer, ipcMain, session } = require("electron")

function createWindow() {
    const win = new BrowserWindow({
        width: 640,
        height: 620,
        title: "Unnamed Learning Reinforcement Tool",
        webPreferences: {
            preload: pathjoin(__dirname, "preload.js")
        }
    })
}