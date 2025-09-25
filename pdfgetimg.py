import fitz  # PyMuPDF
import os

# 載入 PDF
pdf_path = r"C:\Users\Liu\OneDrive\文件\114年外專筆試題庫\小兒外科_單.pdf"
doc = fitz.open(pdf_path)

# 輸出資料夾
output_dir = "extracted_images"
os.makedirs(output_dir, exist_ok=True)

img_count = 0

for page_index in range(len(doc)):
    page = doc[page_index]
    # 抓出該頁的所有圖片
    images = page.get_images(full=True)
    for img_index, img in enumerate(images):
        xref = img[0]  # 圖片的 xref 編號
        base_image = doc.extract_image(xref)
        image_bytes = base_image["image"]
        image_ext = base_image["ext"]  # 例如 "png" 或 "jpg"

        img_count += 1
        image_filename = os.path.join(output_dir, f"page{page_index+1}_img{img_index+1}.{image_ext}")
        with open(image_filename, "wb") as f:
            f.write(image_bytes)

print(f"✅ 總共擷取 {img_count} 張圖片，已存放在資料夾: {output_dir}")