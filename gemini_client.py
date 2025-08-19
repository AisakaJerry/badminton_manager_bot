import os
import json
import logging
import base64
import aiohttp

# Set up logging
logger = logging.getLogger(__name__)

# --- Gemini API Configuration ---
# Your Gemini API key should be set as an environment variable
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY environment variable is not set.")
    # In a production app, you might want to handle this more gracefully.
    # For now, it will raise an error and prevent the bot from starting.
    raise ValueError("Missing GEMINI_API_KEY environment variable.")


async def extract_booking_info(image_data: bytes, mime_type: str = "image/jpeg"):
    """
    Calls the Gemini API with an image and a prompt to extract booking details.
    
    Args:
        image_data (bytes): The raw bytes of the image file.
        mime_type (str): The MIME type of the image (e.g., 'image/jpeg', 'image/png').
        
    Returns:
        dict: A dictionary with extracted booking details or an empty dict if extraction fails.
    """
    prompt = """
    You are a highly specialized text extraction model. From the following image, which is a booking confirmation, extract the following information and return it in a JSON format.
    
    1.  **date**: The booking date in 'YYYY-MM-DD' format.
    2.  **time**: The booking time range in 'HH:MM-HH:MM' format.
    3.  **location**: The name of the booking location.
    4.  **booker_name**: The name of the person who made the booking.
    
    If any information is not found, use a null value. Do not add any extra text outside of the JSON object.
    
    Example response format:
    {
      "date": "2025-08-20",
      "time": "19:00-21:00",
      "location": "Radin Mas Primary School Court 3",
      "booker_name": "John Doe"
    }
    """
    
    base64_image = base64.b64encode(image_data).decode("utf-8")
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inlineData": {"mimeType": mime_type, "data": base64_image}}
                ]
            }
        ]
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GEMINI_API_KEY}"
    }
    
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-vision:generateContent"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=json.dumps(payload)) as response:
                response.raise_for_status()
                result = await response.json()
        
        # Check if the response contains valid candidates and content
        if result and result.get("candidates"):
            text = result["candidates"][0]["content"]["parts"][0]["text"]
            # The Gemini API might return a Markdown block, so we'll clean it up
            json_text = text.strip("```json\n").strip("\n```")
            
            try:
                extracted_data = json.loads(json_text)
                return extracted_data
            except json.JSONDecodeError:
                logger.error(f"Failed to decode JSON from Gemini API: {json_text}")
                return {}
        else:
            logger.warning(f"Gemini API response did not contain candidates: {result}")
            return {}
            
    except aiohttp.ClientError as e:
        logger.error(f"Gemini API request failed: {e}")
        return {}
