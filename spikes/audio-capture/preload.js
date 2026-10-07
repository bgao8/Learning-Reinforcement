const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("spike", {
  log: (msg) => ipcRenderer.invoke("log", msg),
  saveResult: (payload) => ipcRenderer.invoke("save-result", payload),
});
