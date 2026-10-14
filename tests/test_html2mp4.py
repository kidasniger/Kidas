import importlib.util
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


if __name__ == "__main__":
    unittest.main()