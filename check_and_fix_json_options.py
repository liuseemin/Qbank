import json
import argparse
from pathlib import Path

FULL_TO_HALF = str.maketrans("ＡＢＣＤＥ", "ABCDE")

def normalize_options(options):
    return [opt.translate(FULL_TO_HALF) for opt in options]

def check_and_fix_json(json_path, output_dir):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for item in data:

        # 檢查選項是否有全形英文字母
        fullwidth_opts = [opt for opt in item.get("選項", []) if any(c in opt for c in "ＡＢＣＤＥ")]
        if fullwidth_opts:
            print(f"🔍 {json_path}: 題號 {item.get('題號', '')} 選項含全形字母: {fullwidth_opts}")

        # 檢查答案是否有全形英文字母
        if any(c in item.get("答案", "") for c in "ＡＢＣＤＥ"):
            print(f"🔍 {json_path}: 題號 {item.get('題號', '')} 答案含全形字母: {item.get('答案', '')}")
        
        # Normalize options
        # check if "ＡＢＣＤＥ" excists in file
        item["選項"] = normalize_options(item.get("選項", []))
        # als normalize answer
        item["答案"] = item.get("答案", "").translate(FULL_TO_HALF)
        # print(f"✅ {json_path}: 題號 {item.get('題號', '')} 選項已標準化")
        # Ensure 5 options
        if len(item["選項"]) != 5:
            print(f"⚠️ {json_path}: 題號 {item.get('題號', '')} 選項數量為 {len(item['選項'])}")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / json_path.name
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"📝 已輸出到 {output_path}")

def process_folder(folder_path, output_dir):
    for json_file in Path(folder_path).glob("*.json"):
        check_and_fix_json(json_file, output_dir)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="檢查並修正 JSON 題庫選項格式")
    parser.add_argument("path", help="JSON 檔案或資料夾路徑")
    parser.add_argument("-o", "--output", help="輸出資料夾", default="fixed_json")
    args = parser.parse_args()

    input_path = Path(args.path)
    output_dir = Path(args.output)
    if input_path.is_file() and input_path.suffix.lower() == ".json":
        check_and_fix_json(input_path, output_dir)
    elif input_path.is_dir():
        process_folder(input_path, output_dir)
    else:
        print(f"❌ 找不到檔案或資料夾：{input_path}")