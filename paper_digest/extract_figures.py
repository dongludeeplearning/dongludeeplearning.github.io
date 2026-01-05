import fitz  # PyMuPDF
import sys
import os
import re
import urllib.request
import ssl

def download_pdf(url, save_dir="pdfs"):
    if "arxiv.org/abs/" in url:
        pdf_url = url.replace("/abs/", "/pdf/")
        if not pdf_url.endswith(".pdf"): pdf_url += ".pdf"
    elif "arxiv.org/pdf/" in url:
        pdf_url = url
        if not pdf_url.endswith(".pdf"): pdf_url += ".pdf"
    else:
        pdf_url = url

    filename = pdf_url.split("/")[-1].split("?")[0]
    if not filename.endswith(".pdf"): filename += ".pdf"

    if not os.path.exists(save_dir): os.makedirs(save_dir)
    save_path = os.path.join(save_dir, filename)

    if os.path.exists(save_path):
        print(f"PDF already exists at: {save_path}")
        return save_path

    print(f"Downloading PDF from {pdf_url}...")
    try:
        context = ssl._create_unverified_context()
        req = urllib.request.Request(
            pdf_url, 
            data=None, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, context=context) as response, open(save_path, 'wb') as out_file:
            out_file.write(response.read())
        print(f"Saved PDF to: {save_path}")
        return save_path
    except Exception as e:
        print(f"Error downloading PDF: {e}")
        return None

def get_caption_rects(page):
    """
    Finds "Figure X" captions and merges subsequent text blocks that are likely part of the caption.
    Returns list of (rect, full_text, fig_number).
    """
    blocks = page.get_text("blocks")
    # Sort blocks by Y (top to bottom), then X (left to right)
    blocks.sort(key=lambda b: (b[1], b[0]))
    
    captions = []
    # Pattern: Starts with "Fig" or "Figure", followed by number
    pattern = re.compile(r"^Fig(ure|\.)?\s*(\d+)", re.IGNORECASE)
    
    used_indices = set()
    
    for i, b in enumerate(blocks):
        if i in used_indices: continue
        
        text = b[4].strip()
        clean_text = text.replace('\n', ' ')
        match = pattern.search(clean_text)
        
        if match:
            try:
                fig_num = int(match.group(2))
                current_rect = fitz.Rect(b[:4])
                full_text = text
                used_indices.add(i)
                
                # Look ahead for continuations (merged caption blocks)
                # Heuristic: same alignment, small vertical gap, no new "Figure" start
                for j in range(i + 1, len(blocks)):
                    if j in used_indices: continue
                    next_b = blocks[j]
                    next_rect = fitz.Rect(next_b[:4])
                    
                    # Stop if next block looks like a new figure caption OR a section header
                    text_content = next_b[4].strip().replace('\n', ' ')
                    if pattern.search(text_content):
                        break
                    
                    # Heuristic for section header: Starts with number and dot, e.g. "3. Method"
                    if re.match(r"^\d+\.\s+[A-Z]", text_content):
                        break
                        
                    vertical_gap = next_rect.y0 - current_rect.y1
                    
                    # Heuristic for merging:
                    # 1. Close vertically (< 20 pts)
                    # 2. Horizontal overlap or alignment
                    # 3. Font size similarity (hard to check with just blocks, but usually consistent in blocks)
                    
                    # Simple check: vertical proximity
                    if 0 <= vertical_gap < 35: 
                        # Merge this block
                        current_rect |= next_rect
                        full_text += " " + next_b[4].strip()
                        used_indices.add(j)
                    else:
                        # Break if gap is too large (likely next section or unrelated text)
                        break
                
                captions.append((current_rect, full_text, fig_num))
            except:
                pass
    return captions

