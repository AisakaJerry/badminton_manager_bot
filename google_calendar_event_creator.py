import os
import json
import logging
from datetime import datetime
import pytz
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Read configuration from environment variables
CREDENTIALS_JSON = os.environ.get("GOOGLE_CALENDAR_CREDENTIALS_JSON")
CALENDAR_ID = os.environ.get("CALENDAR_ID", "primary")

# Raise an error if the credentials are not set
if not CREDENTIALS_JSON:
    logging.error("GOOGLE_CALENDAR_CREDENTIALS_JSON environment variable is not set.")
    raise ValueError("Missing GOOGLE_CALENDAR_CREDENTIALS_JSON environment variable.")

# Parse credentials using the correct method for service accounts
try:
    from google.oauth2 import service_account
    
    creds_info = json.loads(CREDENTIALS_JSON)
    creds = service_account.Credentials.from_service_account_info(
        creds_info,
        scopes=['https://www.googleapis.com/auth/calendar.events']
    )
except (json.JSONDecodeError, ValueError, ImportError) as e:
    logging.error(f"Failed to parse or load service account credentials: {e}")
    raise

def create_calendar_event(date: str, time_range: str, location: str, description: str, summary: str = "Badminton 🏸"):
    """
    Creates a Google Calendar event.

    Args:
        date (str): The date of the event in 'YYYY-MM-DD' format.
        time_range (str): The time of the event in 'HH:MM-HH:MM' format.
        location (str): The location of the event.
        summary (str): A summary or title for the event.

    Returns:
        str: The HTML link to the created event on success, or None on failure.
    """
    try:
        service = build("calendar", "v3", credentials=creds)

        # Parse date and time
        start_time_str, end_time_str = time_range.split('-')
        
        # Use a timezone object to correctly localize the user's input time
        timezone_sg = pytz.timezone("Asia/Singapore")
        
        # Create naive datetime objects
        start_datetime_naive = datetime.strptime(f"{date} {start_time_str}", '%Y-%m-%d %H:%M')
        end_datetime_naive = datetime.strptime(f"{date} {end_time_str}", '%Y-%m-%d %H:%M')
        
        # Localize the naive datetime objects to the correct timezone
        start_datetime_local = timezone_sg.localize(start_datetime_naive)
        end_datetime_local = timezone_sg.localize(end_datetime_naive)

        event = {
            "summary": summary,
            "location": location,
            "description": description,
            "start": {
                "dateTime": start_datetime_local.isoformat(),
                "timeZone": "Asia/Singapore",
            },
            "end": {
                "dateTime": end_datetime_local.isoformat(),
                "timeZone": "Asia/Singapore",
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 24 * 60},
                    {"method": "popup", "minutes": 10},
                ],
            },
        }

        event = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        logging.info(f"Event created: {event.get('htmlLink')}")
        return event.get('htmlLink')

    except HttpError as e:
        logging.error(f"An HTTP error occurred while creating the event: {e}")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return None
