from datetime import datetime
import re
import fitz  # PyMuPDF
from docx import Document
import os

def roman_to_int(s):
    """
    Convert a Roman numeral to an integer.
    """
    if not s:
        return 0
        
    roman_dict = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    result = 0
    
    # Convert to uppercase for consistency
    s = s.upper()
    
    for i in range(len(s)):
        # If current value is less than next value, subtract it
        if i < len(s) - 1 and roman_dict[s[i]] < roman_dict[s[i + 1]]:
            result -= roman_dict[s[i]]
        else:
            result += roman_dict[s[i]]
            
    return result

def is_roman_numeral(s):
    """
    Check if a string is a valid Roman numeral.
    """
    if not s:
        return False
        
    # Convert to uppercase for consistency
    s = s.upper()
    
    # Check if string only contains valid Roman numeral characters
    if not all(c in 'IVXLCDM' for c in s):
        return False
        
    # Basic pattern check (this is a simplified check)
    pattern = re.compile(r'^M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$')
    return bool(pattern.match(s))

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
    
    # Look for footnote number patterns (both Arabic and Roman numerals)
    dict_format = page.get_text("dict")
    footnote_candidates = []
    
    for block in dict_format["blocks"]:
        if block["type"] == 0:  # Text block
            for line in block["lines"]:
                line_text = "".join(span["text"] for span in line["spans"])
                
                # Look for Arabic number patterns like "1." or "1 " at beginning of line
                if re.match(r'^\s*\d+[\.\s]', line_text):
                    y_pos = line["bbox"][1]
                    if y_pos > page.rect.height * 0.4:  # Only consider if in bottom 60%
                        footnote_candidates.append(y_pos)
                
                # Look for Roman numeral patterns like "i." or "iv " at beginning of line
                roman_match = re.match(r'^\s*([ivxlcdmIVXLCDM]+)[\.\s]', line_text)
                if roman_match and is_roman_numeral(roman_match.group(1)):
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
    Supports both Arabic numerals and Roman numerals for footnotes.
    """
    doc = fitz.open(input_pdf)
    
    # Lists to store document components
    pages_text = []
    all_superscripts = []
    footnote_definitions = {}  # Keyed by footnote number (int)
    roman_footnote_definitions = {}  # Keyed by Roman numeral (string)
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
                    if is_superscript:
                        # Check if it's a digit or Roman numeral
                        if re.match(r'^\d+$', span_text):
                            # Arabic numeral
                            line_positions.append((start_pos, len(line_text), span_text, 'arabic'))
                        elif is_roman_numeral(span_text):
                            # Roman numeral
                            line_positions.append((start_pos, len(line_text), span_text, 'roman'))
                
                if is_in_footnote_area:
                    # Store this line as part of the footnote area
                    footnote_area_text.append(line_text)
                else:
                    # Regular text - add to page content
                    for pos in line_positions:
                        page_superscripts.append((len(page_text) + pos[0], len(page_text) + pos[1], pos[2], page_num, pos[3]))
                    
                    page_text += line_text + "\n"
        
        # Store page information
        pages_text.append(page_text)
        all_superscripts.extend(page_superscripts)
        
        # Process footnote area text to identify footnotes and continuations
        current_footnote_num = None
        current_footnote_type = None  # 'arabic' or 'roman'
        current_footnote_text = ""
        
        for line in footnote_area_text:
            # Check if this line starts a new Arabic numeral footnote
            arabic_match = re.match(r'^\s*(\d+)[\.\s]\s*(.+)$', line)
            
            # Check if this line starts a new Roman numeral footnote
            roman_match = re.match(r'^\s*([ivxlcdmIVXLCDM]+)[\.\s]\s*(.+)$', line)
            
            if arabic_match:
                # If we were building a previous footnote, save it
                if current_footnote_num is not None:
                    if current_footnote_type == 'arabic':
                        if current_footnote_num in footnote_definitions:
                            footnote_definitions[current_footnote_num] += " " + current_footnote_text
                        else:
                            footnote_definitions[current_footnote_num] = current_footnote_text
                    elif current_footnote_type == 'roman':
                        if current_footnote_num in roman_footnote_definitions:
                            roman_footnote_definitions[current_footnote_num] += " " + current_footnote_text
                        else:
                            roman_footnote_definitions[current_footnote_num] = current_footnote_text
                
                # Start a new Arabic footnote
                current_footnote_num = int(arabic_match.group(1))
                current_footnote_type = 'arabic'
                current_footnote_text = arabic_match.group(2)
                
            elif roman_match and is_roman_numeral(roman_match.group(1)):
                # If we were building a previous footnote, save it
                if current_footnote_num is not None:
                    if current_footnote_type == 'arabic':
                        if current_footnote_num in footnote_definitions:
                            footnote_definitions[current_footnote_num] += " " + current_footnote_text
                        else:
                            footnote_definitions[current_footnote_num] = current_footnote_text
                    elif current_footnote_type == 'roman':
                        if current_footnote_num in roman_footnote_definitions:
                            roman_footnote_definitions[current_footnote_num] += " " + current_footnote_text
                        else:
                            roman_footnote_definitions[current_footnote_num] = current_footnote_text
                
                # Start a new Roman footnote
                current_footnote_num = roman_match.group(1)  # Store the actual Roman numeral
                current_footnote_type = 'roman'
                current_footnote_text = roman_match.group(2)
                
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
            if current_footnote_type == 'arabic':
                if current_footnote_num in footnote_definitions:
                    footnote_definitions[current_footnote_num] += " " + current_footnote_text
                else:
                    footnote_definitions[current_footnote_num] = current_footnote_text
            elif current_footnote_type == 'roman':
                if current_footnote_num in roman_footnote_definitions:
                    roman_footnote_definitions[current_footnote_num] += " " + current_footnote_text
                else:
                    roman_footnote_definitions[current_footnote_num] = current_footnote_text
    
    # Second pass: resolve continuations
    # For simplicity, we'll add continuations to the last footnote of either type
    for page_num, continuation_text in footnote_continuations:
        if roman_footnote_definitions:
            # Add to the last Roman footnote
            last_roman = sorted(roman_footnote_definitions.keys())[-1]
            roman_footnote_definitions[last_roman] += " " + continuation_text.strip()
        elif footnote_definitions:
            # Add to the last Arabic footnote
            last_arabic = max(footnote_definitions.keys())
            footnote_definitions[last_arabic] += " " + continuation_text.strip()
    
    doc.close()
    return {
        'pages_text': pages_text,
        'superscripts': all_superscripts,
        'arabic_footnotes': footnote_definitions,
        'roman_footnotes': roman_footnote_definitions
    }

def replace_superscript_references(document_data):
    """
    Replaces superscript references with inline footnotes across all pages.
    Handles both Arabic and Roman numeral footnotes.
    """
    pages_text = document_data['pages_text']
    arabic_footnotes = document_data['arabic_footnotes']
    roman_footnotes = document_data['roman_footnotes']
    superscripts = document_data['superscripts']
    
    # Sort by page and position in reverse order to not mess up the indices
    superscripts.sort(key=lambda x: (x[3], x[0]), reverse=True)
    
    # Process each page
    processed_pages = pages_text.copy()
    
    # Group superscripts by page
    superscripts_by_page = {}
    for start, end, ref_text, page_num, footnote_type in superscripts:
        if page_num not in superscripts_by_page:
            superscripts_by_page[page_num] = []
        superscripts_by_page[page_num].append((start, end, ref_text, footnote_type))
    
    # Replace superscripts on each page
    for page_num, page_superscripts in superscripts_by_page.items():
        page_text = processed_pages[page_num]
        
        # Sort by position in reverse order
        page_superscripts.sort(key=lambda x: x[0], reverse=True)
        
        for start, end, ref_text, footnote_type in page_superscripts:
            if footnote_type == 'arabic':
                try:
                    footnote_num = int(ref_text)
                    if footnote_num in arabic_footnotes:
                        footnote_text = arabic_footnotes[footnote_num]
                        replacement = f" [Footnote {ref_text}: {footnote_text}]"
                        page_text = page_text[:start] + replacement + page_text[end:]
                except ValueError:
                    # If the reference isn't a valid number, skip it
                    continue
            elif footnote_type == 'roman':
                if ref_text in roman_footnotes:
                    footnote_text = roman_footnotes[ref_text]
                    replacement = f" [Footnote {ref_text}: {footnote_text}]"
                    page_text = page_text[:start] + replacement + page_text[end:]
        
        processed_pages[page_num] = page_text
    
    return processed_pages

def process_pdf_to_rtf(input_pdf, output_rtf):
    """
    Extracts text from a PDF, preserves formatting, handles multi-page footnotes,
    replaces superscript footnote references (both Arabic and Roman numerals),
    and saves it as an RTF file.
    """
    try:
        print(f"Processing {input_pdf}...")
        
        # Extract text with formatting information
        document_data = extract_text_with_formatting(input_pdf)
        
        # Log some statistics about what was found
        arabic_count = len(document_data['arabic_footnotes'])
        roman_count = len(document_data['roman_footnotes'])
        print(f"Found {arabic_count} Arabic numeral footnotes and {roman_count} Roman numeral footnotes")
        print(f"Detected {len(document_data['superscripts'])} superscript references")
        
        # Show some details about footnotes found
        if document_data['arabic_footnotes']:
            print("\nFirst few Arabic numeral footnotes found:")
            for i, (num, text) in enumerate(sorted(document_data['arabic_footnotes'].items())[:3]):
                print(f"  {num}: {text[:60]}{'...' if len(text) > 60 else ''}")
            
            if len(document_data['arabic_footnotes']) > 3:
                print(f"  ... and {len(document_data['arabic_footnotes']) - 3} more")
        
        if document_data['roman_footnotes']:
            print("\nFirst few Roman numeral footnotes found:")
            for i, (num, text) in enumerate(sorted(document_data['roman_footnotes'].items(), 
                                                 key=lambda x: roman_to_int(x[0]))[:3]):
                print(f"  {num}: {text[:60]}{'...' if len(text) > 60 else ''}")
            
            if len(document_data['roman_footnotes']) > 3:
                print(f"  ... and {len(document_data['roman_footnotes']) - 3} more")
        
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
    input_pdf = "/Users/izzie/Desktop/USCIS Tests/USCIS-2025-0004-3360.pdf"
    output_rtf = "/Users/izzie/Desktop/test_output.rtf"
    process_pdf_to_rtf(input_pdf, output_rtf)
    
    # For batch processing
    # batch_process_pdfs("input_folder", "output_folder")