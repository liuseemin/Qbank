import pdfplumber
import fitz  # PyMuPDF
from pathlib import Path

def process_pdf_for_images(pdf_path):
    """
    處理 PDF 並將偵測到的圖片儲存為 [原檔名_題號].png
    """
    pdf_path = Path(pdf_path)
    # use pdf_path to make a new folder with suffix "_images" in pdf_path parent folder
    
    print(f"開始處理 {pdf_path.name}...")

    with pdfplumber.open(pdf_path) as pdf:
        doc = fitz.open(pdf_path)

        # 逐頁處理
        for page_idx, page in enumerate(pdf.pages):
            print(f"  > 處理第 {page_idx + 1} 頁...")
            
            # 從 pdfplumber 取得頁面上的所有表格
            tables = page.find_tables()

            # 從 PyMuPDF 取得頁面上的所有圖片資訊
            fitz_page = doc.load_page(page_idx)

            infos = fitz_page.get_image_info()
            print(f"    - 頁面上共有 {len(infos)} 個物件。")
            
            # 遍歷頁面上的每一個物件
            for img_idx in range(len(fitz_page.get_images(full=True))):
                img_info = fitz_page.get_images(full=True)[img_idx]
                xref = img_info[img_idx]
                # print out every image info
                print(f"    - 發現圖片 xref: {xref}, 其他資訊: {img_info[1:]}")
                bbox_info = fitz_page.get_image_info()[img_idx]
                print(f"      * 物件 xref: {xref}, 邊界: {bbox_info['bbox']}")
                print(f"    - 物件邊界: {bbox_info}")
                img_bbox = bbox_info['bbox']
                
                # 遍歷表格，尋找圖片所屬的題號
                found_match = False
                for table in tables:
                    # 跳過表頭，從第二行開始
                    for r in range(1, len(table.rows)):
                        # 確保題號欄位 (row[2]) 存在且有內容
                        # row[2] 是題號欄位
                        # row[3] 是題目欄位
                        # 確保列數足夠，且題目與答案欄位有內容
                        if len(table.rows[r].cells) < 6 or not table.rows[r].cells[2] or not table.rows[r].cells[3]:
                            continue
                            
                        # 取得該題目的邊界
                        # 使用 pdfplumber 的 cell 邊界作為題目的範圍
                        # 這裡要小心索引，因為 row_idx 是從 0 開始
                        
                        question_cell = table.rows[r].cells[3]  # 題號欄位
                        question_id = table.extract()[r][2].strip()
                        if not question_cell:
                            continue

                        print(f"    - 題號: {question_id}, 題目邊界: {question_cell}")
                        
                        # 判斷圖片是否在該題目的邊界範圍內
                        # 使用圖片的垂直中心點來判斷，更準確
                        question_bbox = question_cell
                        img_center_y = (img_bbox[1] + img_bbox[3]) / 2
                        
                        if img_center_y >= question_bbox[1] and img_center_y <= question_bbox[3]:
                            # 找到配對，嘗試儲存圖片
                            try:
                                pix = fitz.Pixmap(doc, xref)
                                
                                output_folder = pdf_path.parent / (pdf_path.stem + "_images")
                                Path(output_folder).mkdir(exist_ok=True)
                                output_path = Path(output_folder) / f"{pdf_path.stem}_{question_id}.png"
                                
                                if output_path.exists():
                                    print(f"    - 檔案已存在，跳過：{output_path.name}")
                                else:
                                    pix.save(str(output_path))
                                    print(f"    - 成功儲存圖片：{output_path.name}")
                                found_match = True
                                break # 找到對應的題目後就跳出，處理下一張圖片
                            except Exception as e:
                                print(f"    - 儲存圖片 {xref} 失敗: {e}")
                    if found_match:
                        break # 如果找到配對，就跳出表格迴圈
            
        doc.close()
    
    print("處理完成。")


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