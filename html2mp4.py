#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Ré-exports : les tests et les anciens scripts importent ces noms depuis html2mp4.
from h2m.browser import CDP, free_port, http_json, launch_chrome, page_ws_url, stop_chrome  # noqa: E402,F401
from h2m.deps import IS_TERMUX, ensure_deps, find_chrome, has_encoder, sh, sudo  # noqa: E402,F401
from h2m.encode import (QUALITY, check_audio_level, output_path, safe_name, start_encoder,  # noqa: E402,F401
                        unique_path, verify_sync, write_wav, write_wav_payload)
from h2m.menu import pick_file, scan_html  # noqa: E402,F401
from h2m.profiles import (MIME_EXT, PRECISE_PROFILES, PROFILES, choose_frame_size,  # noqa: E402,F401
                          detect_profile, detect_stage_size, editpro_duration, extract_audio,
                          inject_base_url, inject_generic_audio_capture, patch_html)
from h2m.render import render, render_with_retry  # noqa: E402,F401
from h2m.scripts_js import GENERIC_AUDIO_CAPTURE, JS_HELPERS  # noqa: E402,F401
from h2m.ui import die, fmt_time, good, human_size, info, warn  # noqa: E402,F401


def parse_fps(value):
    if str(value).lower() == "auto":
        return "auto"
    try:
        fps = int(value)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("Utilise « auto » ou un entier entre 1 et 120.") from error
    if not 1 <= fps <= 120:
        raise argparse.ArgumentTypeError("La fréquence doit être comprise entre 1 et 120 i/s.")
    return fps


def main():
    ap = argparse.ArgumentParser(description="HTML animé → MP4")
    ap.add_argument("dossier", nargs="?", help="dossier à scanner (défaut : dossier du script)")
    ap.add_argument("--file", help="fichier HTML à convertir directement (sans menu)")
    ap.add_argument("--fps", type=parse_fps, default="auto",
                    help="auto (60 i/s pour profils synchronisés, 30 pour HTML générique), ou 1–120")
    ap.add_argument("--scale", type=float, default=1.0, help="échelle de sortie, ex. 0.5 = 540×960 (défaut 1)")
    ap.add_argument("--test", type=float, default=0, help="ne rendre que les N premières secondes")
    ap.add_argument("--duration", type=float, default=0, help="durée maximale en secondes ; 0 = durée détectée ou 60 s en mode universel")
    ap.add_argument("--format", choices=("auto", "portrait", "landscape", "square"), default="auto", help="format de sortie : auto, portrait, paysage ou carré")
    ap.add_argument("--quality", choices=("auto", "fast", "standard", "high"), default="auto",
                    help="auto, fast (rapide), standard ou high (plus net)")
    ap.add_argument("--preview", action="store_true", help="aperçu rapide : demi-résolution, qualité fast, fichier *_apercu.mp4")
    ap.add_argument("--loudnorm", action="store_true", help="normalise le volume à -16 LUFS (recommandé pour les réseaux sociaux)")
    ap.add_argument("--name", default="", help="nom du MP4 (sans extension) ; défaut : nom du fichier HTML")
    args = ap.parse_args()
    if args.preview:
        args.quality = "fast"
        args.scale = min(args.scale, 0.5)

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
        render_with_retry(chosen, args)
    except KeyboardInterrupt:
        print("\nAnnulé.")
        sys.exit(130)
    except RuntimeError as e:
        die(str(e))


if __name__ == "__main__":
    main()
