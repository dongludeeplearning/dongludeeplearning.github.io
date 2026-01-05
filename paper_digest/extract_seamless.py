import fitz
import sys
import re

def save_crop(page, rect, filename):
    # Add generous padding
    rect.x0 -= 10
    rect.y0 -= 10
    rect.x1 += 10
    rect.y1 += 10
    
    # Clip to page
    rect.intersect(page.rect)
    
    zoom = 3.0
    mat = fitz.Matrix(zoom, zoom)
    try:
        pix = page.get_pixmap(matrix=mat, clip=rect)
        pix.save(filename)
        print(f"Saved {filename}")
    except Exception as e:
        print(f"Error saving {filename}: {e}")

def get_figure_rect(page, caption_pattern, max_height=500):
    blocks = page.get_text("blocks")
    blocks.sort(key=lambda b: (b[1], b[0]))
    
    caption_rect = None
    
    # Find caption
    for b in blocks:
        text = b[4].strip().replace('\n', ' ')
        if re.search(caption_pattern, text, re.IGNORECASE):
            caption_rect = fitz.Rect(b[:4])
            print(f"Found caption: {text[:50]}...")
            break
            
    if not caption_rect:
        print(f"Caption matching '{caption_pattern}' not found.")
        return None

    # Find content above caption
    # Heuristic: Look for images/drawings above the caption
    
    content_rect = None
    
    # Check images
    for img in page.get_images(full=True):
        rects = page.get_image_rects(img[0])
        for r in rects:
            if r.y1 < caption_rect.y0 + 20 and r.y1 > caption_rect.y0 - max_height:
                if content_rect is None:
                    content_rect = r
                else:
                    content_rect |= r

    # Check drawings
    for p in page.get_drawings():
        r = p["rect"]
        if r.y1 < caption_rect.y0 + 20 and r.y1 > caption_rect.y0 - max_height:
             if content_rect is None:
                content_rect = r
             else:
                content_rect |= r
                
    if content_rect:
        # Merge with caption
        final_rect = content_rect | caption_rect
        return final_rect
    else:
        print("No content found above caption.")
        return None

def main():
    pdf_path = "pdfs/2506.22554.pdf"
    doc = fitz.open(pdf_path)
    
    # Figure 1 on Page 6 (index 5)
    print("Extracting Intro Figure (Figure 1)...")
    page_intro = doc[5] 
    rect_intro = get_figure_rect(page_intro, r"^Figure 1")
    if rect_intro:
        save_crop(page_intro, rect_intro, "Figures/seamless_interaction_intro.png")
        
    # Figure 6 on Page 18 (index 17)
    print("Extracting Overview Figure (Figure 6)...")
    page_overview = doc[17]
    rect_overview = get_figure_rect(page_overview, r"^Figure 6")
    if rect_overview:
        save_crop(page_overview, rect_overview, "Figures/seamless_interaction_overview.png")

if __name__ == "__main__":
    main()

