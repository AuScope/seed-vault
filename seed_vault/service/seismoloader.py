"""
The main functions for SEED-vault, from original CLI-only version (Pickle 2024)

"""

import os
import sys
import copy
import time
import sqlite3
import datetime
import multiprocessing
import configparser
import pandas as pd
import numpy as np
from tqdm import tqdm
import threading
import random
from typing import Any, Dict, List, Tuple, Optional, Union
from collections import defaultdict
import fnmatch

import obspy
from obspy import UTCDateTime
from obspy.clients.fdsn import Client
from obspy.taup import TauPyModel
from obspy.core.inventory import Inventory
from obspy.core.event import Event,Catalog
from obspy.geodetics.base import locations2degrees,gps2dist_azimuth

from seed_vault.models.config import SeismoLoaderSettings, SeismoQuery
from seed_vault.enums.config import DownloadType, GeoConstraintType
from seed_vault.service.utils import is_in_enum
from seed_vault.service.db import DatabaseManager
from seed_vault.service.waveform import get_local_waveform, stream_to_dataframe
from obspy.clients.fdsn.header import URL_MAPPINGS, FDSNNoDataException


class CustomConfigParser(configparser.ConfigParser):
    """
    Custom configuration parser that can preserve case sensitivity for specified sections.

    This class extends the standard ConfigParser to allow certain sections to maintain
    case sensitivity while others are converted to lowercase.

    Attributes:
        case_sensitive_sections (set): Set of section names that should preserve case sensitivity.
    """

    def __init__(self, *args, **kwargs):
        """
        Initialize the CustomConfigParser.

        Args:
            *args: Variable length argument list passed to ConfigParser.
            **kwargs: Arbitrary keyword arguments passed to ConfigParser.
        """
        self.case_sensitive_sections = set()
        super().__init__(*args, **kwargs)

    def optionxform(self, optionstr: str) -> str:
        """
        Transform option names during parsing.

        Overrides the default behavior to preserve the original string case.

        Args:
            optionstr: The option string to transform.

        Returns:
            str: The original string unchanged.
        """
        return optionstr


def read_config(config_file: str) -> CustomConfigParser:
    """
    Read and process a configuration file with case-sensitive handling for specific sections.

    Reads a configuration file and processes it such that certain sections
    (AUTH, DATABASE, SDS, WAVEFORM) preserve their case sensitivity while
    other sections are converted to lowercase.

    Args:
        config_file: Path to the configuration file to read.

    Returns:
        CustomConfigParser: Processed configuration with appropriate case handling
            for different sections.

    Example:
        >>> config = read_config("config.ini")
        >>> auth_value = config.get("AUTH", "ApiKey")  # Case preserved
        >>> other_value = config.get("settings", "parameter")  # Converted to lowercase
    """
    config = CustomConfigParser(allow_no_value=True)
    config.read(config_file)
    
    processed_config = CustomConfigParser(allow_no_value=True)
    
    for section in config.sections():
        processed_config.add_section(section)
        for key, value in config.items(section):
            if section.upper() in ['AUTH', 'DATABASE', 'SDS', 'WAVEFORM']:
                processed_key = key
                processed_value = value if value is not None else None
            else:
                processed_key = key.lower()
                processed_value = value.lower() if value is not None else None
            
            processed_config.set(section, processed_key, processed_value)

    return processed_config


