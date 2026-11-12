const { contextBridge, ipcRenderer } = require("electron")

contextBridge.exposeInMainWorld("api", {
    log: (msg) => ipcRenderer.invoke("log", msg),
    quizShown: () => ipcRenderer.invoke("quiz-shown"),
    mediaToggle: () => ipcRenderer.invoke("media-toggle"),
})