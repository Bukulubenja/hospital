const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("hms", {
  saveHospitalUrl: (url) => ipcRenderer.invoke("save-hospital-url", url),
});