def to_timestamp(time_obj: Union[int, float, datetime.datetime, UTCDateTime]) -> float:
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
        >>> ts = to_timestamp(datetime.datetime.now())
        >>> ts = to_timestamp(UTCDateTime())
        >>> ts = to_timestamp(1234567890.0)
    """
    if isinstance(time_obj, (int, float)):
        return float(time_obj)
    elif isinstance(time_obj, datetime.datetime):
        return time_obj.timestamp()
    elif isinstance(time_obj, UTCDateTime):
        return time_obj.timestamp
    else:
        raise ValueError(f"Unsupported time type: {type(time_obj)}")


def miniseed_to_db_element(file_path: str) -> Optional[Tuple[str, str, str, str, str, str]]:
    """
    Convert a miniseed file to a database element tuple.

    Processes a miniseed file and extracts relevant metadata for database storage.
    Expects files in the format: network.station.location.channel.*.year.julday

    Args:
        file_path: Path to the miniseed file.

    Returns:
        Optional[Tuple[str, str, str, str, str, str]]: A tuple containing:
            - network: Network code
            - station: Station code
            - location: Location code
            - channel: Channel code
            - start_time: ISO format start time
            - end_time: ISO format end time
            Returns None if file is invalid or cannot be processed.

    Example:
        >>> element = miniseed_to_db_element("/path/to/IU.ANMO.00.BHZ.D.2020.001")
        >>> if element:
        ...     network, station, location, channel, start, end = element
    """
    if not os.path.isfile(file_path):
        return None
    try:
        file = os.path.basename(file_path)
        parts = file.split('.')
        if len(parts) != 7:
            return None  # Skip files that don't match expected format
        
        network, station, location, channel, _, year, dayfolder = parts
        
        # Read the file to get actual start and end times
        st = obspy.read(file_path, headonly=True)
        
        if len(st) == 0:
            print(f"Warning: No traces found in {file_path}")
            return None
        
        start_time = min(tr.stats.starttime for tr in st)
        end_time = max(tr.stats.endtime for tr in st)
        
        return (network, station, location, channel,
                start_time.isoformat(), end_time.isoformat())
    
    except Exception as e:
        print(f"Error processing file {file_path}: {str(e)}")
        return None


def stream_to_db_element(st: obspy.Stream) -> Optional[Tuple[str, str, str, str, str, str]]:
    """
    Convert an ObsPy Stream object to a database element tuple.

    Creates a database element from a stream, assuming all traces have the same
    Network-Station-Location-Channel (NSLC) codes. This is typically faster than
    reading from a file using miniseed_to_db_element.

    Args:
        st: ObsPy Stream object containing seismic traces.

    Returns:
        Optional[Tuple[str, str, str, str, str, str]]: A tuple containing:
            - network: Network code
            - station: Station code
            - location: Location code
            - channel: Channel code
            - start_time: ISO format start time
            - end_time: ISO format end time
            Returns None if stream is empty.

    Example:
        >>> stream = obspy.read()
        >>> element = stream_to_db_element(stream)
        >>> if element:
        ...     network, station, location, channel, start, end = element
    """
    if len(st) == 0:
        print("Warning: Empty stream provided")
        return None
        
    start_time = min(tr.stats.starttime for tr in st)
    end_time = max(tr.stats.endtime for tr in st)
        
    return (st[0].stats.network, st[0].stats.station,
            st[0].stats.location, st[0].stats.channel,
            start_time.isoformat(), end_time.isoformat())


def populate_database_from_sds(sds_path, db_path,
    search_patterns=["??.*.*.???.?.????.???"],
    newer_than=None, num_processes=None, gap_tolerance = 60):

    """
    Scan an SDS archive directory and populate a database with data availability.

    Recursively searches an SDS (Seismic Data Structure) archive for MiniSEED files,
    extracts their metadata, and records data availability in a SQLite database.
    Supports parallel processing and can optionally filter for recently modified files.

    Args:
        sds_path (str): Path to the root SDS archive directory
        db_path (str): Path to the SQLite database file
        search_patterns (list, optional): List of file patterns to match.
            Defaults to ["??.*.*.???.?.????.???"] (standard SDS naming pattern).
        newer_than (str or UTCDateTime, optional): Only process files modified after
            this time. Defaults to None (process all files).
        num_processes (int, optional): Number of parallel processes to use.
            Defaults to None (use all available CPU cores).
        gap_tolerance (int, optional): Maximum time gap in seconds between segments
            that should be considered continuous. Defaults to 60.

    Notes:
        - Uses DatabaseManager class to handle database operations
        - Attempts multiprocessing but falls back to single process if it fails
            (common on OSX and Windows)
        - Follows symbolic links when walking directory tree
        - Files are processed using miniseed_to_db_element() function
        - After insertion, continuous segments are joined based on gap_tolerance
        - Progress is displayed using tqdm progress bars
        - If newer_than is provided, it's converted to a Unix timestamp for comparison

    Raises:
        RuntimeError: If bulk insertion into database fails
    """

    db_manager = DatabaseManager(db_path)

    # Set to possibly the maximum number of CPUs!
    if num_processes is None or num_processes <= 0:
        num_processes = multiprocessing.cpu_count()
    
    # Convert newer_than (means to filter only new files) to timestamp
    if newer_than:
        newer_than = to_timestamp(newer_than)

    # Collect all file paths
    file_paths = []

    for root, dirs, files in os.walk(sds_path,followlinks=True):
        for f in files:
            if any(fnmatch.fnmatch(f, pattern) for pattern in search_patterns):
                file_path = os.path.join(root,f)
                if newer_than is None or os.path.getmtime(file_path) > newer_than:
                    file_paths.append(os.path.join(root, f))
    
    total_files = len(file_paths)
    print(f"Found {total_files} files to process.")
    
    # Process files with or without multiprocessing
    # TODO (currently having issues with OSX and undoubtably windows is going to be a bigger problem)
    if num_processes > 1:
        try:
            with multiprocessing.Pool(processes=num_processes) as pool:
                to_insert_db = list(tqdm(pool.imap(miniseed_to_db_element, file_paths), \
                    total=total_files, desc="Processing files"))
        except Exception as e:
            print(f"Multiprocessing failed: {str(e)}. Falling back to single-process execution.")
            num_processes = 1
    else:
        to_insert_db = []
        for fp in tqdm(file_paths, desc="Scanning %s..." % sds_path):
            to_insert_db.append(miniseed_to_db_element(fp))

    # Update database
    try:
        num_inserted = db_manager.bulk_insert_archive_data(to_insert_db)
    except Exception as e:
        raise RuntimeError("Error with bulk_insert_archive_data") from e  

    print(f"Processed {total_files} files, inserted {num_inserted} records into the database.")

    db_manager.join_continuous_segments(gap_tolerance)

 
def populate_database_from_files_dumb(cursor, file_paths=[]):
    """
    Simple version of database population from MiniSEED files without span merging.

    A simplified "dumb" version that blindly replaces existing database entries
    with identical network/station/location/channel codes, rather than checking for
    and merging overlapping time spans.

    Args:
        cursor (sqlite3.Cursor): Database cursor for executing SQL commands
        file_paths (list, optional): List of paths to MiniSeed files. Defaults to empty list.
    """
    now = int(datetime.datetime.now().timestamp())
    for fp in file_paths:
        result  = miniseed_to_db_element(fp)
        if result:
            result = result + (now,)
            cursor.execute('''
                INSERT OR REPLACE INTO archive_data
                (network, station, location, channel, starttime, endtime, importtime)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', result)


def populate_database_from_files(cursor, file_paths=[]):
    """
    Insert or update MiniSEED file metadata into an SQL database.

    Takes a list of SDS archive file paths, extracts metadata, and updates a database
    tracking data availability. If data spans overlap with existing database entries,
    the spans are merged. Uses miniseed_to_db_element() to parse file metadata.

    Args:
        cursor (sqlite3.Cursor): Database cursor for executing SQL commands
        file_paths (list, optional): List of paths to MiniSeed files. Defaults to empty list.

    Notes:
        - Database must have an 'archive_data' table with columns:
            * network (text)
            * station (text)
            * location (text)
            * channel (text)
            * starttime (integer): Unix timestamp
            * endtime (integer): Unix timestamp
            * importtime (integer): Unix timestamp of database insertion
        - Handles overlapping time spans by merging them into a single entry
        - Sets importtime to current Unix timestamp
        - Skips files that fail metadata extraction (when miniseed_to_db_element returns None)

    Examples:
        >>> import sqlite3
        >>> conn = sqlite3.connect('archive.db')
        >>> cursor = conn.cursor()
        >>> files = ['/path/to/IU.ANMO.00.BHZ.mseed', '/path/to/IU.ANMO.00.BHN.mseed']
        >>> populate_database_from_files(cursor, files)
        >>> conn.commit()
    """
    now = int(datetime.datetime.now().timestamp())
    for fp in file_paths:
        result = miniseed_to_db_element(fp)
        if result:
            network, station, location, channel, start_timestamp, end_timestamp = result
            
            # First check for existing overlapping spans
            cursor.execute('''
                SELECT starttime, endtime FROM archive_data
                WHERE network = ? AND station = ? AND location = ? AND channel = ?
                AND NOT (endtime < ? OR starttime > ?)
            ''', (network, station, location, channel, start_timestamp, end_timestamp))
            
            overlaps = cursor.fetchall()
            if overlaps:
                # Merge with existing spans
                start_timestamp = min(start_timestamp, min(row[0] for row in overlaps))
                end_timestamp = max(end_timestamp, max(row[1] for row in overlaps))
                
                # Delete overlapping spans
                cursor.execute('''
                    DELETE FROM archive_data
                    WHERE network = ? AND station = ? AND location = ? AND channel = ?
                    AND NOT (endtime < ? OR starttime > ?)
                ''', (network, station, location, channel, start_timestamp, end_timestamp))
            
            # Insert the new or merged span
            cursor.execute('''
                INSERT INTO archive_data
                (network, station, location, channel, starttime, endtime, importtime)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (network, station, location, channel, start_timestamp, end_timestamp, now))


def collect_requests(inv, time0, time1, days_per_request=3, 
                     cha_pref=None, loc_pref=None):
    """
    Generate time-windowed data requests for all channels in an inventory.

    Creates a list of data requests by breaking a time period into smaller windows
    and collecting station metadata for each window. Can optionally filter for
    preferred channels and location codes.

    Args:
        inv (obspy.core.inventory.Inventory): Station inventory to generate requests for
        time0 (obspy.UTCDateTime): Start time for data requests
        time1 (obspy.UTCDateTime): End time for data requests
        days_per_request (int, optional): Length of each request window in days. 
            Defaults to 3.
        cha_pref (list, optional): List of preferred channel codes in priority order.
            If provided, only these channels will be requested. Defaults to None.
        loc_pref (list, optional): List of preferred location codes in priority order.
            If provided, only these location codes will be requested. Defaults to None.

    Returns:
        list or None: List of tuples containing request parameters:
            (network_code, station_code, location_code, channel_code, 
             start_time_iso, end_time_iso)
            Returns None if start time is greater than or equal to end time.

    Notes:
        - End time is capped at 120 seconds before current time
        - Times in returned tuples are ISO formatted strings with 'Z' suffix
        - Uses get_preferred_channels() if cha_pref or loc_pref are specified

    Examples:
        >>> from obspy import UTCDateTime
        >>> t0 = UTCDateTime("2020-01-01")
        >>> t1 = UTCDateTime("2020-01-10")
        >>> requests = collect_requests(inventory, t0, t1, 
        ...                           days_per_request=2,
        ...                           cha_pref=['HHZ', 'BHZ'],
        ...                           loc_pref=['', '00'])
    """

    requests = []  # network, station, location, channel, starttime, endtime

    # Sanity check request times
    time1 = min(time1, UTCDateTime.now()-120)
    if time0 >= time1:
        return None
    sub_inv = inv.select(time=time0)
    current_start = time0
    while current_start < time1:
        current_end = min(current_start + datetime.timedelta(days=days_per_request), time1)
        
        if cha_pref or loc_pref:
            sub_inv = get_preferred_channels(inv, cha_pref, loc_pref, current_start)
        
        # Collect requests for the best channels
        for net in sub_inv:
            for sta in net:
                for cha in sta:
                    requests.append((
                        net.code,
                        sta.code,
                        cha.location_code,
                        cha.code,
                        current_start.isoformat() + "Z",
                        current_end.isoformat() + "Z" ))
        
        current_start = current_end
    
    return requests


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
    out = obspy.core.event.Catalog()
    eq_ids = set()

    for event in catalog:
        if event.resource_id not in eq_ids:
            out.append(event)
            eq_ids.add(event.resource_id)

    return out

def get_p_s_times(eq, dist_deg, ttmodel):
    """
    Calculate theoretical P and S wave arrival times for an earthquake at a given distance.

    Uses a travel time model to compute the first P and S wave arrivals for a given
    earthquake and distance. The first arrival (labeled as "P") may not necessarily be
    a direct P wave. For S waves, only phases explicitly labeled as 'S' are considered.

    Args:
        eq (obspy.core.event.Event): Earthquake event object containing origin time
            and depth information
        dist_deg (float): Distance between source and receiver in degrees
        ttmodel (obspy.taup.TauPyModel): Travel time model to use for calculations

    Returns:
        tuple: A tuple containing:
            - (UTCDateTime or None): Time of first arrival ("P" wave)
            - (UTCDateTime or None): Time of first S wave arrival
              Returns (None, None) if travel time calculation fails

    Notes:
        - Earthquake depth is expected in meters in the QuakeML format and is
          converted to kilometers for the travel time calculations
        - For S waves, only searches for explicit 'S' phase arrivals
        - Warns if no P arrival is found at any distance
        - Warns if no S arrival is found at distances ≤ 90 degrees

    Examples:
        >>> from obspy.taup import TauPyModel
        >>> model = TauPyModel(model="iasp91")
        >>> p_time, s_time = get_p_s_times(earthquake, 45.3, model)
    """

    eq_time = eq.origins[0].time
    eq_depth = eq.origins[0].depth / 1000  # depths are in meters for QuakeML

    try:
        phasearrivals = ttmodel.get_travel_times(
            source_depth_in_km=eq_depth,
            distance_in_degree=dist_deg,
            phase_list=['ttbasic']
        )
    except Exception as e:
        print(f"Error calculating travel times:\n {str(e)}")
        return None, None

    p_arrival_time = None
    s_arrival_time = None
    # "P" is whatever the first arrival is.. not necessarily literally uppercase P
    if phasearrivals[0]:
        p_arrival_time = eq_time + phasearrivals[0].time

    # Now get "S"...
    for arrival in phasearrivals:
        if arrival.name.upper() == 'S' and s_arrival_time is None:
            s_arrival_time = eq_time + arrival.time
        if p_arrival_time and s_arrival_time:
            break

    if p_arrival_time is None:
        print(f"No direct P-wave arrival found for distance {dist_deg} degrees")
    if s_arrival_time is None and dist_deg <= 90:
        print(f"No direct S-wave arrival found for distance {dist_deg} degrees (event {eq_time})")

    return p_arrival_time, s_arrival_time


def select_highest_samplerate(inv, minSR=10, time=None):
    """
    Filters an inventory to keep only the highest sample rate channels where duplicates exist.
    
    For each station in the inventory, this function identifies duplicate channels (those sharing
    the same location code) and keeps only those with the highest sample rate. Channels must
    meet the minimum sample rate requirement to be considered.

    Args:
        inv (obspy.core.inventory.Inventory): Input inventory object
        minSR (float, optional): Minimum sample rate in Hz. Defaults to 10.
        time (obspy.UTCDateTime, optional): Specific time to check channel existence.
            If provided, channels are considered duplicates if they share the same
            location code and both exist at that time. If None, channels are considered
            duplicates if they share the same location code and time span. Defaults to None.

    Returns:
        obspy.core.inventory.Inventory: Filtered inventory containing only the highest
            sample rate channels where duplicates existed.

    Examples:
        >>> # Filter inventory keeping only highest sample rate channels
        >>> filtered_inv = select_highest_samplerate(inv)
        >>> 
        >>> # Filter for a specific time, minimum 1 Hz
        >>> from obspy import UTCDateTime
        >>> time = UTCDateTime("2020-01-01")
        >>> filtered_inv = select_highest_samplerate(inv, minSR=1, time=time)

    Notes:
        - Channel duplicates are determined by location code and either:
          * Existence at a specific time (if time is provided)
          * Having identical time spans (if time is None)
        - All retained channels must have sample rates >= minSR
        - For duplicate channels, all channels with the highest sample rate are kept
    """
    if time:
        inv = inv.select(time=time)
    
    for net in inv:
        for sta in net:
            channels = [ch for ch in sta.channels if ch.sample_rate >= minSR]
            
            loc_groups = {}
            for channel in channels:
                loc_code = channel.location_code
                if loc_code not in loc_groups:
                    loc_groups[loc_code] = []
                loc_groups[loc_code].append(channel)
            
            filtered_channels = []
            for loc_group in loc_groups.values():
                if len(loc_group) == 1:
                    filtered_channels.extend(loc_group)
                    continue
                
                if time:
                    active_channels = [ch for ch in loc_group]
                    if active_channels:
                        max_sr = max(ch.sample_rate for ch in active_channels)
                        filtered_channels.extend([ch for ch in active_channels if ch.sample_rate == max_sr])
                else:
                    time_groups = {}
                    for channel in loc_group:
                        time_key = f"{channel.start_date}_{channel.end_date}"
                        if time_key not in time_groups:
                            time_groups[time_key] = []
                        time_groups[time_key].append(channel)
                    
                    for time_group in time_groups.values():
                        if len(time_group) > 1:
                            max_sr = max(ch.sample_rate for ch in time_group)
                            filtered_channels.extend([ch for ch in time_group if ch.sample_rate == max_sr])
                        else:
                            filtered_channels.extend(time_group)
            
            sta.channels = filtered_channels
    
    return inv


def get_preferred_channels(
    inv: Inventory,
    cha_rank: Optional[List[str]] = None,
    loc_rank: Optional[List[str]] = None,
    time: Optional[UTCDateTime] = None
) -> Inventory:
    """Select the best available channels from an FDSN inventory based on rankings.

    Filters an inventory to keep only the preferred channels based on channel code
    and location code rankings. For each component (Z, N, E), selects the channel
    with the highest ranking.

    Args:
        inv: ObsPy Inventory object to filter.
        cha_rank: List of channel codes in order of preference (e.g., ['BH', 'HH']).
            Lower index means higher preference.
        loc_rank: List of location codes in order of preference (e.g., ['', '00']).
            Lower index means higher preference. '--' is treated as empty string.
        time: Optional time to filter channel availability at that time.

    Returns:
        Filtered ObsPy Inventory containing only the preferred channels.
        If all channels would be filtered out, returns original station.

    Note:
        Channel preference takes precedence over location preference.
        If neither cha_rank nor loc_rank is provided, returns original inventory.

    Example:
        >>> inventory = client.get_stations(network="IU", station="ANMO")
        >>> cha_rank = ['BH', 'HH', 'EH']
        >>> loc_rank = ['00', '10', '']
        >>> filtered = get_preferred_channels(inventory, cha_rank, loc_rank)
    """
    if not cha_rank and not loc_rank:
        return inv

    # Convert '--' location codes to empty string
    if loc_rank:
        loc_rank = [lc if lc != '--' else '' for lc in loc_rank]

    new_inv = Inventory(networks=[], source=inv.source)

    if time:
        inv = inv.select(time=time)
    
    for net in inv:
        new_net = net.copy()
        new_net.stations = []
        
        for sta in net:
            new_sta = sta.copy()
            new_sta.channels = []
            
            # Group channels by component (e.g. Z, N, E, 1, 2)
            components = defaultdict(list)
            for chan in sta:
                comp = chan.code[-1]
                components[comp].append(chan)
            
            # Select best channel for each component
            for chan_list in components.values():
                best_chan = None
                best_cha_rank = float('inf')
                best_loc_rank = float('inf')
                
                for chan in chan_list:
                    if not chan.is_active(time):
                        continue
                    
                    cha_code = chan.code[:-1]
                    
                    # Get ranking positions
                    cha_position = len(cha_rank) if cha_rank is None else \
                        len(cha_rank) if cha_code not in cha_rank else cha_rank.index(cha_code)
                    loc_position = len(loc_rank) if loc_rank is None else \
                        len(loc_rank) if chan.location_code not in loc_rank else loc_rank.index(chan.location_code)
                    
                    # Update if better ranking found
                    if (cha_position < best_cha_rank or 
                        (cha_position == best_cha_rank and loc_position < best_loc_rank)):
                        best_chan = chan
                        best_cha_rank = cha_position
                        best_loc_rank = loc_position
                
                if best_chan is not None:
                    new_sta.channels.append(best_chan)
            
            # Keep original if no channels passed filtering
            if new_sta.channels:
                new_net.stations.append(new_sta)
            else:
                new_net.stations.append(sta)
        
        if new_net.stations:
            new_inv.networks.append(new_net)
    
    return new_inv


def collect_requests_event(
    eq: Event,
    inv: Inventory,
    model: Optional[TauPyModel] = None,
    settings: Optional[SeismoLoaderSettings] = None
) -> Tuple[List[Tuple[str, str, str, str, str, str]], 
           List[Tuple[Any, ...]], 
           Dict[str, float]]:
    """
    Collect data requests and arrival times for an event at multiple stations.

    For a given earthquake event, calculates arrival times and generates data
    requests for all appropriate stations in the inventory.

    Args:
        eq: ObsPy Event object containing earthquake information.
        inv: ObsPy Inventory object containing station information.
        model: Optional TauPyModel for travel time calculations.
            If None, uses model from settings or falls back to IASP91.
        settings: Optional SeismoLoaderSettings object containing configuration.

    Returns:
        Tuple containing:
            - List of request tuples (net, sta, loc, chan, start, end)
            - List of arrival data tuples for database
            - Dictionary mapping "net.sta" to P-arrival timestamps

    Note:
        Requires a DatabaseManager instance to check for existing arrivals.
        Time windows are constructed around P-wave arrivals using settings.
        Handles both new calculations and retrieving existing arrival times.

    Example:
        >>> event = client.get_events()[0]
        >>> inventory = client.get_stations(network="IU")
        >>> requests, arrivals, p_times = collect_requests_event(
        ...     event, inventory, model=TauPyModel("iasp91")
        ... )
    """
    settings, db_manager = setup_paths(settings)

    # Extract settings
    model_name = settings.event.model
    before_p_sec = settings.event.before_p_sec
    after_p_sec = settings.event.after_p_sec
    min_radius = settings.event.min_radius
    max_radius = settings.event.max_radius    
    highest_sr_only = settings.station.highest_samplerate_only
    cha_pref = settings.waveform.channel_pref
    loc_pref = settings.waveform.location_pref

    origin = eq.origins[0]
    ot = origin.time
    sub_inv = inv.select(time=ot)

    if highest_sr_only:
        sub_inv = select_highest_samplerate(sub_inv, minSR=5)
    
    if cha_pref or loc_pref:
        sub_inv = get_preferred_channels(sub_inv, cha_pref, loc_pref)

    # Ensure model is loaded
    if not model:
        try:
            model = TauPyModel(model_name.upper())
        except Exception:
            model = TauPyModel('IASP91')

    requests_per_eq = []
    arrivals_per_eq = []
    p_arrivals: Dict[str, float] = {}

    for net in sub_inv:
        for sta in net:
            # Get station timing info
            try:
                sta_start = sta.start_date.timestamp
                sta_end = sta.end_date.timestamp
            except Exception:
                sta_start = None
                sta_end = None

            # Check for existing arrivals
            fetched_arrivals = db_manager.fetch_arrivals_distances(
                str(eq.preferred_origin_id),
                net.code,
                sta.code
            )

            if fetched_arrivals:
                p_time, s_time, dist_km, dist_deg, azi = fetched_arrivals
                t_start = p_time - abs(before_p_sec)
                t_end = p_time + abs(after_p_sec)
                p_arrivals[f"{net.code}.{sta.code}"] = p_time
            else:
                # Calculate new arrivals
                dist_deg = locations2degrees(
                    origin.latitude, origin.longitude,
                    sta.latitude, sta.longitude
                )
                dist_m, azi, _ = gps2dist_azimuth(
                    origin.latitude, origin.longitude,
                    sta.latitude, sta.longitude
                )
                
                p_time, s_time = get_p_s_times(eq, dist_deg, model)
                if p_time is None:
                    print(f"Warning: Unable to calculate first arrival for {net.code}.{sta.code}")
                    continue

                t_start = (p_time - abs(before_p_sec)).timestamp
                t_end = (p_time + abs(after_p_sec)).timestamp
                p_arrivals[f"{net.code}.{sta.code}"] = p_time.timestamp

                # save these new arrivals to insert into database
                arrivals_per_eq.append((
                    str(eq.preferred_origin_id),
                    eq.magnitudes[0].mag,
                    origin.latitude, origin.longitude, origin.depth/1000,
                    ot.timestamp,
                    net.code, sta.code, sta.latitude, sta.longitude, sta.elevation/1000,
                    sta_start, sta_end,
                    dist_deg, dist_m/1000, azi, p_time.timestamp,
                    s_time.timestamp if s_time else None,
                    model_name
                ))

            # skip anything out of our search parameters
            if dist_deg < min_radius:
                print(f"    Skipping {net.code}.{sta.code}  (distance {dist_deg:.1f} < min_radius {min_radius:.1f})")
                continue
            elif dist_deg > max_radius:
                print(f"    Skipping {net.code}.{sta.code}  (distance {dist_deg:.1f} > max_radius {max_radius:.1f})")
                continue
            else:
                # Generate requests for each channel
                for cha in sta:
                    t_end = min(t_end, datetime.datetime.now().timestamp() - 120)
                    t_start = min(t_start, t_end)
                    requests_per_eq.append((
                        net.code,
                        sta.code,
                        cha.location_code,
                        cha.code,
                        datetime.datetime.fromtimestamp(t_start, tz=datetime.timezone.utc).isoformat(),
                        datetime.datetime.fromtimestamp(t_end, tz=datetime.timezone.utc).isoformat()
                    ))

    return requests_per_eq, arrivals_per_eq, p_arrivals


def combine_requests(
    requests: List[Tuple[str, str, str, str, str, str]]
) -> List[Tuple[str, str, str, str, str, str]]:
    """
    Combine multiple data requests for efficiency.

    Groups requests by network and time range, combining stations, locations,
    and channels into comma-separated lists to minimize the number of requests.

    Args:
        requests: List of request tuples, each containing:
            (network, station, location, channel, start_time, end_time)

    Returns:
        List of combined request tuples with the same structure but with
        station, location, and channel fields potentially containing
        comma-separated lists.

    Example:
        >>> original = [
        ...     ("IU", "ANMO", "00", "BHZ", "2020-01-01", "2020-01-02"),
        ...     ("IU", "COLA", "00", "BHZ", "2020-01-01", "2020-01-02")
        ... ]
        >>> combined = combine_requests(original)
        >>> print(combined)
        [("IU", "ANMO,COLA", "00", "BHZ", "2020-01-01", "2020-01-02")]
    """
    # Group requests by network and time range
    groups = defaultdict(list)
    for net, sta, loc, chan, t0, t1 in requests:
        groups[(net, t0, t1)].append((sta, loc, chan))
    
    # Combine requests within each group
    combined_requests = []
    for (net, t0, t1), items in groups.items():
        # Collect unique values
        stas = set(sta for sta, _, _ in items)
        locs = set(loc for _, loc, _ in items)
        chans = set(chan for _, _, chan in items)
        
        # Create combined request
        combined_requests.append((
            net,
            ','.join(sorted(stas)),
            ','.join(sorted(locs)),
            ','.join(sorted(chans)),
            t0,
            t1
        ))
    
    return combined_requests


def get_missing_from_request(eq_id: str, requests: List[Tuple], st: obspy.Stream) -> dict:
    """
    Compare requested seismic data against what's present in a Stream.
    Handles comma-separated values for location and channel codes.
    
    Parameters:
    -----------
    eq_id : str
        Earthquake ID to use as dictionary key
    requests : List[Tuple]
        List of request tuples, each containing (network, station, location, channel, starttime, endtime)
    st : Stream
        ObsPy Stream object containing seismic traces
        
    Returns:
    --------
    dict
        Nested dictionary with structure:
        {eq_id: {
            "network.station": value,
            "network2.station2": value2,
            ...
        }}
        where value is either:
        - list of missing channel strings ("network.station.location.channel")
        - "Not Attempted" if stream is empty
        - "ALL" if all requested channels are missing
        - [] if all requested channels are present
    """
    if not requests:
        return {}
    
    result = {eq_id: {}}
    
    # Process each request
    for request in requests:
        net, sta, loc, cha, _, _ = request  # Ignore time windows
        station_key = f"{net}.{sta}"
        
        # Split location and channel if comma-separated
        locations = loc.split(',') if ',' in loc else [loc]
        channels = cha.split(',') if ',' in cha else [cha]
        
        missing_channels = []
        total_combinations = 0
        missing_combinations = 0
        
        # Check all combinations
        for location in locations:
            for channel in channels:
                total_combinations += 1
                # Look for matching trace
                found_match = False
                for tr in st:
                    if (tr.stats.network == net and 
                        tr.stats.station == sta and
                        tr.stats.location == (location if location else '') and
                        fnmatch.fnmatch(tr.stats.channel, channel)):
                        found_match = True
                        break
                
                if not found_match:
                    missing_combinations += 1
                    missing_channels.append(
                        f"{net}.{sta}.{location}.{channel}"
                    )
        
        # Determine value for this station
        if missing_combinations == total_combinations:  # nothing returned
            result[eq_id][station_key] = "ALL"
        elif missing_combinations == 0:  # everything returned
            result[eq_id][station_key] = []
        else:  # partial return
            result[eq_id][station_key] = missing_channels
    
    return result

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


def prune_requests(
    requests: List[Tuple[str, str, str, str, str, str]],
    db_manager: DatabaseManager,
    sds_path: str,
    min_request_window: float = 3
) -> List[Tuple[str, str, str, str, str, str]]:
    """
    Remove overlapping requests where data already exists in the archive.

    Checks both the database and filesystem for existing data and removes or
    splits requests to avoid re-downloading data that's already available.

    Args:
        requests: List of request tuples containing:
            (network, station, location, channel, start_time, end_time)
        db_manager: DatabaseManager instance for querying existing data.
        sds_path: Root path of the SDS archive.
        min_request_window: Minimum time window in seconds to keep a request.
            Requests shorter than this are discarded.

    Returns:
        List of pruned request tuples, sorted by start time, network, and station.

    Note:
        This function will update the database if it finds files in the SDS
        structure that aren't yet recorded in the database.

    Example:
        >>> requests = [("IU", "ANMO", "00", "BHZ", "2020-01-01", "2020-01-02")]
        >>> pruned = prune_requests(requests, db_manager, "/data/seismic")
    """
    pruned_requests = []
    
    with db_manager.connection() as conn:
        cursor = conn.cursor()
        
        for req in requests:
            network, station, location, channel, start_time, end_time = req
            start_time = UTCDateTime(start_time)
            end_time = UTCDateTime(end_time)

            # Check filesystem for existing files
            existing_filenames = get_sds_filenames(
                network, station, location, channel,
                start_time, end_time, sds_path
            )
            
            # Query database for existing data
            cursor.execute('''
                SELECT starttime, endtime FROM archive_data
                WHERE network = ? AND station = ? AND location = ? AND channel = ?
                AND endtime >= ? AND starttime <= ?
                ORDER BY starttime
            ''', (network, station, location, channel,
                 start_time.isoformat(), end_time.isoformat()))
            
            existing_data = cursor.fetchall()

            # Update database if files exist but aren't recorded
            if existing_filenames and len(existing_data) < len(existing_filenames):
                populate_database_from_files(cursor, file_paths=existing_filenames)
                
                cursor.execute('''
                    SELECT starttime, endtime FROM archive_data
                    WHERE network = ? AND station = ? AND location = ? AND channel = ?
                    AND endtime >= ? AND starttime <= ?
                    ORDER BY starttime
                ''', (network, station, location, channel,
                     start_time.isoformat(), end_time.isoformat()))
                
                existing_data = cursor.fetchall()
            
            if not existing_data and not existing_filenames:
                # Keep entire request if no existing data found
                pruned_requests.append(req)
            else:
                # Process gaps in existing data
                current_time = start_time
                for db_start, db_end in existing_data:
                    db_start = UTCDateTime(db_start)
                    db_end = UTCDateTime(db_end)
                    
                    if current_time < db_start - min_request_window:
                        # Add request for gap before existing data
                        pruned_requests.append((
                            network, station, location, channel,
                            current_time.isoformat(),
                            db_start.isoformat()
                        ))
                    
                    current_time = max(current_time, db_end)
                
                if current_time < end_time - min_request_window:
                    # Add request for gap after last existing data
                    pruned_requests.append((
                        network, station, location, channel,
                        current_time.isoformat(),
                        end_time.isoformat()
                    ))

    # Sort by start time, network, station
    pruned_requests.sort(key=lambda x: (x[4], x[0], x[1]))
    return pruned_requests


def archive_request(
    request: Tuple[str, str, str, str, str, str],
    waveform_clients: Dict[str, Client],
    sds_path: str,
    db_manager: DatabaseManager
) -> None:
    """
    Download seismic data for a request and archive it in SDS format.

    Retrieves waveform data from FDSN web services, saves it in SDS format,
    and updates the database. Handles authentication, data merging, and
    various error conditions.

    Args:
        request: Tuple containing (network, station, location, channel,
            start_time, end_time)
        waveform_clients: Dictionary mapping network codes to FDSN clients.
            Special key 'open' is used for default client.
        sds_path: Root path of the SDS archive.
        db_manager: DatabaseManager instance for updating the database.

    Note:
        - Supports per-network and per-station authentication
        - Handles splitting of large station list requests
        - Performs data merging when files already exist
        - Attempts STEIM2 compression, falls back to uncompressed format
        - Groups traces by day to handle fragmented data efficiently

    Example:
        >>> clients = {'IU': Client('IRIS'), 'open': Client('IRIS')}
        >>> request = ("IU", "ANMO", "00", "BHZ", "2020-01-01", "2020-01-02")
        >>> archive_request(request, clients, "/data/seismic", db_manager)
    """
    try:
        time0 = time.time()
        
        # Select appropriate client
        if request[0] in waveform_clients:
            wc = waveform_clients[request[0]]
        elif request[0] + '.' + request[1] in waveform_clients:
            wc = waveform_clients[request[0] + '.' + request[1]]
        else:
            wc = waveform_clients['open']

        kwargs = {
            'network': request[0].upper(),
            'station': request[1].upper(),
            'location': request[2].upper(),
            'channel': request[3].upper(),
            'starttime': UTCDateTime(request[4]),
            'endtime': UTCDateTime(request[5])
        }

        # Handle long station lists
        if len(request[1]) > 24:
            st = obspy.Stream()
            split_stations = request[1].split(',')
            for s in split_stations:
                try:
                    st += wc.get_waveforms(
                        station=s,
                        **{k: v for k, v in kwargs.items() if k != 'station'}
                    )
                except Exception as e:
                    if 'code: 204' in str(e):
                        print(f"\n        No data for station {s}")
                    else:
                        print(f"Unusual error fetching data for station {s}:\n {str(e)}")
        else:
            st = wc.get_waveforms(**kwargs)

        # Log download statistics
        download_time = time.time() - time0
        download_size = sum(tr.data.nbytes for tr in st) / 1024**2  # MB
        print(f"      > Downloaded {download_size:.2f} MB @ {download_size/download_time:.2f} MB/s")

    except Exception as e:
        if 'code: 204' in str(e):
            print(f"      ~ No data available")
        else:
            print(f"{str(e)}")
        return

    # Group traces by day
    traces_by_day = defaultdict(obspy.Stream)
    
    for tr in st:
        net = tr.stats.network
        sta = tr.stats.station
        loc = tr.stats.location
        cha = tr.stats.channel
        starttime = tr.stats.starttime
        endtime = tr.stats.endtime

        # Handle trace start leaking into previous day
        day_boundary = UTCDateTime(starttime.date + datetime.timedelta(days=1))
        if (day_boundary - starttime) <= tr.stats.delta:
            starttime = day_boundary
        
        current_time = UTCDateTime(starttime.date)
        while current_time < endtime:
            year = current_time.year
            doy = current_time.julday
            
            next_day = current_time + 86400
            day_end = min(next_day - tr.stats.delta, endtime)
            
            day_tr = tr.slice(current_time, day_end, nearest_sample=True)
            day_key = (year, doy, net, sta, loc, cha)
            traces_by_day[day_key] += day_tr
            
            current_time = next_day

    # Process each day's data
    to_insert_db = []
    for (year, doy, net, sta, loc, cha), day_stream in traces_by_day.items():
        full_sds_path = os.path.join(sds_path, str(year), net, sta, f"{cha}.D")
        filename = f"{net}.{sta}.{loc}.{cha}.D.{year}.{doy:03d}"
        full_path = os.path.join(full_sds_path, filename)
        
        os.makedirs(full_sds_path, exist_ok=True)
        
        if os.path.exists(full_path):
            try:
                existing_st = obspy.read(full_path)
                existing_st += day_stream
                existing_st.merge(method=-1, fill_value=None)
                existing_st._cleanup(misalignment_threshold=0.25)
                if existing_st:
                    print(f"  ... Merging {full_path}")
            except Exception as e:
                print(f"! Could not read {full_path}:\n {e}")
                continue
        else:
            existing_st = day_stream
            if existing_st:
                print(f"  ... Writing {full_path}")

        existing_st = obspy.Stream([tr for tr in existing_st if len(tr.data) > 0])

        if existing_st:
            try:
                # Try STEIM2 compression first
                existing_st.write(full_path, format="MSEED", encoding='STEIM2')
                to_insert_db.append(stream_to_db_element(existing_st))
            except Exception as e:
                if "Wrong dtype" in str(e):
                    # Fall back to uncompressed format
                    print("Data type not compatible with STEIM2, attempting uncompressed format...")
                    try:
                        existing_st.write(full_path, format="MSEED")
                        to_insert_db.append(stream_to_db_element(existing_st))
                    except Exception as e:
                        print(f"Failed to write uncompressed MSEED to {full_path}:\n {e}")
                else:
                    print(f"Failed to write {full_path}:\n {e}")

    # Update database
    try:
        num_inserted = db_manager.bulk_insert_archive_data(to_insert_db)
    except Exception as e:
        print("! Error with bulk_insert_archive_data:", e)


# MAIN RUN FUNCTIONS
# ==================================================================

def setup_paths(settings: SeismoLoaderSettings) -> Tuple[SeismoLoaderSettings, DatabaseManager]:
    """Initialize paths and database for seismic data management.

    Args:
        settings: Configuration settings containing paths and database information.

    Returns:
        Tuple containing:
            - Updated settings with validated paths
            - Initialized DatabaseManager instance

    Raises:
        ValueError: If SDS path is not set in settings.

    Example:
        >>> settings = SeismoLoaderSettings()
        >>> settings.sds_path = "/data/seismic"
        >>> settings, db_manager = setup_paths(settings)
    """
    sds_path = settings.sds_path
    if not sds_path:
        raise ValueError("\nSDS Path not set!")

    # Setup SDS directory
    if not os.path.exists(sds_path):
        os.makedirs(sds_path)

    # Initialize database manager
    db_path = settings.db_path
    db_manager = DatabaseManager(db_path)

    settings.sds_path = sds_path
    settings.db_path = db_path

    return settings, db_manager

# not in use?
def get_selected_stations_at_channel_level(settings: SeismoLoaderSettings) -> SeismoLoaderSettings:
    """
    Update inventory information to include channel-level details for selected stations.

    Retrieves detailed channel information for each station in the selected inventory
    using the specified FDSN client.

    Args:
        settings: Configuration settings containing station selection and client information.

    Returns:
        Updated settings with refined station inventory including channel information.

    Example:
        >>> settings = SeismoLoaderSettings()
        >>> settings = get_selected_stations_at_channel_level(settings)
    """
    print("Running get_selected_stations_at_channel_level")
    
    waveform_client = Client(settings.waveform.client)
    station_client = Client(settings.station.client) if settings.station.client else waveform_client

    invs = Inventory()
    for network in settings.station.selected_invs:
        for station in network:
            try:
                updated_inventory = station_client.get_stations(
                    network=network.code,
                    station=station.code,
                    level="channel"
                )
                invs += updated_inventory
                
            except Exception as e:
                print(f"Error updating station {station.code}:\n{e}")

    settings.station.selected_invs = invs
    return settings


def get_stations(settings: SeismoLoaderSettings) -> Optional[Inventory]:
    """
    Retrieve station inventory based on configured criteria.

    Gets station information from FDSN web services or local inventory based on
    settings, including geographic constraints, network/station filters, and channel
    preferences.

    Args:
        settings: Configuration settings containing station selection criteria,
            client information, and filtering preferences.

    Returns:
        Inventory containing matching stations, or None if no stations found
        or if station service is unavailable.

    Note:
        The function applies several layers of filtering:
        1. Basic network/station/location/channel criteria
        2. Geographic constraints (if specified)
        3. Station exclusions/inclusions
        4. Channel and location preferences
        5. Sample rate filtering

    Example:
        >>> settings = SeismoLoaderSettings()
        >>> settings.station.network = "IU"
        >>> inventory = get_stations(settings)
    """
    print("Running get_stations")

    starttime = UTCDateTime(settings.station.date_config.start_time)
    endtime = UTCDateTime(settings.station.date_config.end_time)
    waveform_client = Client(settings.waveform.client)

    highest_sr_only = settings.station.highest_samplerate_only
    cha_pref = settings.waveform.channel_pref
    loc_pref = settings.waveform.location_pref

    station_client = Client(settings.station.client) if settings.station.client else waveform_client

    # Set default wildcards for unspecified codes
    net = settings.station.network or '*'
    sta = settings.station.station or '*'
    loc = settings.station.location or '*'
    cha = settings.station.channel or '*'

    kwargs = {
        'network': net,
        'station': sta,
        'location': loc,
        'channel': cha,
        'starttime': starttime,
        'endtime': endtime,
        'includerestricted': settings.station.include_restricted,
        'level': settings.station.level.value
    }

    # Verify station service availability
    if 'station' not in station_client.services:
        print(f"Station service not available at {station_client.base_url}, no stations returned")
        return None

    # Remove unsupported parameters for this client
    kwargs = {k: v for k, v in kwargs.items() 
             if k in station_client.services['station']}

    inv = None
    # Try loading local inventory if specified
    if settings.station.local_inventory:
        try: 
            inv = obspy.read_inventory(settings.station.local_inventory, level='channel')
        except Exception as e:
            print(f"Could not read {settings.station.local_inventory}:\n{e}")


    # Query stations based on geographic constraints
    elif settings.station.geo_constraint:

        # Reduce number of circular constraints to reduce excessive client calls
        bound_searches = [ele for ele in settings.station.geo_constraint 
                        if ele.geo_type == GeoConstraintType.BOUNDING]

        circle_searches = [ele for ele in settings.station.geo_constraint 
                        if ele.geo_type == GeoConstraintType.CIRCLE]

        if len(circle_searches) > 4: # not as strict for stations
            new_circle_searches = []

            circ_center_lat = sum(p.coords.lat for p in circle_searches) / len(circle_searches)
        
            lon_radians = [np.radians(p.coords.lon) for p in circle_searches]
            avg_x = sum(np.cos(r) for r in lon_radians) / len(circle_searches)
            avg_y = sum(np.sin(r) for r in lon_radians) / len(circle_searches)
            circ_center_lon = np.degrees(np.arctan2(avg_y, avg_x))

            circ_distances = [ np.sqrt((circ_center_lat - p.coords.lat)**2 + (circ_center_lon - p.coords.lon)**2)
                            for p in circle_searches]
            max_circ_distances = max(circ_distances)

            mean_circ = copy.deepcopy(circle_searches[0])
            mean_circ.coords.lat = circ_center_lat
            mean_circ.coords.lon = circ_center_lon
            if mean_circ.coords.min_radius > max_circ_distances:
                mean_circ.coords.min_radius -= max_circ_distances
            mean_circ.coords.max_radius += max_circ_distances

            if max_circ_distances < 60: # in degrees. make this wider for stations
                circle_searches = [mean_circ]
            else: # go throught the list and remove what we can
                new_circle_searches = [mean_circ]
                for i, cs in enumerate(circle_searches):
                    if circ_distances[i] >= 60:  # add any outliers
                        new_circle_searches.append(cs)
                circle_searches = new_circle_searches

        for geo in bound_searches + circle_searches:
            _inv = None
            try:
                if geo.geo_type == GeoConstraintType.BOUNDING:
                    _inv = station_client.get_stations(
                        minlatitude=round(geo.coords.min_lat,4),
                        maxlatitude=round(geo.coords.max_lat,4),
                        minlongitude=round(geo.coords.min_lon,4),
                        maxlongitude=round(geo.coords.max_lon,4),
                        **kwargs
                    )
                elif geo.geo_type == GeoConstraintType.CIRCLE:
                    _inv = station_client.get_stations(
                        minradius=max(0,round(geo.coords.min_radius,3)),
                        maxradius=min(180,round(geo.coords.max_radius,3)),
                        latitude=round(geo.coords.lat,4),
                        longitude=round(geo.coords.lon,4),
                        **kwargs
                    )
                else:
                    print(f"Unknown Geometry type: {geo.geo_type}")
            except FDSNNoDataException:
                print(f"No stations found at {station_client.base_url} with given geographic bounds")

            if _inv is not None:
                inv = _inv if inv is None else inv + _inv

    else:  # Query without geographic constraints
        try:
            inv = station_client.get_stations(**kwargs)
        except FDSNNoDataException:
            print(f"No stations found at {station_client.base_url} with given parameters")
            return None

    if inv is None:
        print("No inventory returned (!?)")
        return None

    # Apply station exclusions
    if settings.station.exclude_stations: # a "SeismoQuery" object
        for sq in settings.station.exclude_stations:
            inv = inv.remove(network=sq.network, station=sq.station)

    # Add forced stations
    if settings.station.force_stations: # a "SeismoQuery" object
        for sq in settings.station.force_stations:
            try:               
                inv += station_client.get_stations(
                    network=sq.network,
                    station=sq.station,
                    location=sq.location or '*',
                    channel=sq.channel or '*',
                    level='channel'
                )
            except Exception as e:
                print(f"Could not find requested station {net}.{sta} at {settings.station.client}\n{e}")
                continue

    # Apply final filters
    if highest_sr_only:
        inv = select_highest_samplerate(inv, minSR=5)
    
    if cha_pref or loc_pref:
        inv = get_preferred_channels(inv, cha_pref, loc_pref)

    return inv


def get_events(settings: SeismoLoaderSettings) -> List[Catalog]:
    """
    Retrieve seismic event catalogs based on configured criteria.

    Queries FDSN web services or loads local catalogs for seismic events matching
    specified criteria including time range, magnitude, depth, and geographic constraints.

    Args:
        settings: Configuration settings containing event search criteria,
            client information, and filtering preferences.

    Returns:
        List of ObsPy Catalog objects containing matching events.
        Returns empty catalog if no events found.

    Raises:
        FileNotFoundError: If local catalog file not found.
        PermissionError: If unable to access local catalog file.
        ValueError: If invalid geographic constraint type specified.

    Example:
        >>> settings = SeismoLoaderSettings()
        >>> settings.event.min_magnitude = 5.0
        >>> catalogs = get_events(settings)
    """
    print("Running get_events")

    starttime = UTCDateTime(settings.event.date_config.start_time)
    endtime = UTCDateTime(settings.event.date_config.end_time)

    waveform_client = Client(settings.waveform.client)
    event_client = Client(settings.event.client) if settings.event.client else waveform_client

    # Check for local catalog first
    if settings.event.local_catalog:
        try:
            return obspy.read_events(settings.event.local_catalog)
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {settings.event.local_catalog}")
        except PermissionError:
            raise PermissionError(f"Permission denied: {settings.event.local_catalog}")
        except Exception as e:
            raise Exception(f"Error reading catalog:\n{e}")

    catalog = Catalog()

    # Build query parameters
    kwargs = {
        'starttime': starttime,
        'endtime': endtime,
        'minmagnitude': settings.event.min_magnitude,
        'maxmagnitude': settings.event.max_magnitude,
        'mindepth': settings.event.min_depth,
        'maxdepth': settings.event.max_depth,
        'includeallorigins': settings.event.include_all_origins,
        'includeallmagnitudes': settings.event.include_all_magnitudes,
        'includearrivals': settings.event.include_arrivals,
        'eventtype': settings.event.eventtype,
        'catalog': settings.event.catalog,
        'contributor': settings.event.contributor,
        'updatedafter': settings.event.updatedafter
    }

    # Verify event service availability
    if 'event' not in event_client.services:
        print(f"Event service not available at {event_client.base_url}")
        return catalog

    # Remove unsupported parameters for this client
    kwargs = {k: v for k, v in kwargs.items() 
             if k in event_client.services['event']}

    # Handle global search case
    if not settings.event.geo_constraint:
        try:
            cat = event_client.get_events(**kwargs)
            print(f"Global Search: Found {len(cat)} events from {settings.event.client}")
            catalog.extend(cat)
        except FDSNNoDataException:
            print("No events found in global search")
        return catalog

    # Handle geographic constraints
    # But first.. reduce number of circular constraints to reduce excessive client calls
    bound_searches = [ele for ele in settings.event.geo_constraint 
                    if ele.geo_type == GeoConstraintType.BOUNDING]

    circle_searches = [ele for ele in settings.event.geo_constraint 
                    if ele.geo_type == GeoConstraintType.CIRCLE]

    if len(circle_searches) > 1:
        new_circle_searches = []

        circ_center_lat = sum(p.coords.lat for p in circle_searches) / len(circle_searches)

        lon_radians = [np.radians(p.coords.lon) for p in circle_searches]
        avg_x = sum(np.cos(r) for r in lon_radians) / len(circle_searches)
        avg_y = sum(np.sin(r) for r in lon_radians) / len(circle_searches)
        circ_center_lon = np.degrees(np.arctan2(avg_y, avg_x))
        
        circ_distances = [ np.sqrt((circ_center_lat - p.coords.lat)**2 + (circ_center_lon - p.coords.lon)**2)
                         for p in circle_searches]
        max_circ_distances = max(circ_distances)

        mean_circ = copy.deepcopy(circle_searches[0])
        mean_circ.coords.lat = circ_center_lat
        mean_circ.coords.lon = circ_center_lon
        if mean_circ.coords.min_radius > max_circ_distances:
            mean_circ.coords.min_radius -= max_circ_distances
        mean_circ.coords.max_radius += max_circ_distances

        if max_circ_distances < 15: # in degrees. all points packed in closely enough
            circle_searches = [mean_circ]
        else: # go throught the list and remove what we can
            new_circle_searches = [mean_circ]
            for i, cs in enumerate(circle_searches):
                if circ_distances[i] >= 15:  # add any outliers
                    new_circle_searches.append(cs)
            circle_searches = new_circle_searches


    for geo in bound_searches + circle_searches: 
        try:
            if geo.geo_type == GeoConstraintType.CIRCLE:
                cat = event_client.get_events(
                    latitude=round(geo.coords.lat,4),
                    longitude=round(geo.coords.lon,4),
                    minradius=max(0,round(geo.coords.min_radius,3)),
                    maxradius=min(180,round(geo.coords.max_radius,3)),
                    **kwargs
                )
                print(f"Found {len(cat)} events from {settings.event.client}")
                catalog.extend(cat)

            elif geo.geo_type == GeoConstraintType.BOUNDING:
                cat = event_client.get_events(
                    minlatitude=round(geo.coords.min_lat,4),
                    minlongitude=round(geo.coords.min_lon,4),
                    maxlatitude=round(geo.coords.max_lat,4),
                    maxlongitude=round(geo.coords.max_lon,4),
                    **kwargs
                )
                print(f"Found {len(cat)} events from {settings.event.client}")
                catalog.extend(cat)

            else:
                raise ValueError(f"Invalid event search type: {geo.geo_type.value}")

        except FDSNNoDataException:
            print(f"No events found for constraint: {geo.geo_type}")
            continue
    
    # Remove duplicates
    catalog = remove_duplicate_events(catalog)

    return catalog



def run_continuous(settings: SeismoLoaderSettings):
    """
    Retrieves continuous seismic data over long time intervals for a set of stations
    defined by the `inv` parameter. The function manages multiple steps including
    generating data requests, pruning unnecessary requests based on existing data,
    combining requests for efficiency, and finally archiving the retrieved data.

    The function uses a client setup based on the configuration in `settings` to
    handle different data sources and authentication methods. Errors during client
    creation or data retrieval are handled gracefully, with issues logged to the console.

    Parameters:
    - settings (SeismoLoaderSettings): Configuration settings containing client information,
      authentication details, and database paths necessary for data retrieval and storage.
      This should include the start and end times for data collection, database path,
      and SDS archive path among other configurations.
    - inv (Inventory): An object representing the network/station/channel inventory
      to be used for data requests. This is usually prepared prior to calling this function.

    Workflow:
    1. Initialize clients for waveform data retrieval.
    2. Retrieve station information based on settings.
    3. Collect initial data requests for the given time interval.
    4. Prune requests based on existing data in the database to avoid redundancy.
    5. Combine similar requests to minimize the number of individual operations.
    6. Update or create clients based on specific network credentials if necessary.
    7. Execute data retrieval requests, archive data to disk, and update the database.

    Raises:
    - Exception: General exceptions could be raised due to misconfiguration, unsuccessful
      data retrieval or client initialization errors. These exceptions are caught and logged,
      but not re-raised, allowing the process to continue with other requests.

    Notes:
    - It is crucial to ensure that the settings object is correctly configured, especially
      the client details and authentication credentials to avoid runtime errors.
    - The function logs detailed information about the processing steps and errors to aid
      in debugging and monitoring of data retrieval processes.
    """
    print("Running run_continuous\n----------------------")
    
    settings, db_manager = setup_paths(settings)

    starttime = UTCDateTime(settings.station.date_config.start_time)
    endtime = UTCDateTime(settings.station.date_config.end_time)
    waveform_client = Client(settings.waveform.client)

    # Sanity check times
    endtime = min(endtime, UTCDateTime.now()-120)
    if starttime > endtime:
        print("Starttime greater than than endtime!")
        return

    # Collect requests
    requests = collect_requests(settings.station.selected_invs, 
        starttime, endtime, days_per_request=settings.waveform.days_per_request,
        cha_pref=settings.waveform.channel_pref,loc_pref=settings.waveform.location_pref)

    # Remove any for data we already have (requires updated db)
    # If force_redownload is flagged, then ignore request pruning
    if settings.waveform.force_redownload:
        print("Forcing re-download as requested...")
        pruned_requests = request
    else:
        # no message needed for default behaviour
        pruned_requests= prune_requests(requests, db_manager, settings.sds_path)

    # Break if nothing to do
    if len(pruned_requests) < 1:
        return

    # Combine these into fewer (but larger) requests
    combined_requests = combine_requests(pruned_requests)

    waveform_clients= {'open':waveform_client} #now a dictionary
    requested_networks = [ele[0] for ele in combined_requests]

    # May only work for network-wide credentials at the moment (99% use case)
    for cred in settings.auths:
        cred_net = cred.nslc_code.split('.')[0].upper()
        if cred_net not in requested_networks:
            continue
        try:
            new_client = Client(settings.waveform.client, 
                user=cred.username.upper(), password=cred.password)
            waveform_clients.update({cred_net:new_client})
        except:
            print("Issue creating client: %s %s via %s:%s" % (settings.waveform.client, 
                cred.nslc_code, cred.username, cred.password))
            continue

    # Archive to disk and updated database
    for request in combined_requests:
        print("Requesting: ", request)
        time.sleep(0.05) # to help ctrl-C out if needed
        try:
            archive_request(request, waveform_clients, settings.sds_path, db_manager)
        except Exception as e:
            print(f"Continuous request not successful: {request} with exception:\n {e}")
            continue

    # Cleanup the database
    try:
        db_manager.join_continuous_segments(settings.processing.gap_tolerance)
    except Exception as e:
        print(f"! Error with join_continuous_segments:\n {e}")

    return True



def run_event(settings: SeismoLoaderSettings, stop_event: threading.Event = None):
    """
    Processes and downloads seismic event data for each event in the provided catalog using
    the specified settings and station inventory. The function manages multiple steps including
    data requests, arrival time calculations, database updates, and data retrieval.

    The function handles data retrieval from FDSN web services with support for authenticated
    access and restricted data. Processing can be interrupted via the stop_event parameter,
    and errors during execution are handled gracefully with detailed logging.

    Parameters:
    - settings (SeismoLoaderSettings): Configuration settings that include client details,
      authentication credentials, event-specific parameters like radius and time window,
      and paths for data storage.
    - stop_event (threading.Event): Optional event flag for canceling the operation mid-execution.
      If provided and set, the function will terminate gracefully at the next safe point.

    Workflow:
    1. Initialize paths and database connections
    2. Load appropriate travel time model for arrival calculations
    3. Process each event in the catalog:
        a. Calculate arrival times and generate data requests
        b. Update arrival information in database
        c. Check for existing data and prune redundant requests
        d. Download and archive new data
        e. Add event metadata to traces (arrivals, distances, azimuths)
    4. Combine data into event streams with complete metadata

    Returns:
    - List[obspy.Stream]: List of streams, each containing data for one event with
      complete metadata including arrival times, distances, and azimuths. Returns None
      if operation is canceled or no data is processed.

    Raises:
    - Exception: General exceptions from client creation, data retrieval, or processing
      are caught and logged but not re-raised, allowing processing to continue with
      remaining events.

    Notes:
    - The function supports threading and can be safely interrupted via stop_event
    - Station metadata is enriched with event-specific information including arrivals
    - Data is archived in SDS format and the database is updated accordingly
    - Each stream in the output includes complete event metadata for analysis
    """
    print(f"Running run_event\n-----------------")
    
    settings, db_manager = setup_paths(settings)
    waveform_client = Client(settings.waveform.client)
    
    # Initialize travel time model
    try:
        ttmodel = TauPyModel(settings.event.model)
    except Exception as e:
        print(f"Falling back to IASP91 model: {str(e)}")
        ttmodel = TauPyModel('IASP91')

    event_streams = []
    all_missing = {}
    for i, eq in enumerate(settings.event.selected_catalogs):
        print(f"\nProcessing event {i+1}/{len(settings.event.selected_catalogs)}  |  OT: {str(eq.origins[0].time)[0:16]} LAT: {eq.origins[0].latitude:.2f} LON: {eq.origins[0].longitude:.2f}")
        
        # Check for cancellation
        if stop_event and stop_event.is_set():
            print("Run cancelled!")
            return None

        # Collect requests for this event
        try:
            requests, new_arrivals, p_arrivals = collect_requests_event(
                eq, settings.station.selected_invs,
                model=ttmodel,
                settings=settings
            )
        except Exception as e:
            print(f"Issue running collect_requests_event in run_event:\n {e}")

        # Update arrival database
        if new_arrivals:
            db_manager.bulk_insert_arrival_data(new_arrivals)

        # Process data requests
        if settings.waveform.force_redownload:
            print("Forcing re-download as requested...")
            pruned_requests = requests
        else:
            pruned_requests = prune_requests(requests, db_manager, settings.sds_path)
        
        if stop_event and stop_event.is_set():
            print("Run cancelled!")
            return None

        # Download new data if needed
        if pruned_requests:
            combined_requests = combine_requests(pruned_requests)
            
            # Setup authenticated clients
            waveform_clients = {'open': waveform_client}
            requested_networks = [req[0] for req in combined_requests]
            
            for cred in settings.auths:
                cred_net = cred.nslc_code.split('.')[0].upper()
                if cred_net not in requested_networks:
                    continue
                try:
                    new_client = Client(
                        settings.waveform.client,
                        user=cred.username.upper(),
                        password=cred.password
                    )
                    waveform_clients[cred_net] = new_client
                except Exception as e:
                    print(f"Issue creating client for {cred_net}:\n {str(e)}")

            # Process requests
            for request in combined_requests:
                if stop_event and stop_event.is_set():
                    print("Run cancelled!")
                    return None
                
                print(f"Requesting: {request}")
                try:
                    archive_request(
                        request,
                        waveform_clients,
                        settings.sds_path,
                        db_manager
                    )
                except Exception as e:
                    print(f"Error archiving request {request}:\n {str(e)}")

        # Read all data for this event
        event_stream = obspy.Stream()
        for req in requests:
            query = SeismoQuery(
                network=req[0],
                station=req[1],
                location=req[2],
                channel=req[3],
                starttime=req[4],
                endtime=req[5]
            )
            
            if stop_event and stop_event.is_set():
                print("Run cancelled!")
                return None
            
            try:
                st = get_local_waveform(query, settings)
                if st:
                    # Add event metadata to traces
                    arrivals = db_manager.fetch_arrivals_distances(
                        str(eq.preferred_origin_id),
                        query.network,
                        query.station
                    )
                    
                    if arrivals:
                        for tr in st:
                            tr.stats.event_id = str(eq.resource_id)
                            tr.stats.p_arrival = arrivals[0]
                            tr.stats.s_arrival = arrivals[1]
                            tr.stats.distance_km = arrivals[2]
                            tr.stats.distance_deg = arrivals[3]
                            tr.stats.azimuth = arrivals[4]
                    
                    event_stream += st
            except Exception as e:
                print(f"Error reading data for {query.network}.{query.station}:\n {str(e)}")
                continue

        # Now attempt to keep track of what data was missing. Note that this is not catching out-of-bounds data, for better or worse (probably better)
        missing = get_missing_from_request(str(eq.resource_id),requests,event_stream)
        #print("DEBUG missing: ", missing)
        #print(event_stream)
        #print("DEBUG requests: ", requests)

        all_missing.update(missing)

        if len(event_stream) > 0:
            event_streams.append(event_stream)


    # Final database cleanup
    try:
        print("\n~~ Cleaning up database ~~")
        db_manager.join_continuous_segments(settings.processing.gap_tolerance)
    except Exception as e:
        print(f"! Error with join_continuous_segments: {str(e)}")

    return event_streams, all_missing


def run_main(
    settings: Optional[SeismoLoaderSettings] = None,
    from_file: Optional[str] = None
    ) -> None:
    """Main entry point for seismic data retrieval and processing.

    Coordinates the overall workflow for retrieving and processing seismic data,
    handling both continuous and event-based data collection based on settings.

    Args:
        settings: Configuration settings for data retrieval and processing.
            If None, settings must be provided via from_file.
        from_file: Path to configuration file to load settings from.
            Only used if settings is None.

    Example:
        >>> # Using settings object
        >>> settings = SeismoLoaderSettings()
        >>> settings.download_type = DownloadType.EVENT
        >>> run_main(settings)
        
        >>> # Using configuration file
        >>> run_main(from_file="config.ini")
    """
    if not settings and from_file:
        settings = SeismoLoaderSettings()
        settings = settings.from_cfg_file(cfg_source=from_file)

    settings, db_manager = setup_paths(settings)

    # Load client URL mappings
    settings.client_url_mapping.load()
    URL_MAPPINGS = settings.client_url_mapping.maps

    # Determine download type
    download_type = settings.download_type.value
    if not is_in_enum(download_type, DownloadType):
        download_type = DownloadType.CONTINUOUS

    # Process continuous data
    if download_type == DownloadType.CONTINUOUS:
        settings.station.selected_invs = get_stations(settings)
        run_continuous(settings)

    # Process event-based data
    if download_type == DownloadType.EVENT:
        settings.event.selected_catalogs = get_events(settings)
        settings.station.selected_invs = get_stations(settings)
        run_event(settings)

    ## Final database cleanup
    #print(" ~~ Cleaning up database ~~")
    #db_manager.join_continuous_segments(settings.processing.gap_tolerance)
