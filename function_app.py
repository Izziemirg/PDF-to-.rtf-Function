import re
from pdfminer.high_level import extract_text
from docx import Document
def extract_footnotes(text):
    """
    Extracts footnotes from the text, assuming they are numbered at the bottom of the document.
    Returns the main text with footnotes removed and a dictionary of footnotes.
    """
    footnote_pattern = re.compile(r"(\n?\d+)\s(.+)")
    footnotes = {}
    # Identify footnotes and store them
    matches = footnote_pattern.findall(text)
    for match in matches:
        number, content = match
        footnotes[int(number.strip())] = content.strip()
    # Remove footnotes completely from the text (no blank lines)
    text = footnote_pattern.sub("", text).strip()
    return text, footnotes
def replace_superscript_references(text, footnotes):
    """
    Replaces superscript footnote references in the main text with inline footnotes.
    """
    superscript_pattern = re.compile(r"(\d+)\b")
    def replace_match(match):
        num = int(match.group(1))
        if num in footnotes:
            return f" [Footnote {num}: {footnotes[num]}]"
        return match.group(0)
    return superscript_pattern.sub(replace_match, text)
def process_pdf_to_rtf(input_pdf, output_rtf):
    """
    Extracts text from a PDF, replaces superscript footnote references, and saves it as an RTF file.
    """
    # Extract text from the PDF
    raw_text = extract_text(input_pdf)
    # Extract and completely remove footnotes
    clean_text, footnotes = extract_footnotes(raw_text)
    # Replace superscript references in the main text
    processed_text = replace_superscript_references(clean_text, footnotes)
    # Remove control characters to ensure compatibility
    processed_text = "".join(char if char.isprintable() or char in "\n\t" else " " for char in processed_text)
    # Save the processed text as an RTF file
    doc = Document()
    doc.add_paragraph(processed_text)
    doc.save(output_rtf)
    print(f"Processed file saved as {output_rtf}")
# Example usage:
input_pdf = "/Users/izzie/Desktop/Newtestdoc18ft.pdf"
output_rtf = "/Users/izzie/Desktop/output.rtf"
process_pdf_to_rtf(input_pdf, output_rtf)
