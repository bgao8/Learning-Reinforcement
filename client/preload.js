const { contextBridge, ipcRenderer } = require("electron")

contextBridge.exposeInMainWorld("api", {
    log: (msg) => ipcRenderer.invoke("log", msg),
    mediaToggle: () => ipcRenderer.invoke("media-toggle"),
    // the island overlay: notch size, focus for typing, and where clicks should be caught
    geometry: () => ipcRenderer.invoke("geometry"),
    focus: () => ipcRenderer.invoke("focus"),
    islandRect: (rect) => ipcRenderer.send("island-rect", rect),
    onShortcut: (fn) => ipcRenderer.on("shortcut", (_e, name) => fn(name)),
})
