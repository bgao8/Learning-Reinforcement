const { contextBridge, ipcRenderer } = require("electron")

contextBridge.exposeInMainWorld("api", {
    log: (msg) => ipcRenderer.invoke("log", msg),
    mediaToggle: () => ipcRenderer.invoke("media-toggle"),
    // #59: fit the window to the UI; main keeps the right edge in place
    resize: (width, height) => ipcRenderer.invoke("resize", width, height),
    onClickThrough: (fn) => ipcRenderer.on("click-through", (_e, on) => fn(on)),
})
