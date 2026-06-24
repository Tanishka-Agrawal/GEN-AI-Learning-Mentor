import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key or api_key.startswith("your_"):
    print("No valid API key found in .env. Current value is a placeholder.")
else:
    print(f"Verifying key starting with: {api_key[:10]}...")
    try:
        genai.configure(api_key=api_key)
        print("Fetching model list from Google AI Studio...")
        models = list(genai.list_models())
        print(f"\nSuccess! Your API Key has access to the following {len(models)} models:")
        for m in models:
            if 'generateContent' in m.supported_generation_methods:
                print(f"  - {m.name} (Supported)")
    except Exception as e:
        print(f"\nError: Google returned an error: {e}")
        print("\nPossible solutions:")
        print("1. Confirm you are using a Gemini API Key from Google AI Studio (https://aistudio.google.com/).")
        print("2. Ensure your key starts with 'AIzaSy'. Keys starting with other prefixes (like 'AQ.') might be Google Cloud service account tokens, which require different authentication packages.")
