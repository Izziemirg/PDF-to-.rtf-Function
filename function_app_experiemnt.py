from datetime import datetime
import re
import fitz  # PyMuPDF
from docx import Document
import os
def detect_footnote_boundary(page):
    """
    Determine where footnotes begin on the page using multiple heuristics.
    Returns the y-coordinate of the detected boundary.
    """
    # Start with a conservative default (60% down the page)
    default_threshold = page.rect.height * 0.6
    
    # Look for horizontal lines that might separate content from footnotes
    horizontal_lines = []
    for drawing in page.get_drawings():
        if drawing["type"] == "l":  # Line
            y1, y2 = drawing["rect"][1], drawing["rect"][3]
            # Check if it's a horizontal line (y coordinates are similar)
            if abs(y1 - y2) < 2 and abs(drawing["rect"][0] - drawing["rect"][2]) > page.rect.width * 0.3:
                horizontal_lines.append((min(y1, y2), max(drawing["rect"][0], drawing["rect"][2]) - min(drawing["rect"][0], drawing["rect"][2])))
    
    if horizontal_lines:
        # Use the lowest horizontal line in the middle 60% of the page as separator
        separator_lines = [line for line in horizontal_lines 
                          if line[0] < page.rect.height * 0.8 
                          and line[0] > page.rect.height * 0.2]
        if separator_lines:
            # Find the longest separator line in the bottom half
            bottom_half_lines = [line for line in separator_lines if line[0] > page.rect.height * 0.5]
            if bottom_half_lines:
                longest_line = max(bottom_half_lines, key=lambda x: x[1])
                return longest_line[0]
            
            # If no lines in bottom half, get the lowest line
            lowest_line = max(separator_lines, key=lambda x: x[0])
            return lowest_line[0]
    
    # Look for footnote number patterns
    dict_format = page.get_text("dict")
    footnote_candidates = []
    
    for block in dict_format["blocks"]:
        if block["type"] == 0:  # Text block
            for line in block["lines"]:
                line_text = "".join(span["text"] for span in line["spans"])
                # Look for patterns like "1." or "1 " at beginning of line
                if re.match(r'^\s*\d+[\.\s]', line_text):
                    # This might be a footnote start
                    y_pos = line["bbox"][1]
                    if y_pos > page.rect.height * 0.4:  # Only consider if in bottom 60%
                        footnote_candidates.append(y_pos)
    
    if footnote_candidates:
        # Find the earliest (highest) potential footnote start
        earliest_footnote = min(footnote_candidates)
        return max(page.rect.height * 0.4, earliest_footnote - 5)  # Small margin above
    
    # Check for font size changes in the bottom half
    font_sizes = {}
    for block in dict_format["blocks"]:
        if block["type"] == 0:
            for line in block["lines"]:
                y_pos = line["bbox"][1]
                for span in line["spans"]:
                    size = span["size"]
                    if size not in font_sizes:
                        font_sizes[size] = []
                    font_sizes[size].append(y_pos)
    
    # If we have at least 2 font sizes, look for smaller fonts in bottom half
    if len(font_sizes) >= 2:
        avg_positions = {size: sum(positions)/len(positions) for size, positions in font_sizes.items()}
        sizes_by_pos = sorted([(pos, size) for size, pos in avg_positions.items()])
        
        # If smallest font has average position in bottom half
        if sizes_by_pos and sizes_by_pos[0][0] > page.rect.height * 0.5:
            smallest_font_positions = font_sizes[sizes_by_pos[0][1]]
            if smallest_font_positions:
                # Get the topmost position of the smallest font
                return max(page.rect.height * 0.4, min(smallest_font_positions) - 5)
    
    # Default if no other indicators found
    return default_threshold
