"""Encodage FFmpeg et vérifications du MP4 final."""
import base64
import re
import shutil
import subprocess
import unicodedata
import wave

from h2m.deps import has_encoder
from h2m.ui import good, warn


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
# Réglages x264 et qualité JPEG des captures pour chaque niveau de qualité.
QUALITY = {
    "fast": {"crf": 24, "preset": "ultrafast", "jpeg": 80},
    "standard": {"crf": 18, "preset": "veryfast", "jpeg": 90},
    "high": {"crf": 15, "preset": "slow", "jpeg": 95},
}


def safe_name(name):
    """Nom de fichier portable (sans accents ni caractères spéciaux), ou '' s'il ne reste rien."""
    name = re.sub(r"\.(html?|mp4)$", "", (name or "").strip(), flags=re.I)
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._-")[:80]


def output_path(html_path, args):
    """Le MP4 porte le nom du fichier HTML (ou --name) et est enregistré à côté de lui."""
    base = safe_name(getattr(args, "name", "")) or html_path.stem
    if getattr(args, "test", 0):
        base += "_test"
    elif getattr(args, "preview", False):
        base += "_apercu"
    return html_path.with_name(base + ".mp4")


def start_encoder(out_path, fps, dur, audio_inputs, err_path, quality="standard", loudnorm=False, audio_speed=1.0):
    """audio_inputs : (Path, volume[, offset]) ; offset aligne la piste sur la première image."""
    q = QUALITY[quality]
    mix_tail = ("loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,alimiter=limit=0.95"
                if loudnorm else "alimiter=limit=0.95")
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
            if abs(float(audio_speed) - 1.0) > 1e-6:
                filters.append(f"atempo={float(audio_speed):.4f}")
            filters.extend(["aresample=48000:async=1:first_pts=0",
                            f"volume={vol}", "apad", f"atrim=duration={dur:.3f}"])
            parts.append(f"[{i + 1}:a]{','.join(filters)}[a{i}]")
        if n == 1:
            parts.append(f"[a0]{mix_tail}[a]")
        else:
            labels = "".join(f"[a{i}]" for i in range(n))
            parts.append(f"{labels}amix=inputs={n}:duration=first:dropout_transition=0,volume={n},{mix_tail}[a]")
        cmd += ["-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v"]

    # H.264 High + yuv420p + AAC stéréo 48 kHz + faststart : accepté par TikTok, Reels et Shorts.
    vcodec = (["-c:v", "libx264", "-preset", q["preset"], "-crf", str(q["crf"]), "-profile:v", "high"]
              if has_encoder("libx264") else ["-c:v", "mpeg4", "-q:v", "2"])
    cmd += ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"] + vcodec + ["-pix_fmt", "yuv420p", "-r", str(fps)]
    cmd += ["-vsync", "cfr"]
    if n:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    cmd += ["-t", f"{dur:.3f}", "-movflags", "+faststart", str(out_path)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=open(err_path, "wb"))


# ----------------------------------------------------------------------------
# Rendu
# ----------------------------------------------------------------------------
def verify_sync(path, fps, dur):
    """Compare durées vidéo/audio et durée attendue avec ffprobe. Retourne (vidéo, audio, écart_ms)."""
    if not shutil.which("ffprobe"):
        return None, None, None

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
        return None, a, None
    gap_ms = abs(v - a) * 1000 if a is not None else None
    if a is not None and abs(v - a) > 1.5 / fps:
        warn(f"Écart durée vidéo/audio : {gap_ms:.0f} ms (vidéo {v:.2f}s, audio {a:.2f}s).")
    elif a is not None:
        good(f"Synchro vérifiée : vidéo {v:.2f}s · audio {a:.2f}s.")
    if abs(v - dur) > 2.0 / fps:
        warn(f"Durée finale {v:.2f}s au lieu de {dur:.2f}s attendues.")
    return v, a, gap_ms


def check_audio_level(path, expected):
    """Avertit si la piste audio du MP4 final est absente ou quasi silencieuse. Retourne le pic en dB."""
    if not expected or not shutil.which("ffmpeg"):
        return None
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
                        "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"max_volume:\s*(-?inf|-?[\d.]+)\s*dB", r.stderr)
    if not m:
        warn("Aucune piste audio exploitable dans la vidéo finale.")
        return None
    peak = float("-inf") if "inf" in m.group(1) else float(m.group(1))
    if peak < -50:
        warn(f"Piste audio quasi silencieuse (pic {m.group(1)} dB) : le son n'a probablement pas été capturé.")
    else:
        good(f"Niveau audio vérifié : pic {peak:.1f} dB.")
    return peak


def unique_path(p):
    if not p.exists():
        return p
    i = 2
    while True:
        q = p.with_name(f"{p.stem}_{i}{p.suffix}")
        if not q.exists():
            return q
        i += 1
