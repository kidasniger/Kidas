#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
html2mp4.py - Convertit une animation HTML (type « KIDAS Vidéo ») en MP4,
sans enregistrement d'écran : rendu image par image + audio, assemblé par FFmpeg.

Utilisation (Termux ou Linux) :
    python html2mp4.py                 # scanne le dossier du script
    python html2mp4.py ~/storage/downloads
    python html2mp4.py --test 10       # rendu rapide des 10 premières secondes
    python html2mp4.py --file kidas.html   # sans menu (utilisé par GitHub Actions)
    python html2mp4.py --fps 24 --scale 0.5

Menu : ↑/↓ naviguer · Espace choisir · Entrée confirmer · q quitter
La vidéo est enregistrée dans le même dossier que le fichier HTML.

Particularité : ce script est écrit pour les pages dont l'horloge est la piste
audio (cas du fichier KIDAS : scène pilotée par un état React « t »). Il lit
l'audio (voix + musique) dans le HTML et recrée les effets sonores hors-ligne.
Internet est nécessaire pendant le rendu (React et la police Sora sont chargés
depuis un CDN).
"""
import argparse
import base64
import json
import os
import re
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave
from pathlib import Path

IS_TERMUX = "com.termux" in os.environ.get("PREFIX", "") or os.path.isdir("/data/data/com.termux")


# ----------------------------------------------------------------------------
# Affichage
# ----------------------------------------------------------------------------
def info(m):
    print(f"\x1b[36m→\x1b[0m {m}", flush=True)


def good(m):
    print(f"\x1b[32m✓\x1b[0m {m}", flush=True)


def warn(m):
    print(f"\x1b[33m! {m}\x1b[0m", flush=True)


def die(m):
    print(f"\x1b[31m✗ {m}\x1b[0m", flush=True)
    sys.exit(1)


# ----------------------------------------------------------------------------
# Dépendances
# ----------------------------------------------------------------------------
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


# ----------------------------------------------------------------------------
# Menu de sélection (Espace = choisir, Entrée = confirmer)
# ----------------------------------------------------------------------------
def human_size(n):
    for u in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or u == "Go":
            return f"{n:.0f} {u}" if u == "o" else f"{n:.1f} {u}"
        n /= 1024


def scan_html(folder):
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in (".html", ".htm")]
    return sorted(files, key=lambda p: p.name.lower())


def _read_key(fd):
    ch = os.read(fd, 1)
    if ch == b"\x1b":
        if select.select([fd], [], [], 0.05)[0]:
            seq = os.read(fd, 2)
            if seq == b"[A":
                return "up"
            if seq == b"[B":
                return "down"
        return "esc"
    if ch == b" ":
        return "space"
    if ch in (b"\r", b"\n"):
        return "enter"
    if ch == b"\x03":
        raise KeyboardInterrupt
    return ch.decode(errors="ignore")


def pick_file(files):
    """Retourne le fichier choisi (Path)."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        for i, f in enumerate(files, 1):
            print(f"  {i}. {f.name}")
        try:
            n = int(input("Numéro du fichier : ").strip())
            return files[n - 1]
        except (ValueError, IndexError):
            die("Choix invalide.")

    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    cur, mark = 0, None
    view = min(len(files), 10)
    top = 0
    block = view + 1
    first = True

    def render():
        nonlocal top
        cols = shutil.get_terminal_size((60, 20)).columns
        if cur < top:
            top = cur
        if cur >= top + view:
            top = cur - view + 1
        lines = []
        for i in range(top, top + view):
            f = files[i]
            ptr = "❯" if i == cur else " "
            box = "[x]" if i == mark else "[ ]"
            line = f"{ptr} {box} {f.name}  ({human_size(f.stat().st_size)})"
            line = line[: cols - 1]
            lines.append(f"\x1b[1;36m{line}\x1b[0m" if i == cur else line)
        more = f"  ({cur + 1}/{len(files)})" if len(files) > view else ""
        lines.append(f"\x1b[2m↑/↓ naviguer · Espace choisir · Entrée confirmer · q quitter{more}\x1b[0m")
        return lines

    print("\nFichiers HTML trouvés :\n")
    sys.stdout.write("\x1b[?25l")
    try:
        tty.setcbreak(fd)
        while True:
            if not first:
                sys.stdout.write(f"\x1b[{block}A")
            first = False
            for ln in render():
                sys.stdout.write("\x1b[2K" + ln + "\n")
            sys.stdout.flush()
            k = _read_key(fd)
            if k in ("up", "k"):
                cur = (cur - 1) % len(files)
            elif k in ("down", "j"):
                cur = (cur + 1) % len(files)
            elif k == "space":
                mark = None if mark == cur else cur
            elif k == "enter":
                choice = mark if mark is not None else cur
                return files[choice]
            elif k in ("q", "esc"):
                print("\nAnnulé.")
                sys.exit(0)
            elif k.isdigit() and k != "0" and int(k) <= len(files):
                cur = int(k) - 1
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()


