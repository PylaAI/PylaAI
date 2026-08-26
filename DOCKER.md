# Running PylaAI on Linux with Docker

This runs the **open-source** PylaAI (the bot logic + web UI) headless on a
Linux server. It does not include the early-access features and does not run an
Android emulator.

## What runs where

Brawl Stars is a real-time 3D game and needs a GPU to render, so the emulator
cannot live in this container on a CPU-only server. The working split is:

```
   Linux server (this container)            Machine with a GPU
  +-----------------------------+          +----------------------+
  |  PylaAI bot + web UI        |   ADB    |  BlueStacks / emulator |
  |  (vision, control, Flask)   |<-------->|  running Brawl Stars   |
  +-----------------------------+          +----------------------+
```

The container talks to the emulator through an **ADB server** running next to
BlueStacks. Nothing about the game rendering happens on the server.

## 1. Build

```sh
docker compose build
```

The `requirements.txt` platform markers automatically install `onnxruntime`
(CPU) instead of the Windows-only `onnxruntime-directml`, and skip `pywin32` /
`pywebview`. No code changes are needed to build on Linux.

## 2. Expose the emulator's ADB server

On the machine running BlueStacks (Windows), start an ADB server that listens
for the container:

```sh
adb kill-server
adb -a -P 5037 nodaemon server
```

`-a` makes it listen on all interfaces. **This is unauthenticated remote control
of the machine** — only expose it over a private network (Tailscale/WireGuard),
never a public IP, and firewall the port to the VPN interface only.

## 3. Configure and run

```sh
export PYLA_WEB_PASSWORD='choose-a-strong-password'
export ADB_HOST='100.x.y.z'   # Tailscale IP of the BlueStacks machine
export ADB_PORT=5037
docker compose up -d
```

Open `http://<server>:8000` and log in with user `pyla` (override with
`PYLA_WEB_USERNAME`) and your password.

> Put the container behind an HTTPS reverse proxy (Caddy/nginx) in production —
> Basic Auth over plain HTTP sends the password in the clear.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `PYLA_WEB_PASSWORD` | (empty) | Enables the Basic Auth gate. Empty = no gate. |
| `PYLA_WEB_USERNAME` | `pyla` | Username for the gate. |
| `PYLA_HEADLESS` | `1` | Server mode: no native window, no browser. |
| `PYLA_HOST` / `PYLA_PORT` | `0.0.0.0` / `8000` | Bind address for the UI. |
| `ANDROID_ADB_SERVER_HOST` | `host.docker.internal` | Where the ADB server lives. |
| `ANDROID_ADB_SERVER_PORT` | `5037` | ADB server port. |

## Known limitation

`window_controller.restart_adb_server()` kills the remote ADB server on a
connection hiccup and cannot restart it across the network, which would break a
long-running remote setup. Fixing it (skip the kill when the ADB host is remote)
is the next step for a robust 24/7 remote deployment.
