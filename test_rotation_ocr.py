import pytesseract
from PIL import Image
import os

img_path = r'C:/Users/laksh/.gemini/antigravity/brain/515cb6b4-7834-4d58-a16c-ae2848acedf0/uploaded_media_1769705680962.png'

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
    # Try different rotations
    print("--- TESTING ROTATIONS ---")
    for angle in [0, -20, -15, -10, 10, 15, 20]:
        rotated = img.rotate(angle, expand=True)
        text = pytesseract.image_to_string(rotated)
        if text.strip():
            print(f"--- ANGLE {angle} SUCCESS ---")
            print(text)
            print("-" * 20)
    print("--- TESTING END ---")
except Exception as e:
    print(f"Error: {e}")
