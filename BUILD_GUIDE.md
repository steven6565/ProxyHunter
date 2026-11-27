# ProxyHunter v3.0 — Build Guide

## Architecture

```
ProxyHunter/
├── backend/          # UI-agnostic controller + background worker (shared)
├── shared/           # export engine used by CLI, Android and Windows
├── proxyhunter/      # preserved v2.0/v3.0 engine (discovery, checker, gateway, security)
├── android/          # Kotlin + Jetpack Compose app (Chaquopy hosts the Python backend)
├── desktop/          # Tkinter desktop app (Windows) + PyInstaller spec + Inno Setup script
├── assets/           # generated original shield/nodes icon (ICO + vector drawable)
├── tests/            # controlled backend test suite + self-signed TLS fixtures
├── builds/           # Windows build script and local build output
└── .github/workflows # reproducible Android/Windows CI builds
```

The **same Python backend** powers the CLI, the Android foreground service and the Windows desktop app. The UIs never reimplement discovery/validation logic.

## Windows 10/11 x64 — portable EXE and Setup.exe

### Reproducible CI (recommended)
1. Push a tag `v3.*` or run the `Build Windows v3.0` workflow manually.
2. Artifacts: `ProxyHunter_v3.0_Windows_portable.zip` and `ProxyHunter_v3.0_Setup.exe`.
3. The EXE is **unsigned** unless a code-signing certificate is configured in the workflow.

### Local Windows machine
```powershell
powershell -ExecutionPolicy Bypass -File builds\build_windows.ps1
```
- Requires Python 3.11+ and (for Setup.exe) Inno Setup 6.
- Portable output: `builds/ProxyHunter_portable/ProxyHunter.exe`.
- Installer output: `builds/ProxyHunter_v3.0_Setup.exe` (start menu shortcut, optional desktop shortcut, uninstall support, no admin rights required).
- Default exports: `%USERPROFILE%\Downloads\ProxyHunter\`.

## Android 8.0+ (API 26+) — APK

### Reproducible CI (recommended)
1. Push a tag `v3.*` or run `Build Android v3.0 APK`.
2. Workflow installs Java 17 + Android SDK and runs Gradle 8.7 `assembleDebug`.
3. Artifact: debug-signed APK (`com.proxyhunter.app`, versionName 3.0.0, versionCode 300).
4. For a release-signed APK, add an upload keystore as GitHub Secrets and a `signingConfigs` block in `android/app/build.gradle.kts`.

### Local Android Studio
1. Open `android/` as a Gradle project (Android Studio Ladybug or newer).
2. `./gradlew assembleDebug` (or Build → Make Project).
3. Install the APK from `android/app/build/outputs/apk/debug/`.

Permissions requested: INTERNET, ACCESS_NETWORK_STATE, FOREGROUND_SERVICE, FOREGROUND_SERVICE_DATA_SYNC, POST_NOTIFICATIONS. No storage/root permission is required: exports use `Download/ProxyHunter/` via scoped storage.

## Build limitations in the delivery environment

The delivery environment is Android/Termux. It has Java/keytool but **no Android SDK, no Gradle, no PyInstaller and no Tkinter**. Therefore:

- `ProxyHunter_v3.0_Android.apk` — **NOT BUILT HERE** (BLOCKED: no Android SDK/Gradle). CI workflow and complete sources are provided.
- `ProxyHunter_v3.0_Windows.exe` / `ProxyHunter_v3.0_Setup.exe` — **NOT BUILT HERE** (BLOCKED: Windows toolchain, PyInstaller and tkinter unavailable). CI workflow and complete sources are provided.
- No fake APK/EXE files were created.

See `TEST_REPORT.md` for exact statuses and `PRODUCTION_READINESS.md` for the verdict.