def get_figure_content_rect(page, caption_rect, all_captions=None):
    """
    Calculates the bounding box of visual elements (images + vector drawings)
    that belong to the given caption.
    """
    # 1. Collect all visual candidates
    visual_rects = []
    
    # Raster Images
    for img in page.get_images(full=True):
        rects = page.get_image_rects(img[0])
        for r in rects:
            visual_rects.append(r)
            
    # Vector Drawings (paths)
    paths = page.get_drawings()
    for p in paths:
        visual_rects.append(p["rect"])
        
    # 2. Filter candidates
    candidates = []
    cap_y0 = caption_rect.y0
    
    # Define Ceiling (Text blocks above)
    text_blocks = page.get_text("blocks")
    ceiling_y = 0
    
    page_width = page.rect.width
    
    # NEW: Treat other captions as ceilings!
    if all_captions:
        for other_rect, _, _ in all_captions:
            # If other caption is strictly above current caption
            if other_rect.y1 < cap_y0:
                # Update ceiling to the bottom of the other caption
                # But wait, the figure for the other caption is ABOVE it?
                # Usually: [Figure 2 Image] -> [Figure 2 Caption] -> [Figure 3 Image] -> [Figure 3 Caption]
                # So for Figure 3, the ceiling should be Figure 2 Caption bottom.
                if other_rect.y1 > ceiling_y:
                    ceiling_y = max(ceiling_y, other_rect.y1)

    for b in text_blocks:
        b_rect = fitz.Rect(b[:4])
        
        # Determine if this block is "Body Text" that should act as a ceiling
        # 1. Must be above caption
        # 2. Any text block above the caption can potentially be a ceiling if it's not part of the figure.
        # We assume standard text blocks (not labels inside figure) are wide enough or substantial enough.
        
        if b_rect.y1 < cap_y0:
            text_content = b[4].lower()
            is_header = "abstract" in text_content or "introduction" in text_content
            # Reverting to a safer threshold to avoid cropping figure labels
            is_substantial = len(text_content) > 60 
            
            # Reverting width check to be more conservative
            is_wide_enough = b_rect.width > (page_width * 0.25)
            
            if (is_header or (is_substantial and is_wide_enough)):
                # If this block overlaps horizontally with caption, it's definitely a ceiling
                # Or if it's a full-width block (like Title), it's a ceiling for everyone.
                
                # Check intersection logic
                # For safety, if it's a "substantial" block above, treat it as a potential ceiling.
                # We take the lowest such block as the active ceiling.
                if b_rect.y1 > ceiling_y:
                    ceiling_y = max(ceiling_y, b_rect.y1)
    
    # 2.5 SPECIAL CASE: If ceiling is 0 (no text above), and we are deep in the page,
    # it might mean the figure starts lower down.
    # However, for "too long" issues, it usually means we grabbed space above the figure up to the top of page.
    # Let's enforce a max height heuristic relative to width if ceiling is not well defined.
    # Or, check if there's a huge gap.

    # 3. Gather rects between Ceiling and Caption
    final_rect = None
    
    # Analyze Caption Position
    # Left column: x < page_width/3
    # Right column: x > 2*page_width/3
    # Centered/Full: overlaps center
    
    cap_center_x = (caption_rect.x0 + caption_rect.x1) / 2
    is_left = cap_center_x < page_width * 0.35
    is_right = cap_center_x > page_width * 0.65
    # otherwise centered/spanning
    
    for r in visual_rects:
        # Vertical check: Strictly between ceiling and caption (with small buffers)
        # Allow r.y1 to slightly dip into caption space (e.g. descenders or tight fit) -> +10
        # Allow r.y0 to be slightly above ceiling? No, ceiling is hard stop usually. -> -5 buffer
        
        # Hard constraint: visual element cannot be too far above caption (max 450pts)
        if r.y0 < cap_y0 - 450:
            continue

        if r.y1 <= cap_y0 + 15 and r.y0 >= ceiling_y - 5:
             
             # Horizontal check logic
             # If caption is clearly in a column, enforce column constraint.
             # If caption is centered/wide, allow broader inclusion.
             
             should_include = False
             
             if is_left:
                 # Check if rect is also in left half
                 if r.x0 < page_width * 0.55: should_include = True
             elif is_right:
                 # Check if rect is also in right half
                 if r.x1 > page_width * 0.45: should_include = True
             else:
                 # Centered/Wide caption: Include almost anything in this vertical band
                 # But verify some overlap to avoid picking up unrelated marginalia?
                 # If caption is wide, just take it.
                 # If caption is narrow but centered (rare for wide figures), 
                 # we still want to capture wide figures.
                 should_include = True
                 
             if should_include:
                 if final_rect is None:
                     final_rect = r
                 else:
                     final_rect |= r

    # Post-processing: If final_rect is too tall, clamp it?
    # "Overview too long" implies we captured too much vertical space.
    if final_rect is not None:
        height = final_rect.height
        # If height is > 400 (approx half page), clamp it.
        if height > 400:
             # Clamp top to max 400pts above caption
             new_y0 = max(final_rect.y0, cap_y0 - 400)
             final_rect.y0 = new_y0

    # If nothing found, fallback
    if final_rect is None:
        # Relaxed fallback slightly but kept it reasonable
        # Update: use a tighter fallback if user complains about "too long"
        fallback_height = 300 # Limit fallback to 300px height?
        fallback_top = max(ceiling_y, cap_y0 - fallback_height)
        final_rect = fitz.Rect(caption_rect.x0, fallback_top, caption_rect.x1, cap_y0)
    
    # Force max height heuristic: 
    # If the detected height is > 1.5 * page_width (unlikely for a figure), clamp it.
    # Or more simply, if the rect starts way above likely figure top.
    
    # Safety clamp: Don't let the rect go above the ceiling
    if final_rect.y0 < ceiling_y:
        final_rect.y0 = ceiling_y

    return final_rect

def save_crop(page, rect, filename):
    # Add generous padding to avoid cuts
    rect.x0 -= 10
    rect.y0 -= 5
    rect.x1 += 10
    # Reduced bottom padding to avoid including next section header
    rect.y1 += 2
    
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

def process_paper(pdf_path, paper_id):
    if not os.path.exists("Figures"): os.makedirs("Figures")
    doc = fitz.open(pdf_path)
    print(f"Processing {pdf_path}...")

    # 1. Search for Figure 1 (Intro) on Page 1-2
    intro_done = False
    for i in range(min(2, len(doc))):
        page = doc[i]
        captions = get_caption_rects(page)
        
        # Look for Fig 1
        for cap_rect, text, num in captions:
            if num == 1:
                print(f"  [Intro] Found Figure 1 caption on Page {i+1}")
                content_rect = get_figure_content_rect(page, cap_rect, captions)
                # Union content + caption
                full_rect = content_rect | cap_rect
                save_crop(page, full_rect, f"Figures/{paper_id}_intro.png")
                intro_done = True
                break
        if intro_done: break

    # 2. Search for Overview (Keywords)
    overview_done = False
    primary_keywords = ["overview"]
    secondary_keywords = ["architecture", "pipeline", "framework", "method", "model"]
    
    candidates = []

    for i in range(min(10, len(doc))): 
        page = doc[i]
        captions = get_caption_rects(page)
        
        for cap_rect, text, num in captions:
            # Skip if it's Figure 1 and we already used it
            if num == 1 and intro_done: continue
            
            text_lower = text.lower()
            score = 0
            
            if "overview" in text_lower:
                score += 100
            elif any(k in text_lower for k in secondary_keywords):
                score += 50
                
            content_rect = get_figure_content_rect(page, cap_rect, captions)
            area = content_rect.width * content_rect.height
            
            score += (area / 10000) 
            
            if score > 20: 
                full_rect = content_rect | cap_rect
                candidates.append((score, page, full_rect, num))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_page, best_rect, best_num = candidates[0]
        print(f"  [Overview] Selected Figure {best_num} (Score: {int(best_score)}) on Page {best_page.number+1}")
        save_crop(best_page, best_rect, f"Figures/{paper_id}_overview.png")
        overview_done = True
    
    if not overview_done:
        print("  [Overview] No keyword match found. Try manual selection.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python extract_figures.py <url_or_path> <paper_id>")
        sys.exit(1)
        
    inp = sys.argv[1]
    pid = sys.argv[2]
    
    pdf_path = None
    
    if inp.lower().startswith("http"):
        pdf_path = download_pdf(inp)
    else:
        pdf_path = inp
        
    if pdf_path and os.path.exists(pdf_path):
        process_paper(pdf_path, pid)
        print(f"Processed successfully. PDF kept at: {pdf_path}")
    else:
        print("Error: PDF path invalid or processing failed.")