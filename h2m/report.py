"""Résumé de fin de rendu : mode, audio, synchronisation."""
import os

from h2m.ui import good, warn


def audio_verdict(report):
    """Retourne (état, texte) avec état dans ok / warn / none."""
    tracks = report.get("audio_tracks") or []
    peak = report.get("peak_db")
    if not tracks:
        return "none", "aucune piste audio : vidéo muette"
    if peak is None:
        return "warn", "pistes ajoutées mais niveau non mesuré"
    if peak < -50:
        return "warn", f"quasi silencieux (pic {peak:.1f} dB)"
    return "ok", f"détecté (pic {peak:.1f} dB)"


def print_report(report):
    state, audio_text = audio_verdict(report)
    gap = report.get("sync_gap_ms")
    sync_text = "non applicable" if gap is None else f"écart {gap:.0f} ms"
    lines = [
        ("Fichier", report["source"]),
        ("Vidéo", report["output"]),
        ("Mode", f"{report['mode']} · profil {report['label']}"),
        ("Format", f"{report['width']}×{report['height']} · {report['fps']} i/s · {report['duration']:.2f} s"),
        ("Qualité", report["quality"] + (" · volume normalisé" if report.get("loudnorm") else "")),
        ("Audio", audio_text + (" · " + ", ".join(report["audio_tracks"]) if report.get("audio_tracks") else "")),
        ("Synchro", sync_text),
    ]
    print("\n\x1b[1mRésumé du rendu\x1b[0m")
    for key, value in lines:
        print(f"  {key:<8} {value}")
    if state == "ok":
        good("Audio présent dans la vidéo.")
    elif state == "warn":
        warn("Vérifie l'audio de la vidéo : " + audio_text + ".")
    else:
        warn("La vidéo est muette.")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        icon = {"ok": "OK", "warn": "A vérifier", "none": "Muet"}[state]
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### Résumé du rendu\n\n| | |\n|---|---|\n")
            for key, value in lines:
                f.write(f"| {key} | {value} |\n")
            f.write(f"| Verdict audio | **{icon}** |\n\n")
