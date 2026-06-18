from datetime import datetime
import os
import json
import logging
import google.generativeai as genai
import pytz
from PIL import Image
from io import BytesIO

# Set up logging
logger = logging.getLogger(__name__)

# --- Gemini API Configuration ---
# Your Gemini API key should be set as an environment variable
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY environment variable is not set.")
    raise ValueError("Missing GEMINI_API_KEY environment variable.")

# Configure the Gemini API client
genai.configure(api_key=GEMINI_API_KEY)


async def extract_booking_info(image_data: bytes):
    """
    Calls the Gemini API with an image and a prompt to extract booking details.
    
    Args:
        image_data (bytes): The raw bytes of the image file.
        
    Returns:
        dict: A dictionary with extracted booking details or an empty dict if extraction fails.
    """
    # get the current date in Singapore time, since all bookings are local to that timezone
    current_date = datetime.now(pytz.timezone("Asia/Singapore")).strftime("%Y-%m-%d")

    prompt = f"""
    You are a highly specialized text extraction model. From the following image, which is a booking confirmation, extract the following information and return it in a JSON format.

    1.  **date**: The booking date in 'YYYY-MM-DD' format.
    2.  **time**: The booking time range in 'HH:MM-HH:MM' format.
    3.  **location**: The name of the booking location. Include court info if have any.
    4.  **booker_name**: The name of the person who made the booking.

    Today's date is {current_date}. Use it to resolve the booking year, following these rules in order:
    1. Default to the year of today's date ({current_date[:4]}).
    2. Only use a different year if the image explicitly prints that year next to the booking date (e.g. "2026" or "26").
    3. If no year is printed and the booking's month/day would fall more than 3 weeks before today using the default year, use next year instead, since bookings are always for upcoming sessions.

    In some images, there may not be a end time included in the message. For these cases, check how many start times are included. It can be assumed that each slot is only 1 hour, so if there is only 1 start time (ie: 14:00), the time range returned should be (14:00-15:00)

    If any information is not found, use a null value. Do not add any extra text outside of the JSON object.

    Example response format:
    {{
      "date": "2025-08-20",
      "time": "19:00-21:00",
      "location": "Radin Mas Primary School Court 3",
      "booker_name": "John Doe"
    }}
    """
    
    try:
        model = genai.GenerativeModel(model_name='gemini-2.5-pro')
        
        # The genai library can't process a bytearray directly, so we convert it to a PIL Image.
        image = Image.open(BytesIO(image_data))
        
        response = model.generate_content([prompt, image])
        
        # The Gemini API might return a Markdown block, so we'll clean it up
        json_text = response.text.strip("```json\n").strip("\n```")
        
        try:
            extracted_data = json.loads(json_text)
            return extracted_data
        except json.JSONDecodeError:
            logger.error(f"Failed to decode JSON from Gemini API: {json_text}")
            return {}
            
    except Exception as e:
        logger.error(f"Error in Gemini API request: {e}")
        return {}
