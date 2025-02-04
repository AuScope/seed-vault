from datetime import datetime, date, time, timedelta
from dateutil.relativedelta import relativedelta
from obspy.clients.fdsn import Client
import streamlit as st


def is_in_enum(item, enum_class):
    return item in (member.value for member in enum_class)


def get_time_interval(interval_type: str, amount: int = 1):
    """
    Get the current date-time and the date-time `amount` intervals earlier.

    Args:
        interval_type (str): One of ['hour', 'day', 'week', 'month']
        amount (int): Number of intervals to go back (default is 1)

    Returns:
        tuple: (current_datetime, past_datetime)
    """
    now = datetime.now()

    if interval_type == "hour":
        past = now - timedelta(hours=amount)
    elif interval_type == "day":
        past = now - timedelta(days=amount)
    elif interval_type == "week":
        past = now - timedelta(weeks=amount)
    elif interval_type == "month":
        past = now - relativedelta(months=amount)
    else:
        st.error(f"Invalid interval type: {interval_type}. Choose from 'hour', 'day', 'week', 'month'.")
        return now, now  # Default fallback

    return now, past


def convert_to_datetime(value):
    """Convert a string or other value to a date and time object, handling different formats.
    
    If only a date is provided, it defaults to 00:00:00 time.
    """
    if isinstance(value, datetime):
        return value.date(), value.time()
    elif isinstance(value, date):
        return value, time(0, 0, 0)  # Default time if only date is given
    elif isinstance(value, str):
        try:
            # Try full ISO format first (e.g., "2025-02-04T14:30:00" or "2025-02-04 14:30:00")
            dt_obj = datetime.fromisoformat(value.replace("T", " "))
            return dt_obj.date(), dt_obj.time()
        except ValueError:
            try:
                # If only a date is provided, default to midnight (00:00:00)
                dt_obj = datetime.strptime(value, "%Y-%m-%d")
                return dt_obj.date(), time(0, 0, 0)
            except ValueError:
                st.error(f"Invalid datetime format: {value}. Expected ISO format 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS'.")
                return date.today(), time(0, 0, 0)  # Default fallback
    
    return date.today(), time(0, 0, 0)


def check_client_services(client_name: str):
    """Check which services are available for a given client name."""
    try:
        client = Client(client_name)
        available_services = client.services.keys()  # Get available services as keys
        return {
            'station': 'station' in available_services,
            'event': 'event' in available_services,
            'dataselect': 'dataselect' in available_services
        }
    except Exception as e:
        st.error(f"Error checking client services: {str(e)}")
        return {
            'station': False,
            'event': False,
            'dataselect': False
        } 