import fitz
import sys

def extract_text(pdf_path, start_page=0, num_pages=None):
    doc = fitz.open(pdf_path)
    text = ""
    end_page = len(doc)
    if num_pages:
        end_page = min(start_page + int(num_pages), len(doc))
    
    for i in range(start_page, end_page):
        text += f"--- Page {i+1} ---\n"
        text += doc[i].get_text()
    return text

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python read_pdf_text.py <pdf_path> [start_page] [num_pages]")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    start_page = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    num_pages = int(sys.argv[3]) if len(sys.argv) > 3 else None
    
    print(extract_text(pdf_path, start_page, num_pages))
