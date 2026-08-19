import pdfplumber
import fitz  # PyMuPDF
from pathlib import Path
from tqdm import tqdm


def process_pdf_for_images(pdf_path):
    """處理 PDF 並將偵測到的圖片儲存為 [原檔名_題號].png。"""
    pdf_path = Path(pdf_path)

    with pdfplumber.open(pdf_path) as pdf:
        doc = fitz.open(pdf_path)
        try:
            for page_idx, page in tqdm(
                enumerate(pdf.pages),
                total=len(pdf.pages),
                desc=pdf_path.name,
                unit="頁",
            ):
                tables = page.find_tables()
                fitz_page = doc.load_page(page_idx)

                for img_idx in range(len(fitz_page.get_images(full=True))):
                    img_info = fitz_page.get_images(full=True)[img_idx]
                    xref = img_info[img_idx]
                    bbox_info = fitz_page.get_image_info()[img_idx]
                    img_bbox = bbox_info["bbox"]
                    found_match = False

                    for table in tables:
                        for row_index in range(1, len(table.rows)):
                            row = table.rows[row_index]
                            if (
                                len(row.cells) < 6
                                or not row.cells[2]
                                or not row.cells[3]
                            ):
                                continue

                            question_cell = row.cells[3]
                            question_id = table.extract()[row_index][2].strip()
                            if not question_cell:
                                continue

                            img_center_y = (img_bbox[1] + img_bbox[3]) / 2
                            if question_cell[1] <= img_center_y <= question_cell[3]:
                                try:
                                    output_folder = pdf_path.parent / (
                                        pdf_path.stem + "_images"
                                    )
                                    output_folder.mkdir(exist_ok=True)
                                    output_path = output_folder / (
                                        f"{pdf_path.stem}_{question_id}.png"
                                    )
                                    if not output_path.exists():
                                        fitz.Pixmap(doc, xref).save(str(output_path))
                                    found_match = True
                                    break
                                except Exception:
                                    pass
                        if found_match:
                            break
        finally:
            doc.close()


# 範例使用
if __name__ == "__main__":
    import argparse

    # 處理整個資料夾檔案
    parser = argparse.ArgumentParser(description="從 PDF 中擷取圖片並依題號命名")
    parser.add_argument("pdf_file_path", type=str, help="PDF 檔案路徑")
    args = parser.parse_args()
    pdf_file_path = args.pdf_file_path

    # 處理整個資料夾
    if Path(pdf_file_path).is_dir():
        for pdf_file in Path(pdf_file_path).glob("*.pdf"):
            process_pdf_for_images(pdf_file)
    # 處理單一檔案
    elif Path(pdf_file_path).is_file():
        process_pdf_for_images(pdf_file_path)
    else:
        print(f"錯誤：找不到檔案 {pdf_file_path}。請確保檔案已上傳且路徑正確。")
