import os
from google import genai
print(os.environ.get("GEMINI_API_KEY"))

import toml
from google import genai

# Load the TOML file
secrets = toml.load(".streamlit/secrets.toml")

# Extract the Gemini API key
api_key = secrets["GEMINI_API_KEY"]

# The client gets the API key from the environment variable `GEMINI_API_KEY`.
from google import genai

client = genai.Client(api_key=api_key)

response = client.models.generate_content(
    model="gemini-3-flash-preview",
    contents="Explain how AI works in a few words"
)
print(response.text)