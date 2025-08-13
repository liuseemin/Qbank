import pdfplumber
import json
import argparse
import re
from pathlib import Path

def split_question_and_options(text):
    """
    將題目與選項分開
    回傳: (題目, 選項列表)
    """
    # 將換行統一成 \n
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 尋找第一個選項（A. 或 A．或 A ）的位置
    match = re.search(r"(\n|^)[A-E][\.\．\s]", text)
    if match:
        q_text = text[:match.start()].strip()
        opts_text = text[match.start():].strip()

        # 分割每個選項
        options = re.split(r"(?:\n|^)(?=[A-E][\.\．\s])", opts_text)
        options = [opt.strip() for opt in options if opt.strip()]
        return q_text, options
    else:
        return text.strip(), []

def pdf_table_to_json(pdf_path, json_path, auto_item=False):
    data_list = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue
                for row in table[1:]:
                    if len(row) >= 6:
                        question_text = row[3] or ""
                        options_str = ""
                        if auto_item:
                            # 從題目欄位自動拆選項
                            q_text, extracted_options = split_question_and_options(question_text)
                            # 如果選項欄位空，就用拆出來的
                            if not options_str.strip() and extracted_options:
                                options_str = extracted_options
                            question_text = q_text

                        row_dict = {
                            "題別": row[1] or "",
                            "題號": row[2] or "",
                            "題目": question_text,
                            "選項": options_str if auto_item else "",
                            "答案": row[4] or "",
                            "出處": row[5] or ""
                        }
                        data_list.append(row_dict)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data_list, f, ensure_ascii=False, indent=4)

    print(f"✅ {pdf_path} → {json_path}")

def process_single_file(pdf_path, output_path, auto_item):
    if output_path.suffix.lower() != ".json":
        output_path = output_path.with_suffix(".json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_table_to_json(pdf_path, output_path, auto_item)

def process_folder(folder_path, output_dir, auto_item):
    pdf_files = list(folder_path.glob("*.pdf"))
    if not pdf_files:
        print(f"⚠ 找不到任何 PDF 檔案於 {folder_path}")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    for pdf_file in pdf_files:
        json_path = output_dir / (pdf_file.stem + ".json")
        pdf_table_to_json(pdf_file, json_path, auto_item)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="將 PDF 表格轉成 JSON 題庫格式")
    parser.add_argument("pdf", help="PDF 檔案或資料夾路徑")
    parser.add_argument("-o", "--output", help="輸出 JSON 檔案路徑或資料夾")
    parser.add_argument("--autoitem", action="store_true", help="自動從題目欄位分離選項")

    args = parser.parse_args()

    input_path = Path(args.pdf)
    if not input_path.exists():
        print(f"❌ 找不到檔案或資料夾：{input_path}")
        exit(1)

    if input_path.is_file():
        if args.output:
            output_path = Path(args.output)
        else:
            output_path = input_path.with_suffix(".json")
        process_single_file(input_path, output_path, args.autoitem)

    elif input_path.is_dir():
        if args.output:
            output_dir = Path(args.output)
        else:
            output_dir = input_path
        process_folder(input_path, output_dir, args.autoitem)