# ----------------------------------------------------------------------------
# Client DevTools (CDP) minimal : pas besoin de Playwright ni de Node
# ----------------------------------------------------------------------------
class CDP:
    def __init__(self, ws_url):
        import websocket

        self.ws = websocket.create_connection(ws_url, timeout=180, suppress_origin=True)
        self.n = 0

    def call(self, method, **params):
        self.n += 1
        i = self.n
        self.ws.send(json.dumps({"id": i, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == i:
                if "error" in msg:
                    raise RuntimeError(f"{method} : {msg['error'].get('message')}")
                return msg.get("result", {})

    def ev(self, expr, await_promise=True):
        r = self.call("Runtime.evaluate", expression=expr, awaitPromise=await_promise, returnByValue=True)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise RuntimeError((d.get("exception") or {}).get("description") or d.get("text") or "erreur JS")
        return r.get("result", {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http_json(url, timeout=2):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return json.loads(opener.open(url, timeout=timeout).read())


def stop_chrome(proc):
    """Arrête Chromium et tous ses processus enfants."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def launch_chrome(exe, tmp, width, height):
    """Lance Chromium headless, retourne (process, port)."""
    reports = []
    for n, mode in enumerate(("--headless=new", "--headless")):
        port = free_port()
        log_path = tmp / f"chrome{n}.log"
        cmd = [
            exe, mode,
            f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={tmp / ('profile' + str(n))}",
            "--no-sandbox", "--no-zygote", "--disable-gpu", "--disable-dev-shm-usage",
            "--disable-extensions", "--disable-component-update",
            "--hide-scrollbars", "--mute-audio",
            "--no-first-run", "--no-default-browser-check",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            "--force-device-scale-factor=1",
            "--autoplay-policy=no-user-gesture-required",
            f"--window-size={width},{height}",
            "about:blank",
        ]
        with open(log_path, "wb") as lf:
            proc = subprocess.Popen(cmd, stdout=lf, stderr=lf, start_new_session=True)
        t0 = time.time()
        while time.time() - t0 < 90:  # le démarrage peut être lent sous proot
            if proc.poll() is not None:
                break
            try:
                http_json(f"http://127.0.0.1:{port}/json/version", 1)
                return proc, port
            except Exception:
                time.sleep(0.5)
        code = proc.poll()
        stop_chrome(proc)
        try:
            lines = [l for l in log_path.read_text(errors="ignore").splitlines()
                     if "dbus" not in l and "udev" not in l and l.strip()]
        except Exception:
            lines = []
        reports.append(f"  {mode} : {'arrêté (code ' + str(code) + ')' if code is not None else 'ne répond pas'}\n    "
                       + "\n    ".join(lines[-5:]))
    die("Chromium n'a pas démarré.\n" + "\n".join(reports))


def page_ws_url(port):
    for _ in range(60):
        try:
            for t in http_json(f"http://127.0.0.1:{port}/json/list", 2):
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    return t["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.25)
    die("Impossible de se connecter à Chromium (DevTools).")


# ----------------------------------------------------------------------------
# Préparation du HTML et de l'audio
# ----------------------------------------------------------------------------
def detect_profile(text):
    """
    Vérifie le fichier avant tout rendu. Retourne (profil, libellé) avec profil dans :
      kidas   : React + audio intégré (KIDAS Vidéo v2, KIDAS motion design 9:16)
      editpro : canvas + fonction render(t) + voix intégrée (EditPro – Vidéo 60 s)
      voicevideo : React + <audio> intégré + window.__video.seek(t)
      musicpro : canvas + render(t) + voix base64 et musique Web Audio (MusicPro – Vidéo)
      generic : autre page HTML (rendu universel en temps réel, synchro non garantie)
      invalid : ce n'est pas une page HTML exploitable
    """
    if len(text.strip()) < 20 or not re.search(r"<(?:!doctype|html|head|body|script|svg|canvas|div|style)\b", text, re.I):
        return "invalid", "Ce fichier ne ressemble pas à une page HTML."
    kidas = (
        text.count("const [t,setT]=useState(0),") == 1
        and bool(re.search(r"[.#]stage\s*\{", text))
        and bool(re.search(r"\bAUD\s*=\s*'data:audio/", text))
        and bool(re.search(r"\bD\s*=\s*\d", text))
    )
    if kidas:
        return "kidas", "KIDAS (React + audio intégré)"
    editpro = (
        "function render(t)" in text
        and text.count("(function loop(){let t=") == 1
        and "const IM=" in text
        and bool(re.search(r'"voice"\s*:\s*"[A-Za-z0-9+/=]{1000,}"', text))
    )
    if editpro:
        return "editpro", "EditPro (canvas + voix intégrée)"
    # MusicPro : canvas + render(t) piloté par ac.currentTime, voix base64 décodée par Web Audio
    # et musique synthétisée hors-ligne (OfflineAudioContext).
    musicpro = (
        "function render(t)" in text
        and bool(re.search(r"atob\(\s*VOICE\s*\)", text))
        and bool(re.search(r"function\s+music\s*\(", text))
        and bool(re.search(r"function\s+go\s*\(", text))
        and bool(re.search(r"\(function\s+lp\s*\(\)\s*\{", text))
        and bool(re.search(r"\bconst\s+D\s*=\s*\d", text))
        and bool(re.search(r"\bvP\s*=", text))
        and bool(re.search(r"\bmP\s*=", text))
    )
    if musicpro:
        return "musicpro", "MusicPro (canvas + voix et musique Web Audio)"
    # Pages « vidéo React » : piste <audio> intégrée + API window.__video (seek/duration)
    # qui pilotent l'animation depuis l'horloge de l'audio.
    voicevideo = (
        "window.__video" in text
        and bool(re.search(r"\bseek\s*\(", text))
        and bool(re.search(r"<audio\b[^>]*\ssrc=[\"']data:audio/", text, re.I))
        and bool(re.search(r"\bDUR\s*=", text))
    )
    if voicevideo:
        return "voicevideo", "Vidéo React (audio intégré + window.__video)"
    return "generic", "Page HTML générique (mode universel)"


def patch_html(text):
    """
    Rend le rendu déterministe selon le profil détecté. Retourne (texte, profil) ;
    profil vaut "" si aucun mode image par image n'est possible.
    """
    profile, _ = detect_profile(text)
    if profile == "kidas":
        # setT devient inactif en mode manuel : la boucle audio de la page ne l'écrase plus.
        a = "const [t,setT]=useState(0),"
        text = text.replace(a, "const [t,__s]=useState(0),setT=v=>{window.__manual||__s(v)},__hk=(window.__setT=__s),", 1)
        return text, "kidas"
    if profile == "editpro":
        a = "(function loop(){let t="
        text = text.replace(a, "(function loop(){if(window.__manual)return;let t=", 1)
        return text, "editpro"
    if profile == "voicevideo":
        # La boucle de la page ne doit plus relire l'horloge de l'audio, et l'audio ne doit pas démarrer seul.
        text = text.replace("const loop = () => { if (!au.paused)", "const loop = () => { if (!window.__manual && !au.paused)", 1)
        text = text.replace("function go() { if (!au.paused) return;", "function go() { if (window.__manual || !au.paused) return;", 1)
        return text, "voicevideo"
    if profile == "musicpro":
        # Le mode manuel est activé avant tout script : la page ne lance ni son horloge audio
        # (go) ni sa boucle temps réel (lp), et render(t) est appelé image par image.
        text = re.sub(r"function\s+go\s*\(\)\s*\{", lambda m: m.group(0) + "if(window.__manual)return;", text, count=1)
        text = re.sub(r"\(function\s+lp\s*\(\)\s*\{", lambda m: m.group(0) + "if(window.__manual)return;", text, count=1)
        manual = "<script>window.__manual=true</script>"
        m = re.search(r"<head\b[^>]*>", text, flags=re.I)
        text = text[:m.end()] + manual + text[m.end():] if m else manual + text
        return text, "musicpro"
    return text, ""


def editpro_duration(text):
    m = re.search(r"if\(t>=(\d+(?:\.\d+)?)\)\{t=", text)
    return float(m.group(1)) if m else 60.0


MIME_EXT = {"mpeg": "mp3", "mp3": "mp3", "wav": "wav", "x-wav": "wav", "ogg": "ogg", "mp4": "m4a", "aac": "aac", "webm": "webm"}


def extract_audio(text, tmp, profile="kidas"):
    """Retourne {'voice': Path|None, 'music': Path|None, 'music_volume': float}."""
    out = {"voice": None, "music": None, "music_volume": 0.2}
    if profile == "musicpro":
        return out  # pistes décodées par le navigateur : voir window.__wavOf
    if profile == "editpro":
        m = re.search(r'"voice"\s*:\s*"([A-Za-z0-9+/=]+)"', text)
        if m:
            p = tmp / "voice.mp3"
            p.write_bytes(base64.b64decode(m.group(1)))
            out["voice"] = p
        return out
    if profile == "voicevideo":
        tags = re.findall(r"<audio\b[^>]*\ssrc=[\"']data:audio/([a-z0-9.+-]+);base64,([A-Za-z0-9+/=]+)[\"']", text, re.I)
        for key, (mime, b64) in zip(("voice", "music"), tags):
            p = tmp / f"{key}.{MIME_EXT.get(mime.lower(), 'mp3')}"
            p.write_bytes(base64.b64decode(b64))
            out[key] = p
        return out
    for key, var in (("voice", "AUD"), ("music", "MUS")):
        m = re.search(var + r"='data:audio/([a-z0-9.+-]+);base64,([A-Za-z0-9+/=]+)'", text)
        if not m:
            continue
        ext = MIME_EXT.get(m.group(1), "mp3")
        p = tmp / f"{key}.{ext}"
        p.write_bytes(base64.b64decode(m.group(2)))
        out[key] = p
    v = re.search(r"\.current\.volume\s*=\s*(\d*\.?\d+)", text)
    if v:
        out["music_volume"] = min(1.0, float(v.group(1)))
    return out


def detect_stage_size(text):
    m = re.search(r"[.#](?:stage|st)\s*\{[^}]*?width:\s*(\d+)px;\s*height:\s*(\d+)px", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"\bW\s*=\s*(\d{3,4})\s*,\s*H\s*=\s*(\d{3,4})\b", text)  # const W = 1080, H = 1920
    return (int(m.group(1)), int(m.group(2))) if m else (1080, 1920)


JS_HELPERS = r"""
window.__raf = () => new Promise(r => { let d = false; const f = () => { if (!d) { d = true; r(); } };
  requestAnimationFrame(f); setTimeout(f, 120); });

window.__prep = async () => {
  const faces = [...document.fonts].filter(f => f.unicodeRange === 'U+0-10FFFF' || /U\+0000/.test(f.unicodeRange));
  await Promise.all(faces.map(f => f.load().catch(() => 0)));
  const au = [...document.querySelectorAll('audio')];
  await Promise.all(au.map(a => a.readyState >= 1 ? 1 :
    new Promise(r => { a.addEventListener('loadedmetadata', r, {once: true}); setTimeout(r, 15000); })));
  return au.map(a => a.duration);
};

window.__finish = async () => {
  await document.fonts.ready;
  const imgs = [...document.images];
  if (imgs.length) await Promise.all(imgs.map(i => i.decode ? i.decode().catch(() => 0) : 0));
  await window.__raf();
};

window.__seek = async (t) => {
  if (window.__profile === 'editpro') {
    if (!window.__ep) {
      window.__manual = true; window.__ep = true;
      run = true; vi = 0; subEnd = 0;
      const ui = document.querySelector('#ui'); if (ui) ui.style.display = 'none';
    }
    render(Math.max(0, t));
    await window.__finish();
    return 1;
  }
  if (window.__profile === 'musicpro') {
    window.__manual = true;
    try { run = 0; } catch (e) {}
    render(Math.max(0, t));
    await window.__finish();
    return 1;
  }
  if (window.__profile === 'voicevideo') {
    window.__manual = true;
    document.querySelectorAll('audio').forEach(a => { try { a.pause(); } catch (e) {} });
    if (window.ReactDOM && ReactDOM.flushSync) ReactDOM.flushSync(() => window.__video.seek(t));
    else { window.__video.seek(t); await window.__raf(); }
    await window.__finish();
    for (const b of document.querySelectorAll('#stage button'))
      if (/Touchez pour lancer|Rejouer/.test(b.textContent) && b.parentElement) b.parentElement.style.display = 'none';
    return 1;
  }
  if (window.__setT && window.ReactDOM && ReactDOM.flushSync) {
    window.__manual = true;
    ReactDOM.flushSync(() => window.__setT(t));
  } else {
    const au = document.querySelectorAll('audio');
    au.forEach(a => { a.currentTime = t; });
    await window.__raf();
    await new Promise(r => setTimeout(r, 40));
    await window.__raf();
  }
  await window.__finish();
  for (const d of document.querySelectorAll('.stage div'))
    if (!d.children.length && d.textContent.startsWith('Touchez pour lancer')) d.style.display = 'none';
  return 1;
};

window.__sfx = async () => {
  if (typeof SFX === 'undefined' || typeof EV === 'undefined') return '';
  const sr = 44100, L = Math.ceil((D + 1.5) * sr);
  const oc = new OfflineAudioContext(1, L, sr);
  let T = 0;
  Object.defineProperty(oc, 'currentTime', { get: () => T });
  const S2 = Object.create(SFX);
  S2.ac = oc; S2.m = oc.createGain(); S2.m.gain.value = .5; S2.m.connect(oc.destination);
  S2.nb = oc.createBuffer(1, sr, sr);
  const nd = S2.nb.getChannelData(0);
  for (let i = 0; i < sr; i++) nd[i] = Math.random() * 2 - 1;
  for (const [et, kind] of EV) { T = Math.max(0, et); S2.play(kind); }
  const buf = await oc.startRendering();
  const x = buf.getChannelData(0), pcm = new Int16Array(x.length);
  for (let i = 0; i < x.length; i++) { const v = Math.max(-1, Math.min(1, x[i])); pcm[i] = v < 0 ? v * 32768 : v * 32767; }
  const u8 = new Uint8Array(pcm.buffer);
  let bin = '';
  for (let i = 0; i < u8.length; i += 0x8000) bin += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(bin);
};

window.__wavOf = async (key) => {
  let buf = null;
  try { buf = await (key === 'voice' ? vP : mP); } catch (e) {}
  if (!buf || !buf.getChannelData) return '';
  const ch = Math.min(2, buf.numberOfChannels), n = buf.length, pcm = new Int16Array(n * ch);
  for (let c = 0; c < ch; c++) {
    const x = buf.getChannelData(c);
    for (let i = 0; i < n; i++) { const v = Math.max(-1, Math.min(1, x[i])); pcm[i * ch + c] = v < 0 ? v * 32768 : v * 32767; }
  }
  const u8 = new Uint8Array(pcm.buffer);
  let bin = '';
  for (let i = 0; i < u8.length; i += 0x8000) bin += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return buf.sampleRate + ':' + ch + ':' + btoa(bin);
};
0;
"""


def write_wav(path, pcm_bytes, sr=44100, channels=1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm_bytes)


def write_wav_payload(path, payload):
    """payload : « fréquence:canaux:PCM16 en base64 », produit par window.__wavOf."""
    sr, ch, b64 = payload.split(":", 2)
    write_wav(path, base64.b64decode(b64), int(sr), int(ch))


# ----------------------------------------------------------------------------
# FFmpeg
# ----------------------------------------------------------------------------
def start_encoder(out_path, fps, dur, audio_inputs, err_path):
    """audio_inputs : (Path, volume[, offset]) ; offset aligne la piste sur la première image."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-"]
    for item in audio_inputs:
        p, _ = item[:2]
        cmd += ["-i", str(p)]

    n = len(audio_inputs)
    if n:
        parts = []
        for i, item in enumerate(audio_inputs):
            _, vol, *extra = item
            offset = float(extra[0]) if extra else 0.0
            filters = []
            if offset > 0.001:
                filters.extend([f"atrim=start={offset:.3f}", "asetpts=PTS-STARTPTS"])
            elif offset < -0.001:
                filters.extend([f"adelay={int(round(-offset * 1000))}:all=1", "asetpts=PTS-STARTPTS"])
            filters.extend(["aresample=48000:async=1:first_pts=0",
                            f"volume={vol}", "apad", f"atrim=duration={dur:.3f}"])
            parts.append(f"[{i + 1}:a]{','.join(filters)}[a{i}]")
        if n == 1:
            parts.append("[a0]alimiter=limit=0.95[a]")
        else:
            labels = "".join(f"[a{i}]" for i in range(n))
            parts.append(f"{labels}amix=inputs={n}:duration=first:dropout_transition=0,volume={n},alimiter=limit=0.95[a]")
        cmd += ["-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v"]

    vcodec = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"] if has_encoder("libx264") else ["-c:v", "mpeg4", "-q:v", "2"]
    cmd += ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"] + vcodec + ["-pix_fmt", "yuv420p", "-r", str(fps)]
    cmd += ["-vsync", "cfr"]
    if n:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    cmd += ["-t", f"{dur:.3f}", "-movflags", "+faststart", str(out_path)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=open(err_path, "wb"))


# ----------------------------------------------------------------------------
# Rendu
# ----------------------------------------------------------------------------
def verify_sync(path, fps, dur):
    """Compare durées vidéo/audio et durée attendue avec ffprobe."""
    if not shutil.which("ffprobe"):
        return

    def probe(sel):
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", sel,
                            "-show_entries", "stream=duration", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True)
        try:
            return float(r.stdout.strip().split("\n")[0])
        except ValueError:
            return None

    v, a = probe("v:0"), probe("a:0")
    if v is None:
        warn("Vérification impossible : pas de piste vidéo lisible.")
        return
    if a is not None and abs(v - a) > 1.5 / fps:
        warn(f"Écart durée vidéo/audio : {abs(v - a) * 1000:.0f} ms (vidéo {v:.2f}s, audio {a:.2f}s).")
    elif a is not None:
        good(f"Synchro vérifiée : vidéo {v:.2f}s · audio {a:.2f}s.")
    if abs(v - dur) > 2.0 / fps:
        warn(f"Durée finale {v:.2f}s au lieu de {dur:.2f}s attendues.")


def check_audio_level(path, expected):
    """Avertit si la piste audio du MP4 final est absente ou quasi silencieuse."""
    if not expected or not shutil.which("ffmpeg"):
        return
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
                        "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"max_volume:\s*(-?inf|-?[\d.]+)\s*dB", r.stderr)
    if not m:
        warn("Aucune piste audio exploitable dans la vidéo finale.")
        return
    peak = float("-inf") if "inf" in m.group(1) else float(m.group(1))
    if peak < -50:
        warn(f"Piste audio quasi silencieuse (pic {m.group(1)} dB) : le son n'a probablement pas été capturé.")
    else:
        good(f"Niveau audio vérifié : pic {peak:.1f} dB.")


def unique_path(p):
    if not p.exists():
        return p
    i = 2
    while True:
        q = p.with_name(f"{p.stem}_{i}{p.suffix}")
        if not q.exists():
            return q
        i += 1


def fmt_time(s):
    s = int(s)
    return f"{s // 60}:{s % 60:02d}"




GENERIC_AUDIO_CAPTURE = r"""<script>
(() => {
  if (window.__h2mCaptureInstalled) return;
  window.__h2mCaptureInstalled = true;
  const Native = window.AudioContext || window.webkitAudioContext;
  const contexts = [];
  let active = false;
  const originalConnect = window.AudioNode && AudioNode.prototype.connect;
  if (originalConnect) {
    AudioNode.prototype.connect = function(destination, ...args) {
      const result = originalConnect.call(this, destination, ...args);
      try {
        const ctx = this.context;
        if (ctx && destination === ctx.destination && ctx.__h2mDest && !ctx.__h2mDup) {
          ctx.__h2mDup = true;
          originalConnect.call(this, ctx.__h2mDest);
          ctx.__h2mDup = false;
        }
      } catch (_) {}
      return result;
    };
  }
  function install(ctx) {
    if (!ctx || ctx.__h2mDest) return;
    try {
      ctx.__h2mDest = ctx.createMediaStreamDestination();
      ctx.__h2mChunks = [];
      ctx.__h2mRec = null;
      contexts.push(ctx);
      start(ctx);
    } catch (_) {}
  }
  if (Native) {
    function WrappedAudioContext(...args) {
      const ctx = new Native(...args);
      install(ctx);
      return ctx;
    }
    WrappedAudioContext.prototype = Native.prototype;
    try { Object.setPrototypeOf(WrappedAudioContext, Native); } catch (_) {}
    window.AudioContext = WrappedAudioContext;
    if (window.webkitAudioContext) window.webkitAudioContext = WrappedAudioContext;
  }
  function start(ctx) {
    if (!ctx || !ctx.__h2mDest || ctx.__h2mRec || !window.MediaRecorder) return;
    try {
      const type = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus' : 'audio/webm';
      const rec = new MediaRecorder(ctx.__h2mDest.stream, { mimeType: type });
      ctx.__h2mRec = rec;
      rec.ondataavailable = e => { if (e.data && e.data.size) ctx.__h2mChunks.push(e.data); };
      rec.start(250);
      ctx.__h2mRecStartPerf = performance.now();
      ctx.__h2mRecCt = ctx.currentTime;
    } catch (_) {}
  }
  window.__h2mStart = async () => {
    if (active) return contexts.length;
    active = true;
    if (Native) {
      for (const el of document.querySelectorAll('audio,video')) {
        try {
          if (!el.__h2mSource) {
            const ctx = new Native();
            install(ctx);
            const source = ctx.createMediaElementSource(el);
            el.__h2mSource = source;
            source.connect(ctx.destination);
          }
        } catch (_) {}
      }
    }
    for (const ctx of contexts) {
      try { await ctx.resume(); } catch (_) {}
      start(ctx);
    }
    for (const el of document.querySelectorAll('audio,video')) {
      try { el.muted = false; el.currentTime = 0; const p = el.play(); if (p) await p.catch(() => {}); } catch (_) {}
    }
    return contexts.length;
  };
  // L'horloge de l'AudioContext n'avance que lorsqu'il tourne, comme le flux enregistré :
  // elle donne un décalage fiable même si le contexte a démarré suspendu.
  window.__h2mMark = () => {
    window.__h2mVideoStartPerf = performance.now();
    for (const ctx of contexts) { try { ctx.__h2mMarkCt = ctx.currentTime; } catch (_) {} }
  };
  window.__h2mStop = async () => {
    const records = contexts.filter(c => c.__h2mRec);
    await Promise.all(records.map(c => new Promise(resolve => {
      const rec = c.__h2mRec;
      if (rec.state === 'inactive') return resolve();
      rec.addEventListener('stop', resolve, { once: true });
      try { rec.stop(); } catch (_) { resolve(); }
    })));
    const result = [];
    for (const ctx of records) {
      try {
        const blob = new Blob(ctx.__h2mChunks, { type: 'audio/webm' });
        if (blob.size < 500) continue;
        const data = await new Promise(resolve => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result).split(',').pop());
          reader.onerror = () => resolve('');
          reader.readAsDataURL(blob);
        });
        if (data) result.push({
          mime: blob.type || 'audio/webm',
          data,
          offset: (ctx.__h2mMarkCt != null && ctx.__h2mRecCt != null) ? ctx.__h2mMarkCt - ctx.__h2mRecCt :
            window.__h2mVideoStartPerf == null ? 0 :
            (window.__h2mVideoStartPerf - (ctx.__h2mRecStartPerf || window.__h2mVideoStartPerf)) / 1000
        });
      } catch (_) {}
    }
    return result;
  };
  window.addEventListener('load', () => { try { window.__h2mStart(); } catch (_) {} }, { once: true });
})();
</script>"""


def inject_base_url(text, base_url):
    """Conserve les chemins relatifs des images, scripts et médias du HTML original."""
    if re.search(r"<base\b", text, flags=re.I):
        return text
    tag = f'<base href="{base_url}">'
    m = re.search(r"<head\b[^>]*>", text, flags=re.I)
    if m:
        return text[:m.end()] + tag + text[m.end():]
    return tag + text


def inject_generic_audio_capture(text):
    """Installe l'enregistrement Web Audio avant les scripts de la page."""
    if re.search(r"__h2mCaptureInstalled", text):
        return text
    m = re.search(r"<head\b[^>]*>", text, flags=re.I)
    if m:
        return text[:m.end()] + GENERIC_AUDIO_CAPTURE + text[m.end():]
    return GENERIC_AUDIO_CAPTURE + text


def choose_frame_size(text, fmt):
    sizes = {"portrait": (1080, 1920), "landscape": (1920, 1080), "square": (1080, 1080)}
    return sizes[fmt] if fmt in sizes else detect_stage_size(text)


def render(html_path, args):
    tmp = Path(tempfile.mkdtemp(prefix="html2mp4_"))
    chrome = proc = cdp = enc = None
    wake = IS_TERMUX and shutil.which("termux-wake-lock")
    try:
        if wake:
            subprocess.call(["termux-wake-lock"])

        text = html_path.read_text(encoding="utf-8", errors="ignore")
        profile, label = detect_profile(text)
        if profile == "invalid":
            die(label)
        info(f"Fichier vérifié : {label}")
        text, profile = patch_html(text)
        precise_candidate = profile in ("kidas", "editpro", "voicevideo", "musicpro")
        W, H = choose_frame_size(text, "auto" if precise_candidate else args.format)
        page = tmp / "page.html"
        text = inject_base_url(text, html_path.parent.resolve().as_uri().rstrip("/") + "/")
        if not precise_candidate:
            text = inject_generic_audio_capture(text)
        page.write_text(text, encoding="utf-8")
        audio = extract_audio(text, tmp, profile) if precise_candidate else {"voice": None, "music": None, "music_volume": 0.2}
        info(f"Fenêtre {W}×{H} · mode : {'image par image (synchronisé)' if precise_candidate else 'universel (temps réel, synchro non garantie)'}")

        chrome = find_chrome()
        viewport_height = H + 300 if precise_candidate else H
        info("Démarrage de Chromium…")
        proc, port = launch_chrome(chrome, tmp, W, viewport_height)
        cdp = CDP(page_ws_url(port))
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        cdp.call("Emulation.setDeviceMetricsOverride", width=W, height=viewport_height, deviceScaleFactor=1, mobile=False)
        cdp.call("Page.navigate", url=page.as_uri())

        info("Chargement du document HTML…")
        t0 = time.time()
        ready = "(()=>({body:!!document.body,state:document.readyState}))()"
        last_state = {}
        while time.time() - t0 < 90:
            try:
                last_state = cdp.ev(ready, await_promise=False) or {}
                if last_state.get("body") and last_state.get("state") == "complete":
                    break
                if last_state.get("body") and time.time() - t0 > 15:
                    warn("La page n'a pas fini de charger toutes ses ressources ; essai de rendu avec le contenu disponible.")
                    break
            except RuntimeError:
                pass
            time.sleep(0.25)
        else:
            die("Chromium n'a pas réussi à créer le document HTML.")
        time.sleep(0.2)

        is_precise = False
        if precise_candidate:
            if profile == "kidas":
                check = "(()=>!!document.querySelector('.stage')&&document.querySelectorAll('audio').length>=1&&typeof D==='number'&&typeof window.__setT==='function')()"
            elif profile == "voicevideo":
                check = "(()=>!!document.querySelector('#stage')&&!!window.__video&&typeof window.__video.seek==='function'&&document.querySelectorAll('audio').length>=1)()"
            elif profile == "musicpro":
                check = "(()=>!!document.querySelector('#st')&&typeof render==='function'&&typeof D==='number'&&typeof vP!=='undefined'&&typeof mP!=='undefined')()"
            else:
                check = "(()=>!!document.querySelector('#stage')&&typeof render==='function'&&typeof IM==='object')()"
            t1 = time.time()
            while time.time() - t1 < 30 and not is_precise:
                try:
                    is_precise = bool(cdp.ev(check, await_promise=False))
                except RuntimeError:
                    is_precise = False
                if not is_precise:
                    time.sleep(0.5)
            if not is_precise:
                die(f"Fichier reconnu ({label}) mais la page ne s'est pas initialisée : "
                    "Internet est-il disponible pour charger React et les polices ?")

        if is_precise:
            cdp.ev(f"window.__profile = {json.dumps(profile)}; 0", await_promise=False)
            cdp.ev(JS_HELPERS, await_promise=False)
            cdp.ev("window.__prep()")
            if profile in ("kidas", "musicpro"):
                total = float(cdp.ev("D"))
            elif profile == "voicevideo":
                total = float(cdp.ev("window.__video.duration"))
            else:
                total = editpro_duration(text)
            dur = min(total, args.duration) if args.duration > 0 else total
            if args.test > 0:
                dur = min(dur, args.test)
            fps = args.fps
            n_frames = max(1, int(round(dur * fps)))
            info(f"Mode synchronisé · {label} · durée {dur:.2f} s · {fps} i/s")

            audio_inputs = []
            if audio["voice"]:
                audio_inputs.append((audio["voice"], 1.0))
            if audio["music"]:
                audio_inputs.append((audio["music"], audio["music_volume"]))
            if profile == "kidas":
                try:
                    b64 = cdp.ev("window.__sfx()")
                    if b64:
                        info("Effets sonores recréés.")
                        sfx = tmp / "sfx.wav"
                        write_wav(sfx, base64.b64decode(b64))
                        audio_inputs.append((sfx, 1.0))
                except Exception as e:  # noqa: BLE001
                    warn(f"Effets sonores ignorés : {e}")
            if profile == "musicpro":
                # Voix et musique sont lues telles que le navigateur les a décodées/synthétisées :
                # aucun format audio à deviner, et la musique inclut déjà son ducking.
                for key, label_fr in (("voice", "voix"), ("music", "musique")):
                    try:
                        payload = cdp.ev(f"window.__wavOf('{key}')")
                    except Exception as e:  # noqa: BLE001
                        warn(f"Piste {label_fr} ignorée : {e}")
                        continue
                    if payload:
                        p = tmp / f"{key}.wav"
                        write_wav_payload(p, payload)
                        audio_inputs.append((p, 1.0))
                        info(f"Piste {label_fr} récupérée depuis le navigateur.")
                    else:
                        warn(f"Piste {label_fr} introuvable ou non décodée par le navigateur.")
            if not audio_inputs:
                warn("Aucune piste audio trouvée dans ce fichier : la vidéo sera muette.")

            cdp.ev("window.__seek(0)")
            r = cdp.ev("(()=>{const r=document.querySelector('.stage,#stage,#st').getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()")
            if abs(r[2] - W) > 2 or abs(r[3] - H) > 2:
                warn(f"La scène mesure {r[2]:.0f}×{r[3]:.0f} au lieu de {W}×{H} : rendu possiblement flou.")
            clip = {"x": round(r[0]), "y": round(r[1]), "width": W, "height": H, "scale": args.scale}
            mode = "synchronisé"
        else:
            # Mode générique : la page n'a besoin ni de .stage, ni de D, ni d'AUD/MUS.
            if args.duration > 0:
                dur = args.duration
            else:
                try:
                    media_dur = cdp.ev("(()=>Math.max(0,...[...document.querySelectorAll('audio,video')].map(x=>x.duration).filter(x=>Number.isFinite(x)&&x>0)))()", await_promise=False)
                except RuntimeError:
                    media_dur = 0
                if not media_dur:
                    # Pas de <audio>/<video> : on cherche une durée déclarée par la page (const D = 48.59…).
                    try:
                        media_dur = cdp.ev(
                            "(()=>{for(const n of ['D','DUR','DURATION','TOTAL','TOTAL_DURATION','VIDEO_DURATION']){"
                            "try{const v=(0,eval)(n);if(typeof v==='number'&&isFinite(v)&&v>=2&&v<=900)return v}catch(e){}}return 0})()",
                            await_promise=False)
                    except RuntimeError:
                        media_dur = 0
                    if media_dur:
                        info(f"Durée déclarée par la page : {float(media_dur):.2f} s.")
                    else:
                        warn("Durée de la page non détectée : 60 s par défaut. Utilise --duration N pour la fixer.")
                dur = float(media_dur or 60.0)
            if args.test > 0:
                dur = min(dur, args.test)
            fps = args.fps
            n_frames = max(1, int(round(dur * fps)))
            info(f"Mode universel · durée {dur:.2f} s · {fps} i/s · capture de la fenêtre")
            clip = {"x": 0, "y": 0, "width": W, "height": H, "scale": args.scale}
            audio_inputs = []
            mode = "universel"

            # Certaines animations (dont EditPro – Vidéo 60 s) restent immobiles
            # tant que leur bouton de démarrage n'a pas reçu une vraie action pointeur.
            try:
                target = cdp.ev(r"""(() => {
                    const nodes = [...document.querySelectorAll(
                      'button,[role=' + '"button"' + '],input[type=button],input[type=submit],a[role=' + '"button"' + ']'
                    )];
                    const action = /(d[eé]marrer|start|lancer|commencer|commencez|lire|play|lecture|begin|▶|▷)/i;
                    const visible = nodes.map(el => {
                      const r = el.getBoundingClientRect();
                      const st = getComputedStyle(el);
                      const label = ((el.innerText || el.value || '') + ' ' +
                        (el.getAttribute('aria-label') || '') + ' ' + (el.title || '')).trim();
                      return {el, r, label, visible: r.width > 0 && r.height > 0 &&
                        st.display !== 'none' && st.visibility !== 'hidden' && Number(st.opacity) > 0.01};
                    }).filter(x => x.visible && action.test(x.label));
                    const chosen = visible.find(x => /(d[eé]marrer|start|lancer|commencer|lire avec|play|▶|▷)/i.test(x.label)) || visible[0];
                    return chosen ? {x: chosen.r.x + chosen.r.width/2,
                      y: chosen.r.y + chosen.r.height/2, label: chosen.label.slice(0, 100)} : null;
                })()""", await_promise=False)
                if target:
                    # CDP pointer events produisent une activation navigateur réelle,
                    # contrairement à HTMLElement.click() pour l'audio protégé par autoplay.
                    cdp.call("Input.dispatchMouseEvent", type="mouseMoved", x=target["x"], y=target["y"])
                    cdp.call("Input.dispatchMouseEvent", type="mousePressed", x=target["x"], y=target["y"], button="left", clickCount=1)
                    cdp.call("Input.dispatchMouseEvent", type="mouseReleased", x=target["x"], y=target["y"], button="left", clickCount=1)
                    info(f"Bouton de démarrage activé automatiquement : {target['label']}")
                    # Certains modèles décodent la narration de façon asynchrone après le clic.
                    has_known_ui = bool(cdp.ev("!!document.querySelector('#ui')", await_promise=False))
                    if has_known_ui:
                        t_click = time.monotonic()
                        while time.monotonic() - t_click < 8:
                            try:
                                started = cdp.ev(r"""(() => {
                                  const ui = document.querySelector('#ui');
                                  return !!(ui && getComputedStyle(ui).display === 'none');
                                })()""", await_promise=False)
                                if started:
                                    break
                            except RuntimeError:
                                pass
                            time.sleep(0.03)
                    else:
                        time.sleep(0.3)
                else:
                    info("Aucun bouton de démarrage évident trouvé ; capture de la page telle quelle.")

                cdp.ev("window.__h2mStart()")
                info("Capture audio du navigateur activée (médias HTML et Web Audio si disponibles).")
            except Exception as e:  # noqa: BLE001
                warn(f"Activation automatique ou capture audio indisponible : {e}")

        out_final = unique_path(html_path.with_suffix(".mp4") if not args.test else html_path.with_name(html_path.stem + "_test.mp4"))
        out_tmp = tmp / "out.mp4"
        err_path = tmp / "ffmpeg.log"
        frame_files = []
        if is_precise:
            enc = start_encoder(out_tmp, fps, n_frames / fps, audio_inputs, err_path)

        if not is_precise:
            # Référence de temps commune navigateur/FFmpeg pour aligner l'audio WebAudio.
            try:
                cdp.ev("(window.__h2mMark ? window.__h2mMark() : (window.__h2mVideoStartPerf = performance.now())); true", await_promise=False)
            except Exception:  # noqa: BLE001
                pass
        info(f"Rendu en cours ({mode})…")
        start = time.monotonic()
        slow_frames = 0
        frame_ts = []  # mode universel : instant réel (s) de chaque capture
        i = -1
        while True:
            i += 1
            if is_precise:
                if i >= n_frames:
                    break
                cdp.ev(f"window.__seek({i / fps:.5f})")
            else:
                # Mode universel : on capture jusqu'à ce que le TEMPS RÉEL atteigne la durée,
                # puis on remet les images à cadence constante (voir plus bas).
                delay = start + i / fps - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                if time.monotonic() - start >= dur:
                    break
                frame_ts.append(time.monotonic() - start)
            shot = cdp.call("Page.captureScreenshot", format="jpeg", quality=90, clip=clip)
            jpeg = base64.b64decode(shot["data"])
            if is_precise:
                try:
                    enc.stdin.write(jpeg)
                except BrokenPipeError:
                    break
            else:
                frame_path = tmp / f"frame-{i:06d}.jpg"
                frame_path.write_bytes(jpeg)
                frame_files.append(frame_path)
            if not is_precise and time.monotonic() > start + (i + 1) / fps:
                slow_frames += 1
            if i % max(1, fps // 2) == 0 or i == n_frames - 1:
                elapsed = time.monotonic() - start
                if is_precise:
                    eta = elapsed / (i + 1) * (n_frames - i - 1)
                    sys.stdout.write(f"\r  {i + 1}/{n_frames}  {100 * (i + 1) / n_frames:5.1f}%  reste ≈ {fmt_time(eta)}   ")
                else:
                    sys.stdout.write(f"\r  {min(elapsed, dur):.1f}/{dur:.1f} s  {i + 1} captures   ")
                sys.stdout.flush()
        print()

        if not is_precise:
            try:
                captures = cdp.ev("window.__h2mStop()")
                for idx, item in enumerate(captures or []):
                    p = tmp / f"browser-audio-{idx}.webm"
                    p.write_bytes(base64.b64decode(item["data"]))
                    if p.stat().st_size > 500:
                        audio_inputs.append((p, 1.0, float(item.get("offset", 0.0))))
                if audio_inputs:
                    warn("Les pistes audio génériques sont incluses ; vérifie la synchronisation et les sons spécifiques de la page.")
                else:
                    warn("Aucun son capturé : la page ne produit peut-être pas d'audio Web Audio/<audio>, ou elle attend un geste "
                         "de l'utilisateur. La vidéo sera muette.")
            except Exception as e:  # noqa: BLE001
                warn(f"Impossible de récupérer la piste audio du navigateur : {e}")
            if slow_frames:
                warn(f"{slow_frames}/{len(frame_files)} captures plus lentes que {fps} i/s : la chronologie reste exacte "
                     "(images répétées pour combler), mais l'animation sera moins fluide. "
                     "Essaie --fps 15 ou --scale 0.5. Pour une fluidité parfaite, la page doit exposer un mode image par image.")

        if not is_precise:
            info("Assemblage des images et de l'audio…")
            enc = start_encoder(out_tmp, fps, n_frames / fps, audio_inputs, err_path)
            # Remise à cadence constante : pour chaque instant k/fps on écrit la dernière image
            # réellement capturée avant cet instant. Image et audio restent ainsi sur la même horloge.
            j = 0
            last_data, last_idx = None, -1
            for k in range(n_frames):
                while j + 1 < len(frame_files) and frame_ts[j + 1] <= k / fps:
                    j += 1
                if frame_files:
                    if last_data is None or last_idx != j:
                        last_data, last_idx = frame_files[j].read_bytes(), j
                    try:
                        enc.stdin.write(last_data)
                    except BrokenPipeError:
                        break
                if k % max(1, fps * 5) == 0 or k == n_frames - 1:
                    sys.stdout.write(f"\r  Assemblage {k + 1}/{n_frames}")
                    sys.stdout.flush()
            print()

        try:
            enc.stdin.close()
        except Exception:
            pass
        enc.wait()
        if enc.returncode != 0 or not out_tmp.exists():
            die("FFmpeg a échoué :\n" + err_path.read_text(errors="ignore")[-1000:])

        shutil.move(str(out_tmp), str(out_final))
        verify_sync(out_final, fps, n_frames / fps)
        check_audio_level(out_final, bool(audio_inputs))
        good(f"Terminé en {fmt_time(time.monotonic() - start)} → {out_final}")
        return out_final
    finally:
        if cdp:
            cdp.close()
        if proc:
            stop_chrome(proc)
        if enc and enc.poll() is None:
            try:
                enc.kill()
            except Exception:
                pass
        if wake and shutil.which("termux-wake-unlock"):
            subprocess.call(["termux-wake-unlock"])
        shutil.rmtree(tmp, ignore_errors=True)

# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="HTML animé → MP4")
    ap.add_argument("dossier", nargs="?", help="dossier à scanner (défaut : dossier du script)")
    ap.add_argument("--file", help="fichier HTML à convertir directement (sans menu)")
    ap.add_argument("--fps", type=int, default=30, help="images par seconde (défaut 30)")
    ap.add_argument("--scale", type=float, default=1.0, help="échelle de sortie, ex. 0.5 = 540×960 (défaut 1)")
    ap.add_argument("--test", type=float, default=0, help="ne rendre que les N premières secondes")
    ap.add_argument("--duration", type=float, default=0, help="durée maximale en secondes ; 0 = durée détectée ou 60 s en mode universel")
    ap.add_argument("--format", choices=("auto", "portrait", "landscape", "square"), default="auto", help="format de sortie : auto, portrait, paysage ou carré")
    args = ap.parse_args()

    folder = Path(args.dossier).expanduser().resolve() if args.dossier else Path(__file__).resolve().parent
    if not folder.is_dir():
        die(f"Dossier introuvable : {folder}")

    print(f"\x1b[1mHTML → MP4\x1b[0m   dossier : {folder}")
    ensure_deps()

    chosen = None
    if args.file:
        chosen = Path(args.file).expanduser()
        if not chosen.is_absolute():
            chosen = folder / chosen
        if not chosen.is_file():
            die(f"Fichier introuvable : {chosen}")
    else:
        files = scan_html(folder)
        if not files:
            die("Aucun fichier .html dans ce dossier.")

    try:
        if chosen is None:
            chosen = pick_file(files)
        print(f"\nFichier choisi : \x1b[1m{chosen.name}\x1b[0m\n")
        render(chosen, args)
    except KeyboardInterrupt:
        print("\nAnnulé.")
        sys.exit(130)
    except RuntimeError as e:
        die(str(e))


if __name__ == "__main__":
    main()
