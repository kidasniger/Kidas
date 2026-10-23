import argparse
import base64
import importlib.util
import tempfile
import unittest
from pathlib import Path

from h2m.profiles import PRECISE_PROFILES
from h2m.render import select_fps, select_quality

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("html2mp4", ROOT / "html2mp4.py")
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


class Html2Mp4Tests(unittest.TestCase):
    def test_default_stage_size(self):
        self.assertEqual(renderer.detect_stage_size("<style>.stage{width:1080px;height:1920px}</style>"), (1080, 1920))

    def test_stage_size_falls_back_for_generic_html(self):
        self.assertEqual(renderer.detect_stage_size("<html><body>hello</body></html>"), (1080, 1920))

    def test_output_formats(self):
        sample = "<style>.stage{width:720px;height:1280px}</style>"
        self.assertEqual(renderer.choose_frame_size(sample, "portrait"), (1080, 1920))
        self.assertEqual(renderer.choose_frame_size(sample, "landscape"), (1920, 1080))
        self.assertEqual(renderer.choose_frame_size(sample, "square"), (1080, 1080))
        self.assertEqual(renderer.choose_frame_size(sample, "auto"), (720, 1280))

    def test_relative_asset_base_is_injected(self):
        html = "<html><head></head><body><img src='assets/pic.png'></body></html>"
        result = renderer.inject_base_url(html, "file:///tmp/source/")
        self.assertIn('<base href="file:///tmp/source/">', result)
        self.assertIn("assets/pic.png", result)

    def test_existing_base_is_preserved(self):
        html = '<html><head><base href="https://example.test/"></head></html>'
        self.assertEqual(renderer.inject_base_url(html, "file:///tmp/source/"), html)

    def test_audio_capture_is_injected_before_page_scripts(self):
        html = "<html><head><script>window.pageCode=true</script></head><body></body></html>"
        result = renderer.inject_generic_audio_capture(html)
        self.assertLess(result.index("__h2mCaptureInstalled"), result.index("window.pageCode=true"))
        self.assertIn("window.__h2mStop", result)

    def test_generic_capture_is_not_injected_twice(self):
        html = renderer.inject_generic_audio_capture("<html><head></head><body></body></html>")
        self.assertEqual(renderer.inject_generic_audio_capture(html), html)

    def test_fixtures_cover_css_canvas_and_webaudio(self):
        fixtures = ROOT / "tests" / "fixtures"
        self.assertTrue((fixtures / "css-animation.html").is_file())
        self.assertTrue((fixtures / "canvas-animation.html").is_file())
        self.assertTrue((fixtures / "webaudio.html").is_file())
        self.assertTrue((fixtures / "static.html").is_file())
        self.assertTrue((fixtures / "start-button.html").is_file())
        self.assertTrue((fixtures / "gsap-audio-timeline.html").is_file())

    # --- vérification automatique du fichier ---
    EDITPRO = ('<html><body><div id="stage"></div><script>const IM={"voice":"' + "QUJD" * 400 + '"};'
               'function render(t){} (function loop(){let t=4.6;render(t)})();</script></body></html>')

    def test_invalid_files_are_rejected(self):
        self.assertEqual(renderer.detect_profile("")[0], "invalid")
        self.assertEqual(renderer.detect_profile("bonjour, ceci est juste du texte")[0], "invalid")

    def test_plain_html_is_generic(self):
        self.assertEqual(renderer.detect_profile("<html><body><p>x</p></body></html>")[0], "generic")

    def test_kidas_file_is_recognised(self):
        text = (ROOT / "kidas.html").read_text(encoding="utf-8", errors="ignore")
        self.assertEqual(renderer.detect_profile(text)[0], "kidas")

    def test_editpro_pattern_is_recognised(self):
        self.assertEqual(renderer.detect_profile(self.EDITPRO)[0], "editpro")

    def test_kidas_patch_freezes_time_state(self):
        text = (ROOT / "kidas.html").read_text(encoding="utf-8", errors="ignore")
        patched, profile = renderer.patch_html(text)
        self.assertEqual(profile, "kidas")
        self.assertIn("window.__manual||__s(v)", patched)
        self.assertIn("window.__setT=__s", patched)

    def test_editpro_patch_stops_page_loop(self):
        patched, profile = renderer.patch_html(self.EDITPRO)
        self.assertEqual(profile, "editpro")
        self.assertIn("if(window.__manual)return;let t=", patched)

    def test_editpro_voice_is_extracted_and_duration_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            audio = renderer.extract_audio(self.EDITPRO, Path(d), "editpro")
            self.assertTrue(audio["voice"].is_file())
            self.assertIsNone(audio["music"])
            self.assertEqual(audio["voice"].read_bytes(), base64.b64decode("QUJD" * 400))
        self.assertEqual(renderer.editpro_duration(self.EDITPRO), 60.0)
        self.assertEqual(renderer.editpro_duration("if(t>=45){t=45;run=false}"), 45.0)

    MUSICPRO = ("<html><head></head><body><canvas id='st'></canvas><script>const D=48.59;let vP=0,mP=0;"
                "function render(t){} function music(){} function go(){ac.resume()} "
                "(function lp(){render(0);requestAnimationFrame(lp)})();"
                "const b=atob(VOICE);</script></body></html>")

    GSAPVIDEO = ('<html><head><style>#st{width:1080px;height:1920px}</style></head><body><div id="st"></div>'
                 '<audio id="a" src="data:audio/wav;base64,QUJD"></audio><script>'
                 'const T=[0,1],SUB=[[0,"start"]],tl=gsap.timeline({paused:true});'
                 'let started=0;(function lp(){const t=started?a.currentTime:1.6;tl.time(t,false);requestAnimationFrame(lp)})();'
                 '</script></body></html>')

    def test_gsap_audio_timeline_pattern_is_recognised(self):
        self.assertEqual(renderer.detect_profile(self.GSAPVIDEO)[0], "gsapvideo")
        self.assertIn("gsapvideo", renderer.PRECISE_PROFILES)

    def test_gsap_audio_timeline_patch_stops_real_time_loop(self):
        patched, profile = renderer.patch_html(self.GSAPVIDEO)
        self.assertEqual(profile, "gsapvideo")
        self.assertLess(patched.index("window.__manual=true"), patched.index("const T=[0,1]"))
        self.assertIn("(function lp(){if(window.__manual)return;", patched)

    def test_gsap_audio_timeline_audio_is_extracted(self):
        with tempfile.TemporaryDirectory() as d:
            audio = renderer.extract_audio(self.GSAPVIDEO, Path(d), "gsapvideo")
            self.assertTrue(audio["voice"].is_file())
            self.assertEqual(audio["voice"].read_bytes(), base64.b64decode("QUJD"))

    def test_musicpro_pattern_is_recognised(self):
        self.assertEqual(renderer.detect_profile(self.MUSICPRO)[0], "musicpro")

    def test_musicpro_patch_enables_manual_mode_before_page_scripts(self):
        patched, profile = renderer.patch_html(self.MUSICPRO)
        self.assertEqual(profile, "musicpro")
        self.assertLess(patched.index("window.__manual=true"), patched.index("const D=48.59"))
        self.assertIn("function go(){if(window.__manual)return;", patched)
        self.assertIn("(function lp(){if(window.__manual)return;", patched)

    def test_generic_capture_records_from_context_creation(self):
        result = renderer.inject_generic_audio_capture("<html><head></head><body></body></html>")
        self.assertIn("window.__h2mMark", result)
        self.assertNotIn("if (active) start(ctx)", result)

    def test_music_volume_is_read_from_page(self):
        with tempfile.TemporaryDirectory() as d:
            text = "AUD='data:audio/mpeg;base64,QUJD',MUS='data:audio/mpeg;base64,QUJD';mu.current.volume=.22"
            self.assertAlmostEqual(renderer.extract_audio(text, Path(d), "kidas")["music_volume"], 0.22)

    def test_output_path_uses_html_name(self):
        args = argparse.Namespace(name="", test=0, preview=False)
        self.assertEqual(renderer.output_path(Path("/x/ma video.html"), args), Path("/x/ma video.mp4"))

    def test_output_path_custom_name_is_sanitised(self):
        args = argparse.Namespace(name="a/b:c", test=0, preview=False)
        self.assertEqual(renderer.output_path(Path("/x/v.html"), args).parent, Path("/x"))
        self.assertNotIn("/", renderer.output_path(Path("/x/v.html"), args).name)

    def test_output_path_suffixes_for_test_and_preview(self):
        self.assertTrue(renderer.output_path(Path("/x/v.html"), argparse.Namespace(name="", test=5, preview=False)).name.endswith("_test.mp4"))
        self.assertTrue(renderer.output_path(Path("/x/v.html"), argparse.Namespace(name="", test=0, preview=True)).name.endswith("_apercu.mp4"))

    def test_quality_presets_cover_all_levels(self):
        for level in ("fast", "standard", "high"):
            self.assertIn("jpeg", renderer.QUALITY[level])

    def test_automatic_fps_uses_60_for_seekable_profiles_and_30_for_generic(self):
        for profile in PRECISE_PROFILES:
            self.assertEqual(select_fps(profile, "auto"), 60, profile)
        self.assertEqual(select_fps("generic", "auto"), 30)
        self.assertEqual(select_fps("generic", 24), 24)
        self.assertEqual(select_fps("gsapvideo", 24), 24)

    def test_automatic_quality_optimizes_preview_and_reduced_renders(self):
        self.assertEqual(select_quality("auto", scale=1, test=0), "standard")
        self.assertEqual(select_quality("auto", scale=0.5, test=0), "fast")
        self.assertEqual(select_quality("auto", scale=1, test=10), "fast")
        self.assertEqual(select_quality("high", scale=0.5, test=10), "high")

    def test_frontend_detects_specialized_audio_profiles_without_manual_fps_control(self):
        page = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('<select id="fps">', page)
        self.assertIn("const gsapvideo =", page)
        self.assertIn("const musicpro =", page)
        self.assertIn("workflowStepLabel", page)

    def test_precise_profiles_come_from_table(self):
        self.assertIn("kidas", renderer.PRECISE_PROFILES)
        self.assertNotIn("generic", renderer.PRECISE_PROFILES)

    def test_audio_verdict(self):
        from h2m.report import audio_verdict
        self.assertEqual(audio_verdict({"audio_tracks": []})[0], "none")
        self.assertEqual(audio_verdict({"audio_tracks": ["a"], "peak_db": -80})[0], "warn")
        self.assertEqual(audio_verdict({"audio_tracks": ["a"], "peak_db": -12})[0], "ok")


if __name__ == "__main__":
    unittest.main()
