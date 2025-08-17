import os
import json
import logging
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Read configuration from environment variables
CREDENTIALS_JSON = os.environ.get("GOOGLE_CALENDAR_CREDENTIALS_JSON")
EVENT_ATTENDEES_STR = os.environ.get("EVENT_ATTENDEES", "")
CALENDAR_ID = os.environ.get("CALENDAR_ID", "primary")

# Raise an error if the credentials are not set
if not CREDENTIALS_JSON:
    logging.error("GOOGLE_CALENDAR_CREDENTIALS_JSON environment variable is not set.")
    raise ValueError("Missing GOOGLE_CALENDAR_CREDENTIALS_JSON environment variable.")

# Parse credentials using the correct method for service accounts
try:
    # Use google.oauth2.service_account instead of generic Credentials
    from google.oauth2 import service_account
    
    creds_info = json.loads(CREDENTIALS_JSON)
    # The `from_service_account_info` method is specifically designed for service account credentials
    creds = service_account.Credentials.from_service_account_info(
        creds_info,
        scopes=['https://www.googleapis.com/auth/calendar.events']
    )
except (json.JSONDecodeError, ValueError, ImportError) as e:
    logging.error(f"Failed to parse or load service account credentials: {e}")
    raise

# Parse attendees
ATTENDEES = [{"email": email.strip()} for email in EVENT_ATTENDEES_STR.split(',') if email.strip()]

def create_calendar_event(date: str, time_range: str, location: str, summary: str = "Badminton Booking"):
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
        start_datetime = datetime.strptime(f"{date} {start_time_str}", '%Y-%m-%d %H:%M')
        end_datetime = datetime.strptime(f"{date} {end_time_str}", '%Y-%m-%d %H:%M')
        
        timezone = "Asia/Singapore"
        # Using a consistent timezone for event creation
        start_datetime = start_datetime.replace(tzinfo=datetime.now().astimezone().tzinfo)
        end_datetime = end_datetime.replace(tzinfo=datetime.now().astimezone().tzinfo)

        event = {
            "summary": summary,
            "location": location,
            "description": f"A badminton session at {location}",
            "start": {
                "dateTime": start_datetime.isoformat(),
                "timeZone": timezone,
            },
            "end": {
                "dateTime": end_datetime.isoformat(),
                "timeZone": timezone,
            },
            # "attendees": ATTENDEES,
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 24 * 60},
                    {"method": "popup", "minutes": 10},
                ],
            },
        }

        # Use the CALENDAR_ID environment variable
        event = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        logging.info(f"Event created: {event.get('htmlLink')}")
        return event.get('htmlLink')

    except HttpError as e:
        logging.error(f"An HTTP error occurred while creating the event: {e}")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return None

# Execute this block if the script is run directly
if __name__ == "__main__":
    try:
        event_link = create_calendar_event(
            date="2025-08-25",
            time_range="20:00-22:00",
            location="ABC Badminton Hall, Court 3",
            summary="Weekly Badminton Game"
        )
        if event_link:
            print(f"Successfully created a calendar event. The link is: {event_link}")
        else:
            print("Failed to create a calendar event. Please check the logs for more information.")
    except Exception as e:
        print(f"Script execution failed: {e}")
