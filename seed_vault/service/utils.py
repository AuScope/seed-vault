from typing import Any, Dict, List, Tuple, Optional, Union

from datetime import datetime, date, time, timedelta, timezone
from dateutil.relativedelta import relativedelta

import streamlit as st

from obspy import UTCDateTime
from obspy.clients.fdsn import Client
from obspy.core.inventory import Inventory
from obspy.core.event import Event,Catalog
from obspy.geodetics import locations2degrees

from seed_vault.enums.config import GeoConstraintType

def is_in_enum(item, enum_class):
    return item in (member.value for member in enum_class)


# It may be worth also outputting the max/min network spans (TODO)
def parse_inv(inv: Inventory):
    """
    Return 4 lists (net, sta, loc, cha) detailing the contents of an ObsPy inventory file
    
    Args:
        inv (Inventory): ObsPy Inventory object
        
    Returns:
        tuple: Four lists containing all network, station, location, and channel codes
    """
    networks = []
    stations = []
    locations = []
    channels = []

    if not inv:
        return networks, stations, locations, channels
    
    for network in inv:
        networks.append(network.code)
        
        for station in network:
            stations.append(station.code)
            
            for channel in station:
                if channel.location_code not in locations:
                    locations.append(channel.location_code)
                
                if channel.code not in channels:
                    channels.append(channel.code)
    
    networks = sorted(list(set(networks)))
    stations = sorted(list(set(stations)))
    locations = sorted(list(set(locations)))
    channels = sorted(list(set(channels)))
    
    return networks, stations, locations, channels



def get_time_interval(interval_type: str, amount: int = 1):
    """
    Get the current date-time and the date-time `amount` intervals earlier.

    Args:
        interval_type (str): One of ['hour', 'day', 'week', 'month']
        amount (int): Number of intervals to go back (default is 1)

    Returns:
        tuple: (current_datetime, past_datetime)
    """
    now = datetime.now(timezone.utc)

    if interval_type == "hour":
        now = now.replace(second=0, microsecond=0)
        past = now - timedelta(hours=amount)
    elif interval_type == "day":
        now = now.replace(second=0, microsecond=0)
        past = now - timedelta(days=amount)
    elif interval_type == "week":
        now = now.replace(second=0, microsecond=0)
        past = now - timedelta(weeks=amount)
        past = past.replace(hour=0, minute=0)
    elif interval_type == "month":
        now = now.replace(second=0, microsecond=0)
        past = now - relativedelta(months=amount)
        past = past.replace(hour=0, minute=0)
    elif interval_type == "year":
        now = now.replace(second=0, microsecond=0)
        past = now - relativedelta(years=amount)
        past = past.replace(hour=0, minute=0)        
    else:
        raise ValueError(f"Invalid interval type: {interval_type}. Choose from 'hour', 'day', 'week', 'month', 'year'.")

    return now, past

def shift_time(reftime, interval_type: str, amount: int = 1):
    """
    Shift time `amount` intervals relative to reftime
    Args:
        reftime (datetime): Reference time
        interval_type (str): One of ['hour', 'day', 'week', 'month', 'year']
        amount (int): Number of intervals to shift (positive = forward, negative = backward)
    Returns:
        shifted_datetime: The new datetime after the shift, capped at current time if shifting forward
    """
        
    if interval_type == "hour":
        newtime = reftime + timedelta(hours=amount)
    elif interval_type == "day":
        newtime = reftime + timedelta(days=amount)
    elif interval_type == "week":
        newtime = reftime + timedelta(weeks=amount)
    elif interval_type == "month":
        newtime = reftime + relativedelta(months=amount)
    elif interval_type == "year":
        newtime = reftime + relativedelta(years=amount)
    else:
        raise ValueError(f"Invalid interval type: {interval_type}. Choose from 'hour', 'day', 'week', 'month', 'year'.")
    
    newtime = newtime.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

    if amount > 0:
        now = datetime.now(timezone.utc)
        if newtime > now:
            return now
        else:
            return newtime
    else:
        return newtime


