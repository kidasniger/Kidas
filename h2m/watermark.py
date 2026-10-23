"""Ajout d'un filigrane animé au MP4 final, sans toucher au HTML source."""
import shutil
import subprocess
from pathlib import Path

ANIMATIONS = {"pulse", "fade", "float", "fixed"}
POSITIONS = {"bottom-right", "bottom-left", "top-right", "top-left", "center"}


def validate_watermark(text="RENDRAX", animation="pulse", position="bottom-right",
                       opacity=0.45, size=0.07):
    if not isinstance(text, str) or not text.strip() or len(text) > 80:
        raise ValueError("Le texte du filigrane doit contenir de 1 à 80 caractères.")
    if animation not in ANIMATIONS:
        raise ValueError("Animation de filigrane non prise en charge.")
    if position not in POSITIONS:
        raise ValueError("Position du filigrane non prise en charge.")
    if not 0.1 <= float(opacity) <= 1.0:
        raise ValueError("L’opacité doit être comprise entre 10 % et 100 %.")
    if not 0.02 <= float(size) <= 0.12:
        raise ValueError("La taille doit être comprise entre 2 % et 12 %.")
    return text.strip(), animation, position, float(opacity), float(size)


def _escape_drawtext(value):
    return (value.replace("\\", "\\\\").replace(":", "\\:")
            .replace("'", "\\'").replace("%", "\\%").replace(",", "\\,")
            .replace("[", "\\[").replace("]", "\\]"))


def watermark_filter(text, animation, position, opacity, size):
    text, animation, position, opacity, size = validate_watermark(
        text, animation, position, opacity, size
    )
    alpha = {
        "pulse": f"{opacity:.4f}*(0.72+0.28*sin(2*PI*t/2))",
        "fade": f"{opacity:.4f}*(0.5+0.5*sin(2*PI*t/5))",
        "float": f"{opacity:.4f}",
        "fixed": f"{opacity:.4f}",
    }[animation]
    margin = "w*0.025"
    if position == "bottom-right":
        x, y = f"w-tw-{margin}", f"h-th-{margin}"
    elif position == "bottom-left":
        x, y = margin, f"h-th-{margin}"
    elif position == "top-right":
        x, y = f"w-tw-{margin}", margin
    elif position == "top-left":
        x, y = margin, margin
    else:
        x, y = "(w-tw)/2", "(h-th)/2"
    if animation == "float":
        y = f"{y}+sin(2*PI*t/4)*h*0.006"
    # Losange de marque + texte dans un seul calque : aucune superposition de couches.
    safe_text = _escape_drawtext("◆  " + text)
    return (f"drawtext=font='DejaVu Sans':text='{safe_text}':fontcolor=white:"
            f"fontsize=h*{size:.5f}:alpha='{alpha}':x={x}:y={y}")


def apply_watermark(source, destination, text="RENDRAX", animation="pulse",
                    position="bottom-right", opacity=0.45, size=0.07):
    """Encode a watermarked copy while stream-copying audio to preserve its timing."""
    source, destination = Path(source), Path(destination)
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError("Le MP4 source est absent ou vide.")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg est requis pour intégrer le filigrane.")
    filters = watermark_filter(text, animation, position, opacity, size)
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-vf", filters, "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
        str(destination),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=1800, check=False)
    if result.returncode != 0 or not destination.is_file() or destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise RuntimeError("Échec de l’ajout du filigrane : " + (result.stderr or "sortie MP4 invalide")[-1200:])
    # Replace only after a complete successful encode; original HTML is never opened for writing.
    source.replace(source.with_suffix(source.suffix + ".pre-watermark"))
    source.with_suffix(source.suffix + ".pre-watermark").replace(source)
    destination.replace(source)
    return source
