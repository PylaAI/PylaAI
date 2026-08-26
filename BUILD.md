# Building the PylaAI desktop app

PylaAI now runs as a single native Windows window (via pywebview) instead of a
console plus a browser tab. The `PylaAI.spec` file bundles it into one `PylaAI.exe`
carrying the app icon.

## Prerequisites

- **Windows** — PyInstaller does not cross-compile, so the `.exe` must be built
  on a Windows machine.
- Python 3.11.9, with the project dependencies installed:

  ```sh
  python setup.py install
  pip install pywebview pyinstaller
  ```

  On Windows, pywebview uses the built-in Edge WebView2 runtime (present on
  Windows 10/11), so there is nothing extra to install for the window itself.

## Build

```sh
pyinstaller PylaAI.spec
```

The executable lands in `dist/PylaAI.exe`. It bundles the web UI (`templates/`,
`static/`), configs, models, images and the scrcpy server jar, and takes its
icon from `images/logo.ico`.

## Notes

- **Console window:** `PylaAI.spec` keeps `console=True` so logs stay visible,
  which is useful while stabilising the build. For a pure GUI app with no console,
  set `console=False` in the spec.
- **Run without the native window:** set `PYLA_NO_WINDOW=1` to fall back to
  opening the UI in the default browser (handy for development).
- **Antivirus:** freshly built, unsigned PyInstaller executables are sometimes
  flagged by Windows Defender / SmartScreen. Code-signing the `.exe` with a
  certificate removes most of these warnings for end users.
- **Icon:** replace `images/logo.ico` to change the application icon. Keep it a
  real multi-size `.ico` (the current one is 256x256) for a crisp taskbar icon.
