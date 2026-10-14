import base64
import importlib.util
import tempfile
import unittest
from pathlib import Path

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

    def test_music_volume_is_read_from_page(self):
        with tempfile.TemporaryDirectory() as d:
            text = "AUD='data:audio/mpeg;base64,QUJD',MUS='data:audio/mpeg;base64,QUJD';mu.current.volume=.22"
            self.assertAlmostEqual(renderer.extract_audio(text, Path(d), "kidas")["music_volume"], 0.22)


if __name__ == "__main__":
    unittest.main()