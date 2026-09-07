"""Local Qbank launcher.

This is intentionally a thin wrapper around app.create_app so local development and
Render run exactly the same application and storage model.
"""
import argparse
import hashlib
import os
import sys
import webbrowser
from pathlib import Path

from InquirerPy import inquirer

from app import create_app
from qbank_loader import BankValidationError, load_path


def discover_files(sources):
    files = []
    for source in sources:
        path = Path(source).expanduser().resolve()
        if not path.exists():
            print(f"❌ 找不到路徑：{path}")
        elif path.is_dir():
            files.extend(sorted((*path.glob("*.json"), *path.glob("*.zip")), key=lambda item: item.name.casefold()))
        elif path.suffix.lower() in (".json", ".zip"):
            files.append(path)
        else:
            print(f"⚠️ 不支援的檔案：{path}")
    return list(dict.fromkeys(files))


def choose_files(files):
    if len(files) <= 1 or not sys.stdin.isatty():
        return files
    return inquirer.checkbox(
        message="請選擇要載入的題庫（可複選）",
        choices=[{"name": path.name, "value": path} for path in files],
        instruction="[Space 選擇] [Enter 完成] [Ctrl+A 全選]",
        keybindings={"toggle-all": [{"key": "c-a"}]},
    ).execute()


def import_public_banks(app, files):
    store = app.extensions["qbank_store"]
    imported = 0
    for path in files:
        try:
            for name, questions in load_path(path):
                digest = hashlib.sha256(str(path).encode("utf-8") + path.read_bytes()).hexdigest()[:32]
                bank_id = hashlib.sha256(f"{digest}:{name}".encode()).hexdigest()[:32]
                store.create_bank("public", name, questions, bank_id=bank_id)
                imported += 1
                print(f"✅ 載入題庫：{name}（{len(questions)} 題）")
        except (OSError, BankValidationError) as error:
            print(f"❌ 無法載入 {path.name}：{error}")
    return imported


def main(argv=None):
    parser = argparse.ArgumentParser(description="Qbank 本機出題機（與 Render 共用相同核心）")
    parser.add_argument("json_files", nargs="*", help="一個或多個 JSON/ZIP 檔案或資料夾")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=int(os.environ.get("PORT", "5000")), type=int)
    parser.add_argument("--open", "-o", action="store_true", help="自動開啟瀏覽器")
    parser.add_argument("--database", default=os.environ.get("DATABASE_PATH"), help="SQLite 資料庫路徑")
    args = parser.parse_args(argv)

    config = {"DATABASE_PATH": args.database} if args.database else {}
    app = create_app(config)
    files = choose_files(discover_files(args.json_files))
    if files and not import_public_banks(app, files):
        return 2
    if not files:
        print("ℹ️ 未預載題庫；請在瀏覽器的題庫選單上傳 JSON 或 ZIP。")
    url = f"http://{args.host}:{args.port}"
    if args.open:
        webbrowser.open(url)
    print(f"🌏 Qbank：{url}")
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
