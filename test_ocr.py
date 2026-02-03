import pytesseract
from PIL import Image
import os

img_path = r'C:/Users/laksh/.gemini/antigravity/brain/515cb6b4-7834-4d58-a16c-ae2848acedf0/uploaded_media_1769705680962.png'

# Tesseract cmd if needed (based on app.py logic)
common_paths = [
    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
    r'C:\Users\laksh\AppData\Local\Programs\Tesseract-OCR\tesseract.exe' 
]

for path in common_paths:
    if os.path.exists(path):
        pytesseract.pytesseract.tesseract_cmd = path
        break

try:
    img = Image.open(img_path)
    text = pytesseract.image_to_string(img)
    print("--- OCR START ---")
    print(text)
    print("--- OCR END ---")
except Exception as e:
    print(f"Error: {e}")
