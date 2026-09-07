import json
import tempfile
import unittest
from pathlib import Path

from qbank_loader import load_path


class LocalLoaderTest(unittest.TestCase):
    def test_local_json_uses_sibling_image_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bank = root / "exam.json"
            bank.write_text(json.dumps([{
                "題號": "3", "題目": "圖題", "選項": ["A. 一", "B. 二"], "答案": "A"
            }], ensure_ascii=False), encoding="utf-8")
            image_dir = root / "exam_images"
            image_dir.mkdir()
            (image_dir / "exam_3.png").write_bytes(b"\x89PNG\r\n\x1a\nimage")

            name, questions = load_path(bank)[0]

            self.assertEqual(name, "exam")
            self.assertTrue(questions[0]["圖片"].startswith("data:image/png;base64,"))


if __name__ == "__main__":
    unittest.main()
