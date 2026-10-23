"""Ajout d'un filigrane RENDRAX animé au MP4 final, sans modifier le HTML."""
import json
import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ANIMATIONS = {"pulse", "fade", "float", "fixed"}
POSITIONS = {"bottom-right", "bottom-left", "top-right", "top-left", "center"}
FPS = 20
DURATION_MS = 2000


def validate_watermark(text="RENDRAX", animation="pulse", position="bottom-right",
                       opacity=0.45, size=0.07):
    if not isinstance(text, str) or not text.strip() or len(text) > 80:
        raise ValueError("Le texte du filigrane doit contenir de 1 à 80 caractères.")
    if animation not in ANIMATIONS:
        raise ValueError("Animation de filigrane non prise en charge.")
    if position not in POSITIONS:
        raise ValueError("Position du filigrane non prise en charge.")
    try:
        opacity, size = float(opacity), float(size)
    except (TypeError, ValueError) as exc:
        raise ValueError("L’opacité et la taille doivent être numériques.") from exc
    if not math.isfinite(opacity) or not 0.1 <= opacity <= 1.0:
        raise ValueError("L’opacité doit être comprise entre 10 % et 100 %.")
    if not math.isfinite(size) or not 0.02 <= size <= 0.12:
        raise ValueError("La taille doit être comprise entre 2 % et 12 %.")
    return text.strip(), animation, position, opacity, size


def _font(size, bold=False):
    paths = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"]
        if bold else
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]
    )
    for name in paths:
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default()


def _make_apng(path, frame_width, frame_height, text, animation, opacity, size):
    """Create a compact RGBA animation with the repository's real RENDRAX icon."""
    target_height = max(18, round(frame_height * size))
    font_size = max(12, round(target_height * 0.72))
    font = _font(font_size, bold=True)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    text_box = probe.textbbox((0, 0), text, font=font, stroke_width=0)
    text_width = max(1, text_box[2] - text_box[0])
    text_height = max(1, text_box[3] - text_box[1])
    pad = max(3, round(target_height * 0.08))
    gap = max(4, round(target_height * 0.12))
    icon_height = max(12, round(target_height * 0.86))
    icon_path = Path(__file__).resolve().parents[1] / "logo" / "rendrax_icon_cutout.png"
    if icon_path.is_file():
        with Image.open(icon_path) as original:
            icon = original.convert("RGBA")
        icon_width = max(1, round(icon.width * icon_height / icon.height))
        icon = icon.resize((icon_width, icon_height), Image.Resampling.LANCZOS)
    else:
        # A geometric fallback avoids making rendering depend on an optional artwork file.
        icon_width = icon_height
        icon = Image.new("RGBA", (icon_width, icon_height), (0, 0, 0, 0))
        d = ImageDraw.Draw(icon)
        d.polygon([(icon_width // 2, 0), (icon_width, icon_height // 2),
                   (icon_width // 2, icon_height), (0, icon_height // 2)],
                  fill=(255, 255, 255, 255))
    canvas_width = pad * 2 + icon_width + gap + text_width
    canvas_height = max(icon_height, text_height) + pad * 2
    frame_count = FPS * DURATION_MS // 1000
    frames = []
    for index in range(frame_count):
        phase = 2 * math.pi * index / frame_count
        if animation == "pulse":
            factor = 0.72 + 0.28 * math.sin(phase)
        elif animation == "fade":
            factor = 0.5 + 0.5 * math.sin(phase)
        else:
            factor = 1.0
        alpha = max(0, min(255, round(255 * opacity * factor)))
        frame = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
        rgba_icon = icon.copy()
        # Scale the logo's alpha channel by the chosen watermark opacity.
        channel = rgba_icon.getchannel("A").point(lambda value: round(value * alpha / 255))
        rgba_icon.putalpha(channel)
        icon_y = (canvas_height - icon_height) // 2
        frame.alpha_composite(rgba_icon, (pad, icon_y))
        draw = ImageDraw.Draw(frame)
        text_y = (canvas_height - text_height) // 2 - text_box[1]
        draw.text((pad + icon_width + gap, text_y), text, font=font,
                  fill=(255, 255, 255, alpha), stroke_width=0)
        frames.append(frame)
    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        path, format="PNG", save_all=True, append_images=frames[1:],
        duration=DURATION_MS // frame_count, loop=0, disposal=0, blend=0,
        optimize=False,
    )
    return canvas_width, canvas_height


def _ffprobe_dimensions(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Impossible de lire les dimensions de la vidéo source.")
    try:
        stream = json.loads(result.stdout)["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
    except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("La vidéo source n’a pas de dimensions valides.") from exc
    if width < 2 or height < 2:
        raise RuntimeError("Les dimensions de la vidéo source sont invalides.")
    return width, height


def _overlay_filter(position, animation, frame_width, frame_height):
    margin_x, margin_y = f"W*0.025", f"H*0.025"
    if position == "bottom-right":
        x, y = f"W-w-{margin_x}", f"H-h-{margin_y}"
    elif position == "bottom-left":
        x, y = margin_x, f"H-h-{margin_y}"
    elif position == "top-right":
        x, y = f"W-w-{margin_x}", margin_y
    elif position == "top-left":
        x, y = margin_x, margin_y
    else:
        x, y = "(W-w)/2", "(H-h)/2"
    if animation == "float":
        y += "+sin(2*PI*t/4)*H*0.006"
    return (f"[1:v]format=rgba,setpts=PTS-STARTPTS[wm];"
            f"[0:v][wm]overlay=x='{x}':y='{y}':eval=frame:eof_action=repeat:shortest=1[v]")


def apply_watermark(source, destination, text="RENDRAX", animation="pulse",
                    position="bottom-right", opacity=0.45, size=0.07):
    """Overlay an animated PNG; copy audio packets unchanged to preserve sync."""
    text, animation, position, opacity, size = validate_watermark(
        text, animation, position, opacity, size
    )
    source, destination = Path(source), Path(destination)
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError("Le MP4 source est absent ou vide.")
    if source.resolve() == destination.resolve():
        raise ValueError("Le fichier temporaire du filigrane doit différer du MP4 source.")
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg et ffprobe sont requis pour intégrer le filigrane.")
    frame_width, frame_height = _ffprobe_dimensions(source)
    animation_file = destination.with_suffix(".apng")
    _make_apng(animation_file, frame_width, frame_height, text, animation, opacity, size)
    filter_complex = _overlay_filter(position, animation, frame_width, frame_height)
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-stream_loop", "-1", "-i", str(animation_file),
        "-filter_complex", filter_complex, "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
        str(destination),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=1800, check=False)
        if result.returncode != 0 or not destination.is_file() or destination.stat().st_size == 0:
            raise RuntimeError("Échec de l’ajout du filigrane : " +
                               (result.stderr or "sortie MP4 invalide")[-1200:])
        # Ensure the replacement stays on the same filesystem and only happens after success.
        shutil.move(str(destination), str(source))
        return source
    finally:
        animation_file.unlink(missing_ok=True)
