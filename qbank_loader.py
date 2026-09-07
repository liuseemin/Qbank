import base64
import io
import json
import mimetypes
import posixpath
import zipfile
from pathlib import Path, PurePosixPath


class BankValidationError(ValueError):
    pass


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def validate_questions(data, source_name):
    if not isinstance(data, list):
        raise BankValidationError(f"{source_name}：JSON 最外層必須是陣列")
    if not data:
        raise BankValidationError(f"{source_name}：題庫不可為空")
    cleaned = []
    for index, raw in enumerate(data, 1):
        if not isinstance(raw, dict):
            raise BankValidationError(f"{source_name}：第 {index} 題必須是物件")
        missing = [field for field in ("題號", "題目", "選項", "答案") if field not in raw]
        if missing:
            raise BankValidationError(f"{source_name}：第 {index} 題缺少 {', '.join(missing)}")
        if not isinstance(raw["選項"], list) or not raw["選項"]:
            raise BankValidationError(f"{source_name}：第 {index} 題的選項必須是非空陣列")
        item = dict(raw)
        item["題號"] = str(item["題號"]).strip()
        item["題目"] = str(item["題目"]).replace("\r\n", " ").replace("\n", " ").strip()
        item["選項"] = [str(option).replace("\r\n", " ").replace("\n", " ").strip() for option in item["選項"]]
        item["答案"] = str(item["答案"]).strip().upper()
        if not item["題號"] or not item["題目"] or not item["答案"]:
            raise BankValidationError(f"{source_name}：第 {index} 題含有空白的必要欄位")
        cleaned.append(item)
    return cleaned


def load_json_bytes(content, filename):
    try:
        data = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BankValidationError(f"{filename}：無法解析 JSON（{error}）") from error
    return Path(filename).stem, validate_questions(data, filename)


def _safe_zip_entries(archive, max_uncompressed_bytes):
    entries, total = {}, 0
    for info in archive.infolist():
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if info.is_dir():
            continue
        if path.is_absolute() or ".." in path.parts:
            raise BankValidationError("ZIP 包含不安全的檔案路徑")
        total += info.file_size
        if total > max_uncompressed_bytes:
            raise BankValidationError("ZIP 解壓縮後超過容量限制")
        entries[path.as_posix()] = archive.read(info)
    return entries


def _attach_zip_images(questions, json_path, entries):
    json_dir = posixpath.dirname(json_path)
    stem = PurePosixPath(json_path).stem
    for question in questions:
        candidates = []
        image_value = question.get("圖片")
        if isinstance(image_value, str) and image_value and not image_value.startswith("data:"):
            candidates.append(posixpath.normpath(posixpath.join(json_dir, image_value)))
        number = str(question["題號"])
        for extension in IMAGE_EXTENSIONS:
            for suffix in ("_image", "_images"):
                candidates.extend([
                    posixpath.join(json_dir, f"{stem}{suffix}", f"{stem}_{number}{extension}"),
                    posixpath.join(json_dir, f"{stem}{suffix}", f"{number}{extension}"),
                ])
        match = next((candidate for candidate in candidates if candidate in entries), None)
        if match:
            mime = mimetypes.guess_type(match)[0] or "application/octet-stream"
            question["圖片"] = f"data:{mime};base64,{base64.b64encode(entries[match]).decode('ascii')}"


def load_zip_bytes(content, filename, max_uncompressed_bytes=100 * 1024 * 1024):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = _safe_zip_entries(archive, max_uncompressed_bytes)
    except (zipfile.BadZipFile, RuntimeError) as error:
        raise BankValidationError(f"{filename}：不是有效的 ZIP 檔案") from error
    json_names = sorted(name for name in entries if name.lower().endswith(".json"))
    if not json_names:
        raise BankValidationError(f"{filename}：ZIP 中找不到 JSON 題庫")
    banks = []
    for json_name in json_names:
        name, questions = load_json_bytes(entries[json_name], json_name)
        _attach_zip_images(questions, json_name, entries)
        banks.append((name, questions))
    return banks


def load_uploaded_file(upload, max_uncompressed_bytes=100 * 1024 * 1024):
    filename = Path(upload.filename or "").name
    content = upload.read()
    if not filename or not content:
        raise BankValidationError("上傳檔案不可為空")
    suffix = Path(filename).suffix.lower()
    if suffix == ".json":
        return [load_json_bytes(content, filename)]
    if suffix == ".zip":
        return load_zip_bytes(content, filename, max_uncompressed_bytes)
    raise BankValidationError(f"{filename}：只支援 .json 或 .zip")


def load_path(path):
    path = Path(path)
    if path.suffix.lower() == ".json":
        name, questions = load_json_bytes(path.read_bytes(), path.name)
        image_dirs = [path.with_name(f"{path.stem}{suffix}")
                      for suffix in ("_image", "_images")]
        for image_dir in (directory for directory in image_dirs if directory.is_dir()):
            for question in questions:
                if str(question.get("圖片", "")).startswith("data:"):
                    continue
                number = str(question["題號"])
                candidates = []
                for extension in IMAGE_EXTENSIONS:
                    candidates.extend((image_dir / f"{path.stem}_{number}{extension}",
                                       image_dir / f"{number}{extension}"))
                match = next((candidate for candidate in candidates if candidate.is_file()), None)
                if match:
                    mime = mimetypes.guess_type(match.name)[0] or "application/octet-stream"
                    question["圖片"] = f"data:{mime};base64,{base64.b64encode(match.read_bytes()).decode('ascii')}"
        return [(name, questions)]
    if path.suffix.lower() == ".zip":
        return load_zip_bytes(path.read_bytes(), path.name)
    raise BankValidationError(f"{path.name}：只支援 .json 或 .zip")
