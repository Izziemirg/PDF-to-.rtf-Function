from datetime import datetime
import re
from pdfminer.high_level import extract_text
from docx import Document

# TODO: It may be worth investigating a way to "break" the page into two chunks first (content and footnotes)
# That might help alleviate some of the issues of grabbing text from other areas of the content as footnotes

# TODO: So, I'm definitely not an expert on pdf packages for python, but it may be worth investigating other packages if pdfminer doesn't help with superscript detection
# I stumbled upon this github issues and the package looks relatively popular: https://github.com/pymupdf/PyMuPDF/discussions/3286
# Another one to potentially check out: https://github.com/jsvine/pdfplumber
# (Not saying don't use pdfminer, it very well could be the best option)

# NOTE: Going page by page may help alleviate some issues as well.
# Though, it may be more of a band aid fix for some of these issues

# NOTE: So, final thoughts, I think the issues are definitely stemming from the detection between what are footnotes vs content of the document
# If you can sure that up a little bit, I think it will help a lot of the other pieces fall in line.
# Also, finding a better regex pattern to avoid detecting (non superscript) numbers in the footnote text 
# (Though you may not need to if you can find a way for the pdf package to detect superscripts)
# Really cool stuff so far! I hope my comments at least make some sense and are a bit helpful!

"""
I'll leave the notes I took on the issues I noticed here in case they are helpful to reference.

These ones are real issues that need solutions:
- The script seems to only use the first line of a footnote when inserting it in line
- Sentence was caught where there was a 2 instead of grabbing the actual number 2 footnote
- Numbers within the footnotes are being caught as footnotes and replaced

These ones may be tangentially fixed by correcting other issues (as we discussed, the footnote may have been eaten by another digit in the text):
- In the case of 3 footnotes (1,2,3), footnote 1 and 3 seem to get replaced, but not 2
- Punctuation (in this case a period) seems to prevent the footnote from being detected (i.e. U.S..12)

"""

def extract_footnotes(text):
    """
    Extracts footnotes from the text, assuming they are numbered at the bottom of the document.
    Returns the main text with footnotes removed and a dictionary of footnotes.
    """
    # XXX: I think this regex pattern is probably not capturing everything we care about
    # XXX: Since "." matches every character other than a new line, this may explain why we are only seeing one line of the footnote in the text
    footnote_pattern = re.compile(r"(\n?\d+)\s(.+)")
    footnotes = {}
    # Identify footnotes and store them
    matches = footnote_pattern.findall(text)
    for match in matches:
        number, content = match
        footnotes[int(number.strip())] = content.strip()
    # Remove footnotes completely from the text (no blank lines)
    # XXX: The result of this will leave a number of footnote related lines in the text
    text = footnote_pattern.sub("", text).strip() 
    return text, footnotes

def replace_superscript_references(text, footnotes):
    """
    Replaces superscript footnote references in the main text with inline footnotes.
    """
    # XXX: This regex pattern is probably a little too basic for what is trying to be accomplished
    # XXX: It is going to catch any number in the text that is before a non character
    # NOTE: This should actually match correctly on 1,2,3 so I'm guessing the missing 2 footnote was due to another issue
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
# NOTE: I updated this to use the usual entry point for python scripts (python -m function_app)
if __name__ == "__main__":
    input_pdf = "input/Titles_headers.pdf"
    output_rtf = f'output/output{datetime.now().strftime("%y%m%d%H%M%S")}.rtf'
    process_pdf_to_rtf(input_pdf, output_rtf)