def convert_to_datetime(value):
    """Convert a string or other value to a date and time object, handling different formats.
    
    If only a date is provided, it defaults to 00:00:00 time.

    note that this returns a tuple of (date, time)
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
    elif isinstance(value,UTCDateTime):
        return value.date,value.time
    
    return date.today(), time(0, 0, 0)


def to_timestamp(time_obj: Union[int, float, datetime, date, UTCDateTime]) -> float:
    """
    Convert various time objects to Unix timestamp.

    Args:
        time_obj: Time object to convert. Can be one of:
            - int/float: Already a timestamp
            - datetime: Python datetime object
            - UTCDateTime: ObsPy UTCDateTime object

    Returns:
        float: Unix timestamp (seconds since epoch).

    Raises:
        ValueError: If the input time object type is not supported.

    Example:
        >>> ts = to_timestamp(datetime.now())
        >>> ts = to_timestamp(UTCDateTime())
        >>> ts = to_timestamp(1234567890.0)
    """
    if isinstance(time_obj, (int, float)):
        return float(time_obj)
    elif isinstance(time_obj, datetime):
        return time_obj.timestamp()
    elif isinstance(time_obj, UTCDateTime):
        return time_obj.timestamp
    elif isinstance(time_obj, date):
        dt = datetime.combine(time_obj, datetime.min.time())
        return dt.timestamp()
    else:
        raise ValueError(f"Unsupported time type: {type(time_obj)}")


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

def get_sds_filenames(
    n: str,
    s: str,
    l: str,
    c: str,
    time_start: UTCDateTime,
    time_end: UTCDateTime,
    sds_path: str
) -> List[str]:
    """Generate SDS (SeisComP Data Structure) format filenames for a time range.

    Creates a list of daily SDS format filenames for given network, station,
    location, and channel codes over a specified time period.

    Args:
        n: Network code.
        s: Station code.
        l: Location code.
        c: Channel code.
        time_start: Start time for data requests.
        time_end: End time for data requests.
        sds_path: Root path of the SDS archive.

    Returns:
        List of SDS format filepaths in the form:
        /sds_path/YEAR/NETWORK/STATION/CHANNEL.D/NET.STA.LOC.CHA.D.YEAR.DOY

    Example:
        >>> paths = get_sds_filenames(
        ...     "IU", "ANMO", "00", "BHZ",
        ...     UTCDateTime("2020-01-01"),
        ...     UTCDateTime("2020-01-03"),
        ...     "/data/seismic"
        ... )
    """
    current_time = time_start
    filenames = []
    
    while current_time <= time_end:
        year = str(current_time.year)
        doy = str(current_time.julday).zfill(3)
        
        path = f"{sds_path}/{year}/{n}/{s}/{c}.D/{n}.{s}.{l}.{c}.D.{year}.{doy}"
        filenames.append(path)
        
        current_time += 86400  # Advance by one day in seconds
    
    return filenames

# not sure if used anymore.. also a feature of filter_catalog_by_geo_constraints
def remove_duplicate_events(catalog):
    """
    Remove duplicate events from an ObsPy Catalog based on resource IDs.

    Takes a catalog of earthquake events and returns a new catalog containing only
    unique events, where uniqueness is determined by the event's resource_id.
    The first occurrence of each resource_id is kept.

    Args:
        catalog (obspy.core.event.Catalog): Input catalog containing earthquake events

    Returns:
        obspy.core.event.Catalog: New catalog containing only unique events

    Examples:
        >>> from obspy import read_events
        >>> cat = read_events('events.xml')
        >>> unique_cat = remove_duplicate_events(cat)
        >>> print(f"Removed {len(cat) - len(unique_cat)} duplicate events")
    """
    out = Catalog()
    eq_ids = set()

    for event in catalog:
        if event.resource_id not in eq_ids:
            out.append(event)
            eq_ids.add(event.resource_id)

    return out

def filter_catalog_by_geo_constraints(catalog: Catalog, constraints) -> Catalog:
    """
    Filter an ObsPy event catalog to include events within ANY of original search constraints. 
    This should be done to clean up any superfluous events that our reducted get_event calls
    may have introduced.
    
    Parameters:
    -----------
    catalog : obspy.core.event.Catalog
        The input event catalog to filter
    constraints: settings.event.geo_constraint (whatever object type this is TODO)
        
    Returns:
    --------
    obspy.core.event.Catalog
        A new catalog containing events within any of the specified circles
    """
    if len(constraints) == 0:
        return catalog

    filtered_events = []

    for event in catalog:

        # Filter out duplicates while we're here
        if event in filtered_events:
            continue

        try:
            event_lat = event.origins[0].latitude
            event_lon = event.origins[0].longitude
        except (IndexError, AttributeError):
            continue

        for geo in constraints:
            if geo.geo_type == GeoConstraintType.BOUNDING:

                # Check latitude first since it's simpler
                if not (geo.coords.min_lat <= event_lat <= geo.coords.max_lat):
                    continue
                    
                # Handle longitude, accounting for meridian crossing
                lon_in_bounds = False
                if geo.coords.min_lon <= geo.coords.max_lon:
                    # Normal case: box doesn't cross meridian
                    lon_in_bounds = geo.coords.min_lon <= event_lon <= geo.coords.max_lon
                else:
                    # Box crosses meridian - event must be either:
                    # 1) Greater than min_lon (e.g., 170 to 180) or
                    # 2) Less than max_lon (e.g., -180 to -170)
                    lon_in_bounds = event_lon >= geo.coords.min_lon or event_lon <= geo.coords.max_lon
                
                if lon_in_bounds:
                    filtered_events.append(event)
                    break

            elif geo.geo_type == GeoConstraintType.CIRCLE:

                if not geo.coords.max_radius:
                    geo.coords.max_radius = 180
                if not geo.coords.min_radius:
                    geo.coords.min_radius = 0

                distance = locations2degrees(event_lat, event_lon, geo.coords.lat, geo.coords.lon)
                    
                if geo.coords.min_radius <= distance <= geo.coords.max_radius:
                    filtered_events.append(event)
                    break
            else:
                filtered_events.append(event)

    return Catalog(events=filtered_events)

def filter_inventory_by_geo_constraints(inventory: Inventory, constraints) -> Inventory:
    """
    Filter an ObsPy inventory to include stations within ANY of the original search constraints.
    
    Parameters:
    -----------
    inventory : obspy.Inventory
        The input inventory to filter
    constraints: settings.event.geo_constraint
        List of geographical constraints
        
    Returns:
    --------
    obspy.Inventory
        A new inventory containing only stations within any of the specified constraints
    """
    if len(constraints) == 0:
        return inventory

    if len(inventory) == 0:
        return None

    # Create new networks list for filtered inventory
    networks = []
    
    for network in inventory:
        # Create new stations list for this network
        filtered_stations = []
        
        for station in network:

            # Filter out duplicates while we're here
            if station in filtered_stations:
                continue

            station_lat = station.latitude
            station_lon = station.longitude
            
            # Check each constraint
            for geo in constraints:
                if geo.geo_type == GeoConstraintType.BOUNDING:
                    # Check latitude first
                    if not (geo.coords.min_lat <= station_lat <= geo.coords.max_lat):
                        continue
                        
                    # Handle longitude, accounting for meridian crossing
                    lon_in_bounds = False
                    if geo.coords.min_lon <= geo.coords.max_lon:
                        # Normal case: box doesn't cross meridian
                        lon_in_bounds = geo.coords.min_lon <= station_lon <= geo.coords.max_lon
                    else:
                        # Box crosses meridian
                        lon_in_bounds = station_lon >= geo.coords.min_lon or station_lon <= geo.coords.max_lon
                    
                    if lon_in_bounds:
                        filtered_stations.append(station)
                        break  # Found a matching constraint, no need to check others
                        
                elif geo.geo_type == GeoConstraintType.CIRCLE:
                    if not geo.coords.max_radius:
                        geo.coords.max_radius = 180
                    if not geo.coords.min_radius:
                        geo.coords.min_radius = 0
                        
                    distance = locations2degrees(station_lat, station_lon, 
                                              geo.coords.lat, geo.coords.lon)
                        
                    if geo.coords.min_radius <= distance <= geo.coords.max_radius:
                        filtered_stations.append(station)
                        break
                        
                else:
                    filtered_stations.append(station)
        
        # If we found any stations in this network, add the network to our result
        if filtered_stations:
            # Create a copy of the network with only the filtered stations
            filtered_network = network.copy()
            filtered_network.stations = filtered_stations
            networks.append(filtered_network)
    
    # Create new inventory with only the networks that had matching stations
    return Inventory(networks=networks, source=inventory.source, sender=inventory.sender)


def format_error(station, error):
    indent = " " * 13
    border = indent + "-" * 74
    
    # Format the error message
    error_lines = str(error).split('\n')
    formatted_error = "\n".join(f"{indent}{line}" for line in error_lines)
    
    return f"\n{indent}Station {station} Error:\n{formatted_error}\n"