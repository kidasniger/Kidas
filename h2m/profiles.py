"""Détection des profils de fichiers, correctifs HTML et extraction audio."""
import base64
import re

from h2m.scripts_js import GENERIC_AUDIO_CAPTURE


def _is_kidas(text):
    return (
        text.count("const [t,setT]=useState(0),") == 1
        and bool(re.search(r"[.#]stage\s*\{", text))
        and bool(re.search(r"\bAUD\s*=\s*'data:audio/", text))
        and bool(re.search(r"\bD\s*=\s*\d", text))
    )


def _is_editpro(text):
    return (
        "function render(t)" in text
        and text.count("(function loop(){let t=") == 1
        and "const IM=" in text
        and bool(re.search(r'"voice"\s*:\s*"[A-Za-z0-9+/=]{1000,}"', text))
    )


def _is_musicpro(text):
    # Canvas + render(t) piloté par ac.currentTime, voix base64 décodée par Web Audio
    # et musique synthétisée hors-ligne (OfflineAudioContext).
    return (
        "function render(t)" in text
        and bool(re.search(r"atob\(\s*VOICE\s*\)", text))
        and bool(re.search(r"function\s+music\s*\(", text))
        and bool(re.search(r"function\s+go\s*\(", text))
        and bool(re.search(r"\(function\s+lp\s*\(\)\s*\{", text))
        and bool(re.search(r"\bconst\s+D\s*=\s*\d", text))
        and bool(re.search(r"\bvP\s*=", text))
        and bool(re.search(r"\bmP\s*=", text))
    )


def _is_voicevideo(text):
    # Pages « vidéo React » : piste <audio> intégrée + API window.__video (seek/duration)
    # qui pilotent l'animation depuis l'horloge de l'audio.
    return (
        "window.__video" in text
        and bool(re.search(r"\bseek\s*\(", text))
        and bool(re.search(r"<audio\b[^>]*\ssrc=[\"']data:audio/", text, re.I))
        and bool(re.search(r"\bDUR\s*=", text))
    )


def _is_gsapvideo(text):
    # GSAP timelines synchronized to a base64 audio track. These must be rendered frame-by-frame.
    return (
        bool(re.search(r"<audio\b[^>]*\bsrc=[\"']data:audio/[a-z0-9.+-]+;base64,", text, re.I))
        # Les variantes peuvent déclarer les timings dans T=[...] ou une durée D=...
        # et appeler tl.time(t,false) ou tl.time(Math.min(t,D),false).
        and bool(re.search(r"\b(?:const\s+T\s*=\s*\[\s*\d|const\s+D\s*=\s*\d)", text))
        and bool(re.search(r"\bSUB\s*=", text))
        and bool(re.search(r"\btl\s*=\s*gsap\.timeline\(\s*\{\s*paused\s*:\s*true\s*\}\s*\)", text))
        and bool(re.search(r"\btl\.time\([^;]*?,\s*false\s*\)", text))
        and bool(re.search(r"\bstarted\s*\?\s*a\.currentTime", text))
        and bool(re.search(r"requestAnimationFrame\s*\(\s*lp\s*\)", text))
        and bool(re.search(r"[.#]st\s*\{[^}]*?width:\s*\d+px;\s*height:\s*\d+px", text))
    )


# Table des profils reconnus, testés dans l'ordre. Pour en ajouter un : écrire son test
# _is_xxx(text), l'inscrire ici, puis prévoir son correctif dans patch_html et son audio
# dans extract_audio / render.
PROFILES = (
    ("kidas", "KIDAS (React + audio intégré)", _is_kidas),
    ("editpro", "EditPro (canvas + voix intégrée)", _is_editpro),
    ("musicpro", "MusicPro (canvas + voix et musique Web Audio)", _is_musicpro),
    ("voicevideo", "Vidéo React (audio intégré + window.__video)", _is_voicevideo),
    ("gsapvideo", "Vidéo GSAP synchronisée sur la piste audio", _is_gsapvideo),
)
PRECISE_PROFILES = tuple(name for name, _, _ in PROFILES)


def detect_profile(text):
    """
    Vérifie le fichier avant tout rendu. Retourne (profil, libellé) ; le profil est le nom
    d'une entrée de PROFILES (rendu image par image synchronisé), ou :
      generic : autre page HTML (rendu universel en temps réel, synchro non garantie)
      invalid : ce n'est pas une page HTML exploitable
    """
    if len(text.strip()) < 20 or not re.search(r"<(?:!doctype|html|head|body|script|svg|canvas|div|style)\b", text, re.I):
        return "invalid", "Ce fichier ne ressemble pas à une page HTML."
    for name, label, matches in PROFILES:
        if matches(text):
            return name, label
    return "generic", "Page HTML générique (mode universel)"


def patch_html(text):
    """
    Rend le rendu déterministe selon le profil détecté. Retourne (texte, profil) ;
    profil vaut "" si aucun mode image par image n'est possible.
    """
    profile, _ = detect_profile(text)
    if profile == "rendraxai":
        # Stoppe la boucle d'aperçu et laisse RENDRAX appeler render(t) pour chaque image.
        manual = "<script>window.__manual=true</script>"
        m = re.search(r"<head\b[^>]*>", text, flags=re.I)
        text = text[:m.end()] + manual + text[m.end():] if m else manual + text
        return text, "rendraxai"
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
    if profile == "gsapvideo":
        # Stop the audio-driven real-time loop and let the renderer seek the GSAP timeline directly.
        text = re.sub(r"\(function\s+lp\s*\(\)\s*\{", lambda m: m.group(0) + "if(window.__manual)return;", text, count=1)
        manual = "<script>window.__manual=true</script>"
        m = re.search(r"<head\b[^>]*>", text, flags=re.I)
        text = text[:m.end()] + manual + text[m.end():] if m else manual + text
        return text, "gsapvideo"
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
    if profile in ("voicevideo", "gsapvideo"):
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
