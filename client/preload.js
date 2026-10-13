const { contextBridge, ipcRenderer } = require("electron")

contextBridge.exposeInMainWorld("api", {
    log: (msg) => ipcRenderer.invoke("log", msg)
})