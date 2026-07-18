const { app, BrowserWindow, Menu, ipcMain } = require("electron");
const path = require("path");
const fs = require("fs");

const configPath = path.join(app.getPath("userData"), "config.json");

function loadConfig() {
  try {
    return JSON.parse(fs.readFileSync(configPath, "utf-8"));
  } catch {
    return {};
  }
}

function saveConfig(config) {
  fs.mkdirSync(path.dirname(configPath), { recursive: true });
  fs.writeFileSync(configPath, JSON.stringify(config));
}

let mainWindow = null;
let setupWindow = null;

function buildMenu(baseUrl) {
  const template = [
    {
      label: "Hospital",
      submenu: [
        {
          label: "Change Hospital…",
          click: () => {
            saveConfig({});
            if (mainWindow) {
              mainWindow.close();
              mainWindow = null;
            }
            createSetupWindow();
          },
        },
        { role: "reload" },
        { type: "separator" },
        { role: "quit" },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function createMainWindow(baseUrl) {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    title: "HMS Staff",
    webPreferences: {
      contextIsolation: true,
    },
  });
  mainWindow.loadURL(`${baseUrl.replace(/\/+$/, "")}/hospital/`);
  buildMenu(baseUrl);
}

function createSetupWindow() {
  setupWindow = new BrowserWindow({
    width: 480,
    height: 340,
    resizable: false,
    title: "HMS Staff — Setup",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
    },
  });
  setupWindow.setMenu(null);
  setupWindow.loadFile("setup.html");
}

ipcMain.handle("save-hospital-url", (_event, url) => {
  saveConfig({ baseUrl: url });
  if (setupWindow) {
    setupWindow.close();
    setupWindow = null;
  }
  createMainWindow(url);
});

app.whenReady().then(() => {
  const config = loadConfig();
  if (config.baseUrl) {
    createMainWindow(config.baseUrl);
  } else {
    createSetupWindow();
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      const current = loadConfig();
      if (current.baseUrl) {
        createMainWindow(current.baseUrl);
      } else {
        createSetupWindow();
      }
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
