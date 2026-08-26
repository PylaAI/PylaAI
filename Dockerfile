# PylaAI headless (Linux) image.
#
# Runs the bot logic + web UI on a server. It does NOT run an Android emulator:
# Brawl Stars needs a GPU to render, so keep BlueStacks (or another emulator) on
# a machine with a GPU and point this container at it over ADB.
FROM python:3.11-slim

# System libraries:
# - libgl1 / libglib2.0-0: required by opencv-python at import time
# - ffmpeg libs: required by PyAV (av) for H.264 decoding of the scrcpy stream
# - android-tools-adb: the adb client used to reach the emulator
# - tini: clean PID 1 signal handling
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libavcodec-extra \
        libavformat59 \
        libavdevice59 \
        android-tools-adb \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first so the layer caches across code changes.
# The platform markers in requirements.txt select onnxruntime (not directml)
# and drop the Windows-only packages automatically on Linux.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Then the source.
COPY . .

# Headless server defaults; override at runtime.
ENV PYLA_HEADLESS=1 \
    PYLA_HOST=0.0.0.0 \
    PYLA_PORT=8000 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

ENTRYPOINT ["tini", "--"]
CMD ["python", "main.py"]
