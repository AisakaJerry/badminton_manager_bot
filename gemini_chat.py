import os
import logging
import google.generativeai as genai

# Set up logging
logger = logging.getLogger(__name__)

# --- Gemini API Configuration ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY environment variable is not set.")
    # In a production app, you might want to handle this more gracefully.
    raise ValueError("Missing GEMINI_API_KEY environment variable.")

# Configure the Gemini API client
genai.configure(api_key=GEMINI_API_KEY)

async def get_gemini_response(prompt_text: str):
    """
    Calls the Gemini API with a text prompt and returns the generated response.
    
    Args:
        prompt_text (str): The text message from the user.
        
    Returns:
        str: The AI-generated response or an error message.
    """
    try:
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(prompt_text)
        return response.text
    except Exception as e:
        logger.error(f"Gemini API request failed: {e}")
        return "Sorry, I couldn't process your request at the moment."