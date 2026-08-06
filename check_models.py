import os
import google.generativeai as genai
from dotenv import load_dotenv

# Load API Key dari .env
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY") # Sesuaikan dengan nama variabel di .env Anda

if not api_key:
    print("Error: GEMINI_API_KEY tidak ditemukan di .env")
    exit()

genai.configure(api_key=api_key)

print("Mencari model Gemini yang tersedia untuk generateContent...\n")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name.replace('models/', '')}")
except Exception as e:
    print(f"Gagal mengambil daftar model: {e}")