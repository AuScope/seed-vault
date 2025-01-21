from datetime import datetime, date
from obspy.clients.fdsn import Client
import streamlit as st


def is_in_enum(item, enum_class):
    return item in (member.value for member in enum_class)

def convert_to_date(value):
    """Convert a string or other value to a date object, handling different formats."""
    if isinstance(value, date):
        return value
    elif isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            try:
                return datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                st.error(f"Invalid date format: {value}. Expected ISO format 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS'.")
                return date.today()  
    else:
        return date.today() 

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