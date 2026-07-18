# HMS Staff Desktop App

An Electron wrapper around the existing HMS staff web dashboards — no separate UI, no backend changes. On first launch it asks for your hospital's web address (e.g. `https://stjohns.hms.example.com`, or `http://stjohns.lvh.me:8000` for local dev) and then just displays the real login page and dashboards in a native window.

## Run in development

```
cd desktop-app
npm install
npm start
```

## Build a Windows installer/exe

```
npm run dist
```

Produces both an NSIS installer and a portable `.exe` under `dist/` (see the `build.win.target` config in `package.json`).

## Changing hospitals

Use the **Hospital → Change Hospital…** menu item in the running app to clear the saved address and re-enter setup.