def extract_text_with_formatting(input_pdf):
    """
    Extracts text from a PDF using PyMuPDF, preserving formatting information
    and handling footnotes that span multiple pages, with dynamic footnote detection.
    """
    doc = fitz.open(input_pdf)
    
    # Lists to store document components
    pages_text = []
    all_superscripts = []
    footnote_definitions = {}  # Keyed by footnote number
    footnote_continuations = []  # Store potential continuations without numbers
    
    # First pass: extract text, superscripts, and identify footnote regions
    for page_num in range(len(doc)):
        page = doc[page_num]
        dict_format = page.get_text("dict")
        
        page_text = ""
        page_superscripts = []
        
        # Dynamically determine footnote boundary
        footnote_y_threshold = detect_footnote_boundary(page)
        footnote_area_text = []
        
        print(f"Page {page_num+1}: Footnote boundary detected at {footnote_y_threshold:.1f} " +
              f"({(footnote_y_threshold/page.rect.height*100):.1f}% from top)")
        
        for block in dict_format["blocks"]:
            # Skip non-text blocks
            if block["type"] != 0:
                continue
                
            for line in block["lines"]:
                # Check if this line is in the footnote area
                line_y = line["bbox"][1]  # Y-coordinate of line
                is_in_footnote_area = line_y > footnote_y_threshold
                
                line_text = ""
                line_positions = []
                
                for span in line["spans"]:
                    # Check if span is superscript (bit 0 in flags is set)
                    is_superscript = bool(span["flags"] & 2**0)
                    
                    span_text = span["text"]
                    start_pos = len(line_text)
                    line_text += span_text
                    
                    # If superscript, store the position and text
                    if is_superscript and re.match(r'^\d+$', span_text):
                        line_positions.append((start_pos, len(line_text), span_text))
                
                if is_in_footnote_area:
                    # Store this line as part of the footnote area
                    footnote_area_text.append(line_text)
                else:
                    # Regular text - add to page content
                    for pos in line_positions:
                        page_superscripts.append((len(page_text) + pos[0], len(page_text) + pos[1], pos[2], page_num))
                    
                    page_text += line_text + "\n"
        
        # Store page information
        pages_text.append(page_text)
        all_superscripts.extend(page_superscripts)
        
        # Process footnote area text to identify footnotes and continuations
        current_footnote_num = None
        current_footnote_text = ""
        
        for line in footnote_area_text:
            # Check if this line starts a new footnote
            footnote_match = re.match(r'^\s*(\d+)[\.\s]\s*(.+)$', line)
            
            if footnote_match:
                # If we were building a previous footnote, save it
                if current_footnote_num is not None:
                    if current_footnote_num in footnote_definitions:
                        footnote_definitions[current_footnote_num] += " " + current_footnote_text
                    else:
                        footnote_definitions[current_footnote_num] = current_footnote_text
                
                # Start a new footnote
                current_footnote_num = int(footnote_match.group(1))
                current_footnote_text = footnote_match.group(2)
            else:
                # This might be a continuation of the current footnote
                # or an orphaned continuation from a previous page
                if current_footnote_num is not None:
                    # Append to current footnote
                    current_footnote_text += " " + line
                else:
                    # This might be a continuation from a previous page
                    footnote_continuations.append((page_num, line))
        
        # Don't forget to save the last footnote on the page
        if current_footnote_num is not None:
            if current_footnote_num in footnote_definitions:
                footnote_definitions[current_footnote_num] += " " + current_footnote_text
            else:
                footnote_definitions[current_footnote_num] = current_footnote_text
    
    # Second pass: resolve continuations
    for page_num, continuation_text in footnote_continuations:
        # Find the most recent footnote before this continuation
        candidate_footnotes = [(num, text) for num, text in footnote_definitions.items()]
        candidate_footnotes.sort()  # Sort by footnote number
        
        if candidate_footnotes:
            # Assign to the highest numbered footnote as a best guess
            best_match = candidate_footnotes[-1][0]
            footnote_definitions[best_match] += " " + continuation_text.strip()
    
    doc.close()
    return {
        'pages_text': pages_text,
        'superscripts': all_superscripts,
        'footnotes': footnote_definitions
    }
