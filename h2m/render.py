"""Rendu image par image d'un fichier HTML."""
import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from h2m.browser import CDP, launch_chrome, page_ws_url, stop_chrome
from h2m.deps import IS_TERMUX, find_chrome
from h2m.encode import (QUALITY, check_audio_level, output_path, start_encoder, unique_path, verify_sync,
                        write_wav, write_wav_payload)
from h2m.profiles import (PRECISE_PROFILES, choose_frame_size, detect_profile, editpro_duration, extract_audio,
                          inject_base_url, inject_generic_audio_capture, patch_html)
from h2m.report import print_report
from h2m.scripts_js import JS_HELPERS
from h2m.ui import die, fmt_time, good, info, warn


def select_fps(profile, requested="auto"):
    """Use 60 fps for seekable/synchronized profiles and 30 for generic HTML."""
    if requested is None or str(requested).lower() == "auto":
        # Les animations IA silencieuses sont seekables, mais 30 i/s réduit le temps de rendu.
        if profile == "rendraxai":
            return 30
        return 60 if profile in PRECISE_PROFILES else 30
    fps = int(requested)
    if not 1 <= fps <= 120:
        raise ValueError("La fréquence d’images doit être comprise entre 1 et 120 i/s.")
    return fps


def select_quality(requested="auto", scale=1.0, test=0, preview=False):
    """Use faster encoding for previews/reduced exports and standard otherwise."""
    if requested and requested != "auto":
        return requested
    if preview or float(test or 0) > 0 or float(scale or 1.0) < 1.0:
        return "fast"
    return "standard"


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
        selected_quality = select_quality(
            getattr(args, "quality", "auto"), getattr(args, "scale", 1.0),
            getattr(args, "test", 0), getattr(args, "preview", False)
        )
        info(f"Fichier vérifié : {label}")
        info(f"Qualité d’encodage automatique : {selected_quality}.")
        text, profile = patch_html(text)
        precise_candidate = profile in PRECISE_PROFILES
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
            if profile == "rendraxai":
                check = "(()=>!!document.querySelector('.stage')&&typeof D==='number'&&typeof window.__rendraxSeek==='function')()"
            elif profile == "kidas":
                check = "(()=>!!document.querySelector('.stage')&&document.querySelectorAll('audio').length>=1&&typeof D==='number'&&typeof window.__setT==='function')()"
            elif profile == "voicevideo":
                check = "(()=>!!document.querySelector('#stage')&&!!window.__video&&typeof window.__video.seek==='function'&&document.querySelectorAll('audio').length>=1)()"
            elif profile == "musicpro":
                check = "(()=>!!document.querySelector('#st')&&typeof render==='function'&&typeof D==='number'&&typeof vP!=='undefined'&&typeof mP!=='undefined')()"
            elif profile == "gsapvideo":
                check = "(()=>!!document.querySelector('#st')&&!!document.querySelector('#a')&&typeof gsap!=='undefined'&&typeof tl!=='undefined'&&typeof SUB!=='undefined')()"
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
            if profile in ("kidas", "musicpro", "rendraxai"):
                total = float(cdp.ev("D"))
            elif profile == "voicevideo":
                total = float(cdp.ev("window.__video.duration"))
            elif profile == "gsapvideo":
                # The embedded narration is the master clock for the original GSAP timeline.
                total = float(cdp.ev("document.querySelector('#a').duration"))
            else:
                total = editpro_duration(text)
            dur = min(total, args.duration) if args.duration > 0 else total
            if args.test > 0:
                dur = min(dur, args.test)
            # Native browser animations run around 60 Hz; preserve that cadence for GSAP timeline videos.
            fps = select_fps(profile, getattr(args, "fps", "auto"))
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
            if not audio_inputs and profile != "rendraxai":
                die("Aucune piste audio valide n’a été récupérée pour ce profil synchronisé. Le MP4 muet a été bloqué.")

            cdp.ev("window.__seek(0)")
            r = cdp.ev("(()=>{const r=document.querySelector('.stage,#stage,#st').getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()")
            if abs(r[2] - W) > 2 or abs(r[3] - H) > 2:
                warn(f"La scène mesure {r[2]:.0f}×{r[3]:.0f} au lieu de {W}×{H} : rendu possiblement flou.")
            clip = {"x": round(r[0]), "y": round(r[1]), "width": W, "height": H, "scale": args.scale}
            mode = "timeline silencieuse" if profile == "rendraxai" else "synchronisé"
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
            fps = select_fps(profile, getattr(args, "fps", "auto"))
            n_frames = max(1, int(round(dur * fps)))
            info(f"Mode universel · durée {dur:.2f} s · {fps} i/s · capture de la fenêtre")
            clip = {"x": 0, "y": 0, "width": W, "height": H, "scale": args.scale}
            audio_inputs = []
            mode = "universel"

            # Certaines animations (dont EditPro – Vidéo 60 s) restent immobiles
            # tant que leur bouton de démarrage n'a pas reçu une vraie action pointeur.
            try:
                target = cdp.ev(r"""(() => {
                    const action = /(d[eé]marrer|start|lancer|commencer|commencez|lire|play|lecture|begin|▶|▷)/i;
                    const nodes = [...document.querySelectorAll('body *')];
                    const visible = nodes.map(el => {
                      const r = el.getBoundingClientRect();
                      const st = getComputedStyle(el);
                      const label = ((el.innerText || el.value || '') + ' ' +
                        (el.getAttribute('aria-label') || '') + ' ' + (el.title || '')).trim();
                      const buttonLike = el.matches('button,[role="button"],input[type=button],input[type=submit],a[role="button"]') ||
                        typeof el.onclick === 'function' || el.hasAttribute('onclick') || st.cursor === 'pointer';
                      const largeOverlay = r.width * r.height >= innerWidth * innerHeight * 0.2;
                      return {el, r, label, clickable: buttonLike || largeOverlay,
                        visible: r.width > 0 && r.height > 0 && st.display !== 'none' &&
                          st.visibility !== 'hidden' && Number(st.opacity) > 0.01};
                    }).filter(x => x.visible && x.clickable && action.test(x.label));
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

        out_final = unique_path(output_path(html_path, args))
        out_tmp = tmp / "out.mp4"
        err_path = tmp / "ffmpeg.log"
        frame_files = []
        if is_precise:
            enc = start_encoder(out_tmp, fps, n_frames / fps, audio_inputs, err_path,
                                quality=selected_quality, loudnorm=args.loudnorm)

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
            shot = cdp.call("Page.captureScreenshot", format="jpeg", quality=QUALITY[selected_quality]["jpeg"], clip=clip)
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
            enc = start_encoder(out_tmp, fps, n_frames / fps, audio_inputs, err_path,
                                quality=selected_quality, loudnorm=args.loudnorm)
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
        if getattr(args, "watermark", True):
            from h2m.watermark import apply_watermark
            apply_watermark(
                out_final, tmp / "watermarked.mp4",
                text=getattr(args, "watermark_text", "RENDRAX"),
                animation=getattr(args, "watermark_animation", "pulse"),
                position=getattr(args, "watermark_position", "bottom-right"),
                opacity=float(getattr(args, "watermark_opacity", 0.45)),
                size=float(getattr(args, "watermark_size", 0.07)),
            )
        video_duration, audio_duration, gap_ms = verify_sync(out_final, fps, n_frames / fps)
        if is_precise and audio_inputs:
            if video_duration is None or audio_duration is None:
                die("Le MP4 final n’expose pas une piste audio/vidéo vérifiable.")
            if gap_ms is not None and gap_ms > max(80.0, 2500.0 / fps):
                die(f"Écart audio/vidéo trop grand ({gap_ms:.0f} ms) : MP4 non validé.")
        peak = check_audio_level(out_final, bool(audio_inputs))
        good(f"Terminé en {fmt_time(time.monotonic() - start)} → {out_final}")
        print_report({
            "source": html_path.name, "output": out_final.name, "mode": mode, "label": label,
            "width": W, "height": H, "fps": fps, "duration": n_frames / fps,
            "quality": selected_quality, "loudnorm": args.loudnorm,
            "audio_tracks": [item[0].stem for item in audio_inputs],
            "peak_db": peak, "sync_gap_ms": gap_ms,
        })
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


def _is_browser_failure(exc):
    """Vrai pour une panne de Chromium ou de sa connexion (et non une erreur de la page)."""
    try:
        from websocket import WebSocketException
    except ImportError:
        WebSocketException = ()
    if isinstance(exc, (OSError, WebSocketException)):
        return True
    return isinstance(exc, RuntimeError) and bool(
        re.search(r"closed|crash|disconnect|Target|Inspected target", str(exc), re.I))


def render_with_retry(html_path, args, attempts=2):
    """Relance le rendu une fois si Chromium plante, au lieu de perdre tout le travail."""
    for attempt in range(1, attempts + 1):
        try:
            return render(html_path, args)
        except Exception as e:  # noqa: BLE001
            if attempt == attempts or not _is_browser_failure(e):
                raise
            warn(f"Chromium s'est arrêté ({e}). Nouvelle tentative {attempt + 1}/{attempts}…")
