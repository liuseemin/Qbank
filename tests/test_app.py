import io
import json
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from app import create_app


def question(number="1", text="題目", answer="A"):
    return {
        "題別": "單選題",
        "題號": number,
        "題目": text,
        "選項": ["A. 正確", "B. 錯誤"],
        "答案": answer,
        "出處": "測試",
    }


class QBankAppTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "qbank.sqlite3")
        config = {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE_PATH": self.db_path,
            "APP_PASSWORD": "",
        }
        self.app = create_app(config)
        self.client = self.app.test_client()
        self.client.post("/login", data={"password": "", "api_key": ""})

    def tearDown(self):
        self.temp_dir.cleanup()

    def upload_json(self, name, questions):
        payload = io.BytesIO(json.dumps(questions, ensure_ascii=False).encode("utf-8"))
        return self.client.post(
            "/upload",
            data={"question_files": (payload, name)},
            content_type="multipart/form-data",
            follow_redirects=True,
        )

    def bank_ids(self):
        with self.client.session_transaction() as flask_session:
            sid = flask_session["sid"]
        return [bank["id"] for bank in self.app.extensions["qbank_store"].list_banks(sid)]

    def test_health_check_does_not_create_a_browser_session(self):
        response = self.app.test_client().get("/healthz")
        self.assertEqual(response.get_json(), {"status": "ok"})
        self.assertNotIn("Set-Cookie", response.headers)

    def test_upload_multiple_jsons_select_together_and_duplicate_numbers_are_stable(self):
        payload_a = io.BytesIO(json.dumps([question("1", "甲")], ensure_ascii=False).encode())
        payload_b = io.BytesIO(json.dumps([question("1", "乙")], ensure_ascii=False).encode())
        response = self.client.post(
            "/upload",
            data={"question_files": [(payload_a, "甲.json"), (payload_b, "乙.json")]},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        ids = self.bank_ids()
        self.assertEqual(len(ids), 2)

        selected = self.client.post("/select", data={"question_sets": ids})
        self.assertEqual(selected.status_code, 302)
        first = self.client.get("/get_question?mode=order").get_json()
        second = self.client.get("/get_question?mode=order").get_json()
        self.assertNotEqual(first["_key"], second["_key"])
        self.assertEqual({first["題目"], second["題目"]}, {"甲", "乙"})

    def test_uploaded_bank_is_visible_from_an_independent_worker(self):
        self.upload_json("worker.json", [question()])
        bank_id = self.bank_ids()[0]
        self.client.post("/select", data={"question_sets": [bank_id]})

        worker_two = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE_PATH": self.db_path,
                "APP_PASSWORD": "",
            }
        ).test_client()
        cookie = self.client.get_cookie("session")
        worker_two.set_cookie("session", cookie.value)

        data = worker_two.get("/get_question?mode=order").get_json()
        self.assertEqual(data["題目"], "題目")

    def test_zip_upload_embeds_matching_image(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("包/影像題.json", json.dumps([question("7")], ensure_ascii=False))
            zipped.writestr("包/影像題_images/影像題_7.png", b"\x89PNG\r\n\x1a\nimage")
        archive.seek(0)
        response = self.client.post(
            "/upload",
            data={"question_files": (archive, "題庫包.zip")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertIn("影像題", response.get_data(as_text=True))
        bank_id = self.bank_ids()[0]
        self.client.post("/select", data={"question_sets": [bank_id]})
        loaded = self.client.get("/get_question?mode=order").get_json()
        self.assertTrue(loaded["圖片"].startswith("data:image/png;base64,"))

    def test_returning_to_selector_can_switch_bank_and_resets_progress(self):
        self.upload_json("first.json", [question("1", "第一庫")])
        self.upload_json("second.json", [question("1", "第二庫")])
        first_id, second_id = self.bank_ids()
        self.client.post("/select", data={"question_sets": [first_id]})
        current = self.client.get("/get_question?mode=order").get_json()
        self.client.post("/submit_answer", json={"question": current, "answer": "B"})

        self.client.post("/select", data={"question_sets": [second_id]})
        switched = self.client.get("/get_question?mode=order").get_json()
        self.assertEqual(switched["題目"], "第二庫")
        review = self.client.get("/review").get_data(as_text=True)
        self.assertIn("目前沒有錯題", review)

    def test_api_key_is_optional_and_ai_interface_is_not_rendered_without_it(self):
        self.upload_json("plain.json", [question()])
        self.client.post("/select", data={"question_sets": self.bank_ids()})
        html = self.client.get("/").get_data(as_text=True)
        self.assertNotIn('id="ai-explanation"', html)
        self.assertIn('class="main-container no-ai"', html)
        response = self.client.post("/get_ai_explanation", json={"question": question()})
        self.assertEqual(response.status_code, 403)

    def test_api_key_is_server_side_and_enables_ai_interface(self):
        client = self.app.test_client()
        client.post("/login", data={"password": "", "api_key": "private-key"})
        with client.session_transaction() as flask_session:
            sid = flask_session["sid"]
            self.assertNotIn("gemini_api_key", flask_session)
        self.assertEqual(self.app.extensions["qbank_store"].get_api_key(sid), "private-key")
        payload = io.BytesIO(json.dumps([question()], ensure_ascii=False).encode())
        client.post("/upload", data={"question_files": (payload, "ai.json")},
                    content_type="multipart/form-data")
        banks = self.app.extensions["qbank_store"].list_banks(sid)
        client.post("/select", data={"question_sets": [banks[0]["id"]]})
        self.assertIn('id="ai-explanation"', client.get("/").get_data(as_text=True))

    def test_login_stores_provider_model_and_endpoint_server_side(self):
        client = self.app.test_client()
        client.post("/login", data={
            "password": "", "ai_provider": "openai", "api_key": "openai-secret",
            "ai_model": "gpt-test", "ai_base_url": "",
        })
        with client.session_transaction() as flask_session:
            config = self.app.extensions["qbank_store"].get_ai_config(flask_session["sid"])
            self.assertNotIn("api_key", flask_session)
        self.assertEqual(config["provider"], "openai")
        self.assertEqual(config["model"], "gpt-test")
        self.assertEqual(config["api_key"], "openai-secret")

    def test_invalid_json_is_rejected_without_creating_a_bank(self):
        response = self.client.post(
            "/upload",
            data={"question_files": (io.BytesIO(b'{"not": "a list"}'), "bad.json")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertIn("最外層必須是陣列", response.get_data(as_text=True))
        self.assertEqual(self.bank_ids(), [])

    def test_duplicate_bank_name_is_skipped_with_warning(self):
        self.upload_json("duplicate.json", [question("1", "原版")])
        response = self.upload_json("duplicate.json", [question("2", "新版")])
        self.assertEqual(len(self.bank_ids()), 1)
        html = response.get_data(as_text=True)
        self.assertIn("同名題庫已存在", html)
        self.assertIn("duplicate", html)

    def test_bank_list_shows_detected_image_status(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("影像題.json", json.dumps([question("7")], ensure_ascii=False))
            zipped.writestr("影像題_image/影像題_7.png", b"\x89PNG\r\n\x1a\nimage")
        archive.seek(0)
        response = self.client.post(
            "/upload", data={"question_files": (archive, "images.zip")},
            content_type="multipart/form-data", follow_redirects=True,
        )
        html = response.get_data(as_text=True)
        self.assertIn("已偵測 1 張圖檔", html)

    def test_uploaded_bank_can_be_deleted(self):
        self.upload_json("delete-me.json", [question()])
        bank_id = self.bank_ids()[0]
        response = self.client.post(f"/banks/{bank_id}/delete", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.bank_ids(), [])
        self.assertIn("已刪除題庫", response.get_data(as_text=True))

    def test_selector_has_select_all_and_invert_controls(self):
        self.upload_json("controls.json", [question()])
        html = self.client.get("/select").get_data(as_text=True)
        self.assertIn('id="select-all"', html)
        self.assertIn('id="invert-selection"', html)

    def test_unselected_question_cannot_be_submitted(self):
        self.upload_json("only.json", [question()])
        self.client.post("/select", data={"question_sets": self.bank_ids()})
        forged = question("999", "偽造")
        forged["_key"] = "missing:0"
        response = self.client.post("/submit_answer", json={"question": forged, "answer": "A"})
        self.assertEqual(response.status_code, 404)

    def test_wrong_mode_progress_is_counted(self):
        self.upload_json("wrong.json", [question()])
        self.client.post("/select", data={"question_sets": self.bank_ids()})
        current = self.client.get("/get_question?mode=order").get_json()
        self.client.post("/submit_answer", json={"question": current, "answer": "B", "mode": "order"})
        reviewed = self.client.get("/get_question?mode=wrong").get_json()
        result = self.client.post(
            "/submit_answer", json={"question": reviewed, "answer": "A", "mode": "wrong"}
        ).get_json()
        self.assertEqual(result["answered_wrong"], 1)

    def test_zip_path_traversal_is_rejected(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("../escape.json", json.dumps([question()]))
        archive.seek(0)
        response = self.client.post(
            "/upload", data={"question_files": (archive, "unsafe.zip")},
            content_type="multipart/form-data", follow_redirects=True,
        )
        self.assertIn("不安全的檔案路徑", response.get_data(as_text=True))
        self.assertEqual(self.bank_ids(), [])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JavaScript syntax validation")
    def test_rendered_quiz_javascript_has_valid_syntax(self):
        self.upload_json("script.json", [question()])
        self.client.post("/select", data={"question_sets": self.bank_ids()})
        html = self.client.get("/").get_data(as_text=True)
        scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S | re.I)
        script_path = Path(self.temp_dir.name) / "rendered-index.js"
        script_path.write_text("\n".join(scripts), encoding="utf-8")
        result = subprocess.run([shutil.which("node"), "--check", str(script_path)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_search_page_builds_safe_mark_elements(self):
        html = self.client.get("/search").get_data(as_text=True)
        self.assertIn('document.createElement("mark")', html)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JavaScript syntax validation")
    def test_new_page_javascript_has_valid_syntax(self):
        for route in ("/login", "/select", "/search"):
            html = self.client.get(route).get_data(as_text=True)
            scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S | re.I)
            result = subprocess.run(
                [shutil.which("node"), "--check", "-"], input="\n".join(scripts),
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            self.assertEqual(result.returncode, 0, f"{route}: {result.stderr}")


if __name__ == "__main__":
    unittest.main()