def replace_superscript_references(document_data):
    """
    Replaces superscript references with inline footnotes across all pages.
    """
    pages_text = document_data['pages_text']
    footnotes = document_data['footnotes']
    superscripts = document_data['superscripts']
    
    # Sort by page and position in reverse order to not mess up the indices
    superscripts.sort(key=lambda x: (x[3], x[0]), reverse=True)
    
    # Process each page
    processed_pages = pages_text.copy()
    
    # Group superscripts by page
    superscripts_by_page = {}
    for start, end, ref_text, page_num in superscripts:
        if page_num not in superscripts_by_page:
            superscripts_by_page[page_num] = []
        superscripts_by_page[page_num].append((start, end, ref_text))
    
    # Replace superscripts on each page
    for page_num, page_superscripts in superscripts_by_page.items():
        page_text = processed_pages[page_num]
        
        # Sort by position in reverse order
        page_superscripts.sort(reverse=True)
        
        for start, end, ref_text in page_superscripts:
            try:
                footnote_num = int(ref_text)
                if footnote_num in footnotes:
                    footnote_text = footnotes[footnote_num]
                    replacement = f" [Footnote {footnote_num}: {footnote_text}]"
                    page_text = page_text[:start] + replacement + page_text[end:]
            except ValueError:
                # If the reference isn't a valid number, skip it
                continue
        
        processed_pages[page_num] = page_text
    
    return processed_pages
def process_pdf_to_rtf(input_pdf, output_rtf):
    """
    Extracts text from a PDF, preserves formatting, handles multi-page footnotes,
    replaces superscript footnote references, and saves it as an RTF file.
    """
    try:
        print(f"Processing {input_pdf}...")
        
        # Extract text with formatting information
        document_data = extract_text_with_formatting(input_pdf)
        
        # Log some statistics about what was found
        print(f"Found {len(document_data['footnotes'])} unique footnotes across {len(document_data['pages_text'])} pages")
        print(f"Detected {len(document_data['superscripts'])} superscript references")
        
        # Show some details about footnotes found
        if document_data['footnotes']:
            print("\nFirst few footnotes found:")
            for i, (num, text) in enumerate(sorted(document_data['footnotes'].items())[:3]):
                print(f"  {num}: {text[:60]}{'...' if len(text) > 60 else ''}")
            
            if len(document_data['footnotes']) > 3:
                print(f"  ... and {len(document_data['footnotes']) - 3} more")
        
        # Process each page and replace superscripts
        processed_pages = replace_superscript_references(document_data)
        
        # Combine all processed pages
        processed_text = "\n\n".join(processed_pages)
        
        # Remove control characters to ensure compatibility
        processed_text = "".join(char if char.isprintable() or char in "\n\t" else " " for char in processed_text)
        
        # Create output directory if it doesn't exist
        os.makedirs(os.path.dirname(output_rtf), exist_ok=True)
        
        # Save the processed text as an RTF file
        doc = Document()
        doc.add_paragraph(processed_text)
        doc.save(output_rtf)
        
        print(f"Processed file saved as {output_rtf}")
        return True
    except Exception as e:
        print(f"Error processing PDF: {e}")
        import traceback
        traceback.print_exc()
        return False
def batch_process_pdfs(input_folder, output_folder):
    """
    Process all PDF files in the input folder and save the results to the output folder.
    """
    # Create output folder if it doesn't exist
    os.makedirs(output_folder, exist_ok=True)
    
    # Get all PDF files in the input folder
    pdf_files = [f for f in os.listdir(input_folder) if f.lower().endswith('.pdf')]
    
    if not pdf_files:
        print(f"No PDF files found in {input_folder}")
        return
    
    print(f"Found {len(pdf_files)} PDF files to process")
    
    # Process each PDF file
    for pdf_file in pdf_files:
        input_path = os.path.join(input_folder, pdf_file)
        output_path = os.path.join(output_folder, f"{os.path.splitext(pdf_file)[0]}.rtf")
        
        print(f"\nProcessing {pdf_file}...")
        process_pdf_to_rtf(input_path, output_path)
    
    print("\nBatch processing completed!")
# Example usage
if __name__ == "__main__":
    # For single file processing
    input_pdf = "/Users/izzie/Desktop/USCIS Tests/USCIS-2025-0004-1569.pdf"
    output_rtf = "/Users/izzie/Desktop/test_output.rtf"
    process_pdf_to_rtf(input_pdf, output_rtf)
    
    # For batch processing
    # batch_process_pdfs("input_folder", "output_folder")