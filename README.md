# PylaAI

[![CC BY-NC 4.0 License](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc/4.0/)
[![Discord](https://img.shields.io/badge/Discord-5865F2?logo=discord&logoColor=white)](https://discord.gg/xUusk3fw4A)
[![Trello](https://img.shields.io/badge/Trello-0079BF?logo=trello&logoColor=white)](https://trello.com/b/SAz9J6AA/public-pyla-trello)

> [!WARNING]
> **Warning**: There are two versions of PylaAI, you are currently browsing the source code for developers. Please visit our [Discord](https://discord.gg/xUusk3fw4A) to use the compiled version, which comes as a ready-to-use `.exe`.

PylaAI is currently the best external Brawl Stars bot.

## Requirements

- **NVIDIA GPUs**
  - Automatically installs compatible **CUDA + PyTorch**
  - Optimized for **GTX 10-series → RTX 50-series**

- **AMD GPUs**
  - Native **ROCm** support for Radeon / Ryzen GPUs

- **Intel / Generic GPUs**
  - Uses **DirectML** acceleration on Windows
  - Works well with integrated graphics

## Installation

You will need [Python 3.11.9](https://www.python.org/downloads/release/python-3119/).

### Windows

```sh
python setup.py install
```

### Other Platforms

The official PylaAI does **NOT** support other platforms such as Linux or Mac, but you can visit [Unofficial Ports](https://github.com/4D1-TooFarGone/Pyla-Ports) for cross-platform support.

## Using PylaAI

> [!NOTE]
> **Note**: This open-source version runs in localhost mode. The cloud features have been disabled by default.

Run the bot:

```sh
python main.py
```

Pyla opens in its own desktop window (an installed Edge / Chrome / Brave is used as the window host, without any browser UI), so it behaves like a regular Windows application: Pyla colored title bar, own taskbar entry, and closing the window shuts Pyla down.

### Startup options

| Flag | Effect |
| --- | --- |
| *(none)* | Console visible, UI in the Pyla desktop window |
| `--no-console` | Hides the console window, output goes to `%LOCALAPPDATA%\PylaAI\pyla.log`. Ignored when Pyla is started from an existing terminal, so your own terminal is never hidden. |
| `--no-webapp` | Opens the UI in the default browser instead of the desktop window |

Set `PYLA_WEBAPP_BROWSER` to a browser executable to pick which one hosts the window.

> [!NOTE]
> When compiling with Nuitka, keep the default console mode (`--windows-console-mode=force`): the console is hidden at runtime by `--no-console`, so it has to exist in the first place. Everything the desktop window needs is in `desktop.py`, which only uses the standard library and `ctypes`.


## License

This project is **not permitted to be sold or monetized** under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/).

## Maintainer

### Developers

- **ivanyordanovgt**
- **AngelFireLA**
- **awarzu**

### Contributors

- **Maayan080**
- **simonrejzek**
- **bocchi-the-cat**
- **Ariko842**
