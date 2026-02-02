import google.generativeai as genai
import os

api_key = "AIzaSyCf0SE8IetEWv5EchFUgKGcBiAZRGE9q74"
genai.configure(api_key=api_key)

print("Listing models...")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"Model: {m.name}")
except Exception as e:
    print(f"Error: {e}")
