# HMS Patient App

A React Native CLI app (not Expo) that gives patients a native mobile front end for the HMS backend — the same features as the web patient dashboard (appointments, telemedicine, prescription refills, medical records, lab results, billing, secure messaging, notifications, and a one-tap emergency alert), talking to a dedicated JSON API rather than server-rendered pages.

## How it fits together

- **Backend**: `hospital/api/` in the main Django project — DRF + JWT, one endpoint per screen below, all reusing the same `hospital/services.py` business logic the web app uses. See the root [README](../README.md) and [CLAUDE.md § Mobile/desktop clients](../CLAUDE.md#mobiledesktop-clients) for the full API surface.
- **Multi-tenancy**: this app is a single build shared by every hospital. On first launch (`HospitalPickerScreen`), the patient enters their hospital's server address and subdomain; that's stored locally and sent as `X-Hospital-Subdomain` on every request (see `src/api/storage.ts`, `src/api/client.ts`).
- **Auth**: JWT access + refresh tokens (`src/api/client.ts`). The access token is retried once with a silent refresh on a 401; the refresh token lives in `react-native-keychain` (OS-level secure storage), never `AsyncStorage`.

## Project layout

```
src/
  api/           client.ts (fetch + auth), storage.ts (Keychain/AsyncStorage), endpoints.ts (1:1 mirror of hospital/api/urls.py)
  context/       AuthContext.tsx — hospital selection + login/logout state for the whole app
  navigation/    RootNavigator (auth gate) → MainNavigator (bottom tabs + stack for detail screens)
  screens/       one screen per API area — thin fetch-and-render layers, no business logic
  components/    shared UI primitives (Card, Button, Input, ...)
  hooks/useApi.ts  loading/error/refetch wrapper used by every data screen
  theme.ts       shared color palette (matches desktop-app's dark theme)
```

## Running it

```bash
npm install
npx react-native start          # Metro bundler, in one terminal
npx react-native run-android    # or run-ios, in another
```

**Local dev against the Django backend**: don't try to reach your dev machine over WiFi/LAN IP. For a USB-connected Android device, tunnel instead:

```bash
adb reverse tcp:8000 tcp:8000   # Django
adb reverse tcp:8081 tcp:8081   # Metro
```

Then use `http://localhost:8000` as the server address in the hospital picker screen, with your test hospital's subdomain in the second field.

**Windows Android builds**: if you hit CMake/NDK/linker errors, read [CLAUDE.md § Mobile/desktop clients](../CLAUDE.md#mobiledesktop-clients) before changing any Gradle/NDK config — the current `ndkVersion`/`cmake.version`/`newArchEnabled` pins in `android/build.gradle`, `android/app/build.gradle`, and `android/gradle.properties` each fix a specific, already-diagnosed toolchain incompatibility. Changing any one of them in isolation reintroduces a build failure that took real effort to track down.

## Testing changes

There's no dedicated screen-level test suite here yet — verify by running the app against a real (or local) hospital and walking the flow: pick hospital → log in → dashboard loads real data → navigate each tab. The backend API itself is covered by `hospital/api/tests.py` in the Django project.
