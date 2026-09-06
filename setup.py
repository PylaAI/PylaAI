import sys
import platform
import subprocess
import os
import shutil
import glob
import importlib

# --- LOOP-PROOF BOOTSTRAP ---

def bootstrap():
    if os.environ.get("PYLAAI_BOOTSTRAP") == "1":
        return
    try:
        import jaraco.functools
        import wheel
    except ImportError:
        print("\nDetected missing core tools. Stabilizing environment...")
        os.environ["PYLAAI_BOOTSTRAP"] = "1"
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
        print("Environment stabilized. Restarting setup...\n")
        subprocess.run([sys.executable] + sys.argv)
        sys.exit(0)

if any(cmd in sys.argv for cmd in ["install", "develop"]):
    bootstrap()

from setuptools import setup, find_packages

def get_requirement_name(req):
    req = req.strip()

    if " @ " in req:
        name = req.split(" @ ", 1)[0].strip()
    else:
        name = req
        for sep in ["~=", ">=", "<=", "==", "!=", ">", "<"]:
            name = name.split(sep, 1)[0]

    name = name.split("[", 1)[0].strip()
    return name.replace("-", "_").lower()

def check_base_requirements(req_list):
    print("\nVerifying base requirements...")
    for req in req_list:
        pkg_name = get_requirement_name(req)
        mapping = {
            "opencv_python": "cv2",
            "discord.py": "discord",
            "pillow": "PIL",
            "pywin32": "win32api",
            "onnxruntime_directml": "onnxruntime",
            "pycryptodome": "Crypto",
            "flask": "flask",
        }
        import_name = mapping.get(pkg_name, pkg_name)

        try:
            importlib.import_module(import_name)
            print(f"  [OK] {req}")
        except ImportError:
            print(f"  [INSTALLING] {req}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", req])

def get_gpu_info():
    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader,nounits"],
            encoding='utf-8'
        )
        cc = float(output.strip().split('\n')[0])
        return "nvidia", cc
    except:
        return "other", 0.0

# --- MAIN SETUP ---
install_requires = [
    "aiohttp~=3.13",
    "opencv-python~=4.11",
    "numpy~=2.3",
    "onnxruntime-directml~=1.24",
    "requests~=2.32",
    "toml~=0.10",
    "pillow>=11.2.1",
    "discord.py~=2.7",
    "packaging>=25.0",
    "pywin32>=311",
    "adbutils~=2.12",
    "av~=12.3",
    "Flask~=3.1",
    "pycryptodome~=3.21",
    "pywebview~=6.2.1"
]

setup(
    name="PylaAI",
    version="1.0.0",
    packages=find_packages(exclude=["api", "cfg", "images", "models"]),
    install_requires=install_requires,
)

if any(cmd in sys.argv for cmd in ["install", "develop"]):
    try:
        check_base_requirements(install_requires)

        # --- ONNX ACCELERATOR SETUP ---
        gpu_type, cc = get_gpu_info()
        installed_onnx = "ONNX Runtime (DirectML)"

        if gpu_type == "nvidia":
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "onnxruntime-gpu"])
                installed_onnx = "ONNX Runtime (GPU)"
            except Exception:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "onnxruntime-directml"])
                installed_onnx = "ONNX Runtime (DirectML)"
        else:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "onnxruntime-directml"])
            installed_onnx = "ONNX Runtime (DirectML)"

        # Conflict Resolution
        subprocess.check_call([sys.executable, "-m", "pip", "install", "adbutils==2.12.0", "av==12.3.0"])

        os.system('cls' if os.name == 'nt' else 'clear')
        print("\n" + "="*50 + "\n              SETUP COMPLETED!                \n" + "="*50)
        print(
            f"  - ONNX Engine:      {installed_onnx}\n"
            + "="*50 + "\n"
        )

    except Exception as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)
