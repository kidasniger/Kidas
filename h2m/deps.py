"""Dépendances système : Python, FFmpeg, Chromium."""
import os
import re
import shutil
import subprocess
import sys

from h2m.ui import die, info


IS_TERMUX = "com.termux" in os.environ.get("PREFIX", "") or os.path.isdir("/data/data/com.termux")


def sh(cmd):
    try:
        return subprocess.call(cmd) == 0
    except FileNotFoundError:
        return False


def sudo():
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return []
    return ["sudo"] if shutil.which("sudo") else []


def find_chrome():
    for n in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome"):
        p = shutil.which(n)
        if p:
            return p
    return None


def ensure_deps():
    try:
        import websocket  # noqa: F401
    except ImportError:
        info("Installation de websocket-client (pip)…")
        base = [sys.executable, "-m", "pip", "install", "-q"]
        if not (sh(base + ["websocket-client"]) or sh(base + ["--break-system-packages", "websocket-client"])):
            die("Impossible d'installer websocket-client. Essaie : pip install websocket-client")

    if not shutil.which("ffmpeg"):
        info("Installation de FFmpeg…")
        if IS_TERMUX:
            sh(["pkg", "install", "-y", "ffmpeg"])
        elif shutil.which("apt-get"):
            sh(sudo() + ["apt-get", "install", "-y", "ffmpeg"])
        if not shutil.which("ffmpeg"):
            die("FFmpeg introuvable. Termux : pkg install ffmpeg")

    if not find_chrome():
        info("Installation de Chromium…")
        if IS_TERMUX:
            sh(["pkg", "install", "-y", "tur-repo"])
            sh(["pkg", "install", "-y", "chromium"])
        elif shutil.which("apt-get"):
            if not sh(sudo() + ["apt-get", "install", "-y", "chromium"]):
                sh(sudo() + ["apt-get", "install", "-y", "chromium-browser"])
        if not find_chrome():
            die(
                "Chromium introuvable.\n"
                "  Termux : pkg install tur-repo && pkg install chromium\n"
                "  Si ça échoue sur ton appareil : utilise proot-distro (Debian) puis apt install chromium."
            )


def has_encoder(name):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return re.search(rf"\b{name}\b", out) is not None
