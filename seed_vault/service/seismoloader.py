"""
The main functions for SEED-vault, from original CLI-only version (Pickle 2024)

"""

import os
import sys
import copy
from time import sleep,time
import fnmatch
import sqlite3
from datetime import datetime,timedelta,timezone
import configparser
import pandas as pd
import numpy as np
import threading
import random
from typing import Any, Dict, List, Tuple, Optional, Union
from collections import defaultdict
import warnings

from obspy import UTCDateTime
from obspy.core.stream import Stream
from obspy.core.stream import read as streamread
from obspy.core.inventory import read_inventory,Inventory
from obspy.core.event import read_events,Event,Catalog

from obspy.clients.fdsn import Client
from obspy.taup import TauPyModel
from obspy.geodetics.base import locations2degrees,gps2dist_azimuth
from obspy.clients.fdsn.header import URL_MAPPINGS, FDSNNoDataException
from obspy.io.mseed.headers import InternalMSEEDWarning
warnings.filterwarnings("ignore", category=InternalMSEEDWarning)

from seed_vault.models.config import SeismoLoaderSettings, SeismoQuery, convert_geo_to_minus180_180
from seed_vault.enums.config import DownloadType, GeoConstraintType
from seed_vault.service.utils import is_in_enum,get_sds_filenames,to_timestamp,\
    filter_inventory_by_geo_constraints,filter_catalog_by_geo_constraints,format_error
from seed_vault.service.db import DatabaseManager,stream_to_db_elements,miniseed_to_db_elements,\
    populate_database_from_sds,populate_database_from_files,populate_database_from_files_dumb
from seed_vault.service.waveform import get_local_waveform, stream_to_dataframe



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

    # Select inventory within the overall time window
    sub_inv = inv.select(starttime=time0, endtime=time1)

    # Filter by preferred channels if specified
    if cha_pref or loc_pref:
        sub_inv = get_preferred_channels(sub_inv, cha_pref, loc_pref, time0)

    # Process each network, station, and channel
    for net in sub_inv:
        for sta in net:
            for cha in sta:
                # Determine effective time range for this channel
                channel_start = max(time0, cha.start_date if cha.start_date else time0)
                channel_end = min(time1, cha.end_date if cha.end_date else time1)

                if channel_start >= channel_end:
                    continue

                # Break into smaller requests based on days_per_request
                current_start = channel_start
                while current_start < channel_end:
                    window_end = min(
                        current_start + timedelta(days=days_per_request, microseconds=-1),
                        channel_end
                    )

                    requests.append((
                        net.code,
                        sta.code,
                        cha.location_code,
                        cha.code,
                        current_start.isoformat() + "Z",
                        window_end.isoformat() + "Z"
                    ))

                    current_start = window_end + timedelta(microseconds=1)

    return requests

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

    # Ensure 1D vel model is loaded
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
                print(f"    Skipping {net.code}.{sta.code} \t(distance {dist_deg:4.1f} < min_radius {min_radius:4.1f})")
                continue
            elif dist_deg > max_radius:
                print(f"    Skipping {net.code}.{sta.code} \t(distance {dist_deg:4.1f} > max_radius {max_radius:4.1f})")
                continue
            else:
                # Generate requests for each channel
                for cha in sta:
                    t_end = min(t_end, datetime.now().timestamp() - 120)
                    t_start = min(t_start, t_end)
                    requests_per_eq.append((
                        net.code,
                        sta.code,
                        cha.location_code,
                        cha.code,
                        datetime.fromtimestamp(t_start, tz=timezone.utc).isoformat(),
                        datetime.fromtimestamp(t_end, tz=timezone.utc).isoformat()
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

    if not requests:
        return []

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
            net, # keep networks distinct
            ','.join(sorted(stas)),
            ','.join(sorted(locs)),
            ','.join(sorted(chans)),
            t0,
            t1
        ))

    return combined_requests


def get_missing_from_request(db_manager, eq_id: str, requests: List[Tuple], st: Stream) -> dict:
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
        net, sta, loc, cha, t0, t1 = request #only using t0 really
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

                    # check the recently downloaded stream
                    if (tr.stats.network == net and 
                        tr.stats.station == sta and
                        tr.stats.location == (location if location else '') and
                        fnmatch.fnmatch(tr.stats.channel, channel)):
                        found_match = True
                        break

                    # also check the database
                    if db_manager.check_data_existence(tr.stats.network,
                                                    tr.stats.station,
                                                    tr.stats.location,
                                                    tr.stats.channel,
                                                    t0,t1):
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


def prune_requests(
    requests: List[Tuple[str, str, str, str, str, str]],
    db_manager: DatabaseManager,
    sds_path: str,
    min_request_window: float = 3
) -> List[Tuple[str, str, str, str, str, str]]:
    """
    Remove overlapping requests where data already exists in the archive.

    Checks both the database and filesystem for existing data and removes or
    splits requests to avoid re-downloading data that should be there already.

    Args:
        requests: List of request tuples containing:
            (network, station, location, channel, start_time, end_time)
        db_manager: DatabaseManager instance for querying existing data.
        sds_path: Root path of the SDS archive.
        min_request_window: Minimum time window in seconds to keep a request.
            Requests shorter than this are discarded. Default is 3 seconds.

    Returns:
        List of pruned request tuples, sorted by start time, network, and station.

    Note:
        This function will update the database if it finds files in the SDS
        structure that aren't yet recorded in the database.

    Example:
        >>> requests = [("IU", "ANMO", "00", "BHZ", "2020-01-01", "2020-01-02")]
        >>> pruned = prune_requests(requests, db_manager, "/data/SDS")
    """
    if not requests:
        return []

    # Group requests by network for batch processing
    requests_by_network = {}
    for req in requests:
        network = req[0]
        if network not in requests_by_network:
            requests_by_network[network] = []
        requests_by_network[network].append(req)

    pruned_requests = []

    with db_manager.connection() as conn:
        cursor = conn.cursor()

        # Process each network as a batch
        for network, network_requests in requests_by_network.items():
            # Find min and max times for this batch to reduce query range
            min_start = min(UTCDateTime(req[4]) for req in network_requests)
            max_end = max(UTCDateTime(req[5]) for req in network_requests)

            # Get all relevant data in one query
            cursor.execute('''
                SELECT network, station, location, channel, starttime, endtime 
                FROM archive_data
                WHERE network = ? AND endtime >= ? AND starttime <= ?
            ''', (network, min_start.isoformat(), max_end.isoformat()))

            # Organize existing data by (station, location, channel)
            existing_data = {}
            for row in cursor.fetchall():
                key = (row[1], row[2], row[3])  # station, location, channel
                if key not in existing_data:
                    existing_data[key] = []
                existing_data[key].append((UTCDateTime(row[4]), UTCDateTime(row[5])))

            # Process each request with the pre-fetched data
            for req in network_requests:
                network, station, location, channel, start_str, end_str = req
                start_time = UTCDateTime(start_str)
                end_time = UTCDateTime(end_str)

                if end_time - start_time < min_request_window:
                    continue

                key = (station, location, channel)

                # First check if we need to look at the filesystem
                # We'll do this regardless of whether the key exists or not in existing_data
                need_to_check_files = True

                # If we have data for this key, check if it fully covers our request
                if key in existing_data and existing_data[key]:
                    # Check if this request is fully covered by existing data
                    relevant_intervals = [
                        (db_start, db_end) for db_start, db_end in existing_data[key]
                        if not (db_end <= start_time or db_start >= end_time)
                    ]

                    # If we have complete coverage, we don't need to look for files
                    if relevant_intervals:
                        relevant_intervals.sort(key=lambda x: x[0])

                        # Analyze coverage by merging overlapping intervals
                        full_coverage = False
                        merged_intervals = []
                        for interval in relevant_intervals:
                            if not merged_intervals:
                                merged_intervals.append(interval)
                            else:
                                last_end = merged_intervals[-1][1]
                                if interval[0] <= last_end:
                                    # Overlap found, merge intervals
                                    merged_intervals[-1] = (merged_intervals[-1][0], max(last_end, interval[1]))
                                else:
                                    # No overlap, add as new interval
                                    merged_intervals.append(interval)

                        # Check if a single merged interval covers our entire request
                        for merged_start, merged_end in merged_intervals:
                            if merged_start <= start_time and merged_end >= end_time:
                                full_coverage = True
                                break

                        if full_coverage:
                            need_to_check_files = False

                # Look for files in the SDS archive if necessary
                if need_to_check_files:
                    file_paths = get_sds_filenames(
                        network, station, location, channel, 
                        start_time, end_time, sds_path
                    )

                    # If files exist, update the database and our in-memory cache
                    if file_paths:
                        # Update database with newly found files
                        populate_database_from_files(cursor, file_paths=file_paths)

                        # Refresh our data for this key from the database
                        cursor.execute('''
                            SELECT starttime, endtime FROM archive_data
                            WHERE network = ? AND station = ? AND location = ? AND channel = ?
                            AND endtime >= ? AND starttime <= ?
                            ORDER BY starttime
                        ''', (network, station, location, channel,
                             start_time.isoformat(), end_time.isoformat()))

                        # Update our in-memory cache
                        existing_data[key] = [(UTCDateTime(r[0]), UTCDateTime(r[1])) 
                                              for r in cursor.fetchall()]

                # Now that database is updated, identify gaps
                if key in existing_data and existing_data[key]:
                    relevant_intervals = [
                        (db_start, db_end) for db_start, db_end in existing_data[key]
                        if not (db_end <= start_time or db_start >= end_time)
                    ]

                    if not relevant_intervals:
                        # No coverage at all, add the full request
                        pruned_requests.append(req)
                    else:
                        relevant_intervals.sort(key=lambda x: x[0])

                        # Find gaps in coverage
                        current_time = start_time
                        gaps = []
                        for db_start, db_end in relevant_intervals:
                            if current_time < db_start:
                                gaps.append((current_time, db_start))
                            current_time = max(current_time, db_end)

                        if current_time < end_time:
                            gaps.append((current_time, end_time))

                        # Add requests per appropriate gap
                        for gap_start, gap_end in gaps:
                            if gap_end - gap_start >= min_request_window:
                                pruned_requests.append((
                                    network, station, location, channel,
                                    gap_start.isoformat(),
                                    gap_end.isoformat()
                                ))
                else:
                    # No data found in database or files, add the entire request
                    pruned_requests.append(req)

    if pruned_requests:
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

        t0 = UTCDateTime(request[4])
        t1 = UTCDateTime(request[5])

        # Double check that the request range is real and not some db artifact
        if t1 - t0 < 3:
            return

        time0 = time()
        
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
            'starttime': t0,
            'endtime': t1
        }

        # if possible, do not request anything under three seconds
        if 'minimumlength' in wc.services['dataselect'].keys():
            kwargs['minimumlength'] = 3.0

        # Handle long station lists
        if len(request[1]) > 24:
            st = Stream()
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
                        print(format_error(s,e))
        else:
            st = wc.get_waveforms(**kwargs)

        # Log download statistics
        download_time = time() - time0
        download_size = sum(tr.data.nbytes for tr in st) / 1024**2  # MB
        if download_size > 0.001:
            print(f"      > Downloaded {download_size:.3f} MB @ {download_size/download_time:.2f} MB/s")
        else:
            print(f"      ! Data missing on the server, presumably a gap...")

        # Remove any widowing artifacts
        st.traces = [tr for tr in st if len(tr.data) > 1]

    except Exception as e:
        if 'code: 204' in str(e):
            print(f"      ~ No data available")
        else:
            print(format_error(request[1].upper(),e))
        return

    if not st:
        return

    # Create a Stream-based dictionary to group traces by day
    traces_by_day = defaultdict(Stream)

    for tr in st:
        net = tr.stats.network
        sta = tr.stats.station
        loc = tr.stats.location
        cha = tr.stats.channel
        starttime = tr.stats.starttime
        endtime = tr.stats.endtime

        # Handle trace start leaking into previous day
        day_boundary = UTCDateTime(starttime.date + timedelta(days=1))
        if (day_boundary - starttime) <= tr.stats.delta:
            starttime = day_boundary

        current_time = UTCDateTime(starttime.date)
        while current_time < endtime:
            year = current_time.year
            doy = current_time.julday
            
            next_day = current_time + 86400
            day_end = min(next_day - tr.stats.delta/3, endtime)
            
            day_tr = tr.slice(current_time, day_end, nearest_sample=False)
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
                existing_st = streamread(full_path)
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

        existing_st = Stream([tr for tr in existing_st if len(tr.data) > 1]) # assume 1-sample traces are artifacts

        if existing_st:
            try:
                # Try STEIM2 compression first
                existing_st.write(full_path, format="MSEED", encoding='STEIM2')
                to_insert_db.extend(stream_to_db_elements(existing_st))
            except Exception as e:
                if "Wrong dtype" in str(e):
                    # Fall back to uncompressed format
                    print("Data type not compatible with STEIM2, attempting uncompressed format...")
                    try:
                        existing_st.write(full_path, format="MSEED")
                        to_insert_db.extend(stream_to_db_elements(existing_st))
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
    print("Running get_stations...")

    starttime = UTCDateTime(settings.station.date_config.start_time)
    endtime = UTCDateTime(settings.station.date_config.end_time)
    if starttime >= endtime:
        print("get_stations: Starttime greater than endtime!")
        return None
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
            inv = read_inventory(settings.station.local_inventory, level='channel')
        except Exception as e:
            print(f"Could not read {settings.station.local_inventory}:\n{e}")

    # Query stations based on geographic constraints
    elif settings.station.geo_constraint:

        geo_constraints_for_obspy = convert_geo_to_minus180_180(settings.station.geo_constraint)

        # Reduce number of circular constraints to reduce excessive client calls
        bound_searches = [ele for ele in geo_constraints_for_obspy 
                        if ele.geo_type == GeoConstraintType.BOUNDING]

        circle_searches = [ele for ele in geo_constraints_for_obspy 
                        if ele.geo_type == GeoConstraintType.CIRCLE]

        if len(circle_searches) > 4: # not as strict for stations
            new_circle_searches = []

            circ_center_lat = sum(p.coords.lat for p in circle_searches) / len(circle_searches)
        
            lon_radians = [np.radians(p.coords.lon) for p in circle_searches]
            avg_x = sum(np.cos(r) for r in lon_radians) / len(circle_searches)
            avg_y = sum(np.sin(r) for r in lon_radians) / len(circle_searches)
            circ_center_lon = np.degrees(np.arctan2(avg_y, avg_x))

            circ_distances = [ locations2degrees(circ_center_lat,circ_center_lon, p.coords.lat,p.coords.lon)
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

        # Remove any events that may have been added by loosening geo searches. Also removes duplicates. 
        try:
            inv = filter_inventory_by_geo_constraints(inv,geo_constraints_for_obspy)            
        except Exception as e:
            print("filter_inventory_by_geo_constraits issue:",e)

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
            inv = inv.remove(network=sq.network, station=sq.station,
                location=sq.location, channel=sq.channel)

    # Add forced stations
    if settings.station.force_stations: # a "SeismoQuery" object
        for sq in settings.station.force_stations:
            try:               
                inv += station_client.get_stations(
                    network=sq.network,
                    station=sq.station,
                    location='*' if sq.location is None else sq.location,
                    channel=sq.channel or '*',
                    starttime=sq.starttime,
                    endtime=sq.endtime,
                    level=settings.station.level.value
                )
            except Exception as e:
                print(f"Could not find requested station {net}.{sta} at {settings.station.client}\n{e}")
                continue

    # Apply final filters
    if highest_sr_only:
        inv = select_highest_samplerate(inv, minSR=5)
    
    if cha_pref or loc_pref:
        inv = get_preferred_channels(inv, cha_pref, loc_pref)

    print("     ...got stations")
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
    print("Running get_events...")

    starttime = UTCDateTime(settings.event.date_config.start_time)
    endtime = UTCDateTime(settings.event.date_config.end_time)
    if starttime >= endtime:
        print("get_events: Starttime greater than endtime!")
        return Catalog()

    waveform_client = Client(settings.waveform.client)
    event_client = Client(settings.event.client) if settings.event.client else waveform_client

    # Check for local catalog first
    if settings.event.local_catalog:
        try:
            return read_events(settings.event.local_catalog)
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

        # Sort by origin time
        catalog.events.sort(key=lambda event: event.origins[0].time)

        return catalog

    # Handle geographic constraints
    # But first.. reduce number of circular constraints to reduce excessive client calls
    geo_constraints_for_obspy = convert_geo_to_minus180_180(settings.event.geo_constraint)

    bound_searches = [ele for ele in geo_constraints_for_obspy 
                    if ele.geo_type == GeoConstraintType.BOUNDING]

    circle_searches = [ele for ele in geo_constraints_for_obspy 
                    if ele.geo_type == GeoConstraintType.CIRCLE]

    if len(circle_searches) > 1:
        new_circle_searches = []

        circ_center_lat = sum(p.coords.lat for p in circle_searches) / len(circle_searches)

        lon_radians = [np.radians(p.coords.lon) for p in circle_searches]
        avg_x = sum(np.cos(r) for r in lon_radians) / len(circle_searches)
        avg_y = sum(np.sin(r) for r in lon_radians) / len(circle_searches)
        circ_center_lon = np.degrees(np.arctan2(avg_y, avg_x))
        
        circ_distances = [ locations2degrees(circ_center_lat,circ_center_lon, p.coords.lat,p.coords.lon)
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

    # Re-filter to remove anything that eclipsed original search. Also removes duplicates.
    try:
        catalog = filter_catalog_by_geo_constraints(catalog,geo_constraints_for_obspy)
    except Exception as e:
        print("filter_catalog_by_geo_constraints issue:",e)

    # Sort by origin time
    catalog.events.sort(key=lambda event: event.origins[0].time)

    print("     ...got events")
    return catalog


def run_continuous(settings: SeismoLoaderSettings, stop_event: threading.Event = None):
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
    - stop_event (threading.Event): Optional event flag for canceling the operation mid-execution.
      If provided and set, the function will terminate gracefully at the next safe point.

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
    if not settings.station.selected_invs: #NEW / double check. issue #317
        return None

    print("Running run_continuous...\n----------------------")
    
    settings, db_manager = setup_paths(settings)

    starttime = UTCDateTime(settings.station.date_config.start_time)
    endtime = UTCDateTime(settings.station.date_config.end_time)
    waveform_client = Client(settings.waveform.client)

    # Sanity check times
    endtime = min(endtime, UTCDateTime.now()-120)
    if starttime > endtime:
        print("run_continuous: Starttime greater than endtime!")
        return True

    # Collect requests
    print("Collecting, combining, and pruning requests against database... ")
    requests = collect_requests(settings.station.selected_invs, 
        starttime, endtime, days_per_request=settings.waveform.days_per_request,
        cha_pref=settings.waveform.channel_pref,loc_pref=settings.waveform.location_pref)

    if not requests:
        print("ERROR: No requests returned! This shouldn't happen, likely issue in collect_requests.")
        return True

    # Remove any for data we already have (requires updated db)
    # If force_redownload is flagged, then ignore request pruning
    if settings.waveform.force_redownload:
        print("Forcing re-download as requested...")
        pruned_requests = requests
    else:
        # no message needed for default behaviour
        pruned_requests = prune_requests(requests, db_manager, settings.sds_path)

    # Break if nothing to do
    if not pruned_requests:
        print(f"          ... All data already archived!")
        return True

    # Check for cancellation after request pruning
    # This allows termination after database operations but before
    # network operations and data downloads begin
    if stop_event and stop_event.is_set():
        print("Run cancelled!")
        return None

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
        print(" ")    
        print("Requesting: ", request)
        sleep(0.05) # to help ctrl-C out if needed
        try:
            archive_request(request, waveform_clients, settings.sds_path, db_manager)
        except Exception as e:
            print(f"Continuous request not successful: {request} with exception:\n {e}")
            continue

        # Check for cancellation before each individual request
        # This allows termination between network requests, preventing
        # unnecessary data downloads if the user cancels mid-process
        # This is the only time consuming step so probably the only sensible place for a cancel break
        if stop_event and stop_event.is_set():
            print("Run cancelled!")
            db_manager.join_continuous_segments(settings.processing.gap_tolerance)
            return True

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

    all_event_traces = []
    all_missing = {}

    for i, eq in enumerate(settings.event.selected_catalogs):

        if stop_event and stop_event.is_set():
            print("\nCancelling run_event!")
            try:
                print("\n~~ Cleaning up database ~~")
                db_manager.join_continuous_segments(settings.processing.gap_tolerance)
            except Exception as e:
                print(f"! Error with join_continuous_segments: {str(e)}")

            if all_event_traces:
                return all_event_traces, all_missing
            else:
                return None

        try:
            event_region = eq.event_descriptions[0].text
        except:
            event_region = ""

        print(" ") # hack to make streamlit in-app log insert a newline
        print(
            f"Processing event {i+1}/{len(settings.event.selected_catalogs)} | "
            f"{event_region:^35} | "
            f"{str(eq.origins[0].time)[0:16]} "
            f"({eq.origins[0].latitude:.2f},{eq.origins[0].longitude:.2f})"
        )

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
            try:
                db_manager.bulk_insert_arrival_data(new_arrivals)
            except Exception as e:
                print(f"Issue with run_event > bulk_insert_arrival_data:\n",{e})

        # Process data requests
        if settings.waveform.force_redownload:
            print("Forcing re-download as requested...")
            pruned_requests = requests
        else:
            try:
                pruned_requests = prune_requests(requests, db_manager, settings.sds_path)
            except Exception as e:
                print(f"Issue with run_event > prune_requests:\n",{e})
        
        if len(requests) > 0 and not pruned_requests:
            print(f"          ... All data already archived!")

        # Download new data if needed
        if pruned_requests:
            try:
                combined_requests = combine_requests(pruned_requests)
            except Exception as e:
                print(f"Issue with run_event > combine_requests:\n",{e})

            if not combined_requests:
                print("DEBUG: combined requests is empty? here was pruned_requests",pruned_requests)
                continue
            
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

                print(f"  Requesting: {request}")
                try:
                    archive_request(
                        request,
                        waveform_clients,
                        settings.sds_path,
                        db_manager
                    )
                except Exception as e:
                    print(f"Error archiving request {request}:\n {str(e)}")
                    continue

        # Now load everything in from our archive
        event_stream = Stream()
        for request in requests:
            try:
                st = get_local_waveform(request, settings)
                if st:
                    # Add event metadata to traces
                    arrivals = db_manager.fetch_arrivals_distances(
                        eq.preferred_origin_id.id,
                        request[0].upper(), # network
                        request[1].upper()  # station
                        )

                    if arrivals:
                        for tr in st:
                            tr.stats.resource_id = eq.resource_id.id
                            tr.stats.p_arrival = arrivals[0]
                            tr.stats.s_arrival = arrivals[1]
                            tr.stats.distance_km = arrivals[2]
                            tr.stats.distance_deg = arrivals[3]
                            tr.stats.azimuth = arrivals[4]
                            tr.stats.event_magnitude = eq.magnitudes[0].mag if hasattr(eq, 'magnitudes') and eq.magnitudes else 0.99
                            tr.stats.event_region = event_region
                            tr.stats.event_time = eq.origins[0].time

                    event_stream.extend(st)


            except Exception as e:
                print(f"Error reading data for {request[0].upper()}.{request[1].upper()}:\n {str(e)}")
                continue

        # Now attempt to keep track of what data was missing. 
        # Note that this is not catching out-of-bounds data, for better or worse (probably better)
        if event_stream:

            all_event_traces.extend(event_stream)

            try: 
                missing = get_missing_from_request(db_manager,eq.resource_id.id,requests,event_stream)
            except Exception as e:
                print("get_missing_from_request issue:", e)

            if missing:
                all_missing.update(missing)

    # Final database cleanup
    try:
        print("\n~~ Cleaning up database ~~")
        db_manager.join_continuous_segments(settings.processing.gap_tolerance)
    except Exception as e:
        print(f"! Error with join_continuous_segments: {str(e)}")

    # And return to ui/components/waveform.py
    if all_event_traces:
        return all_event_traces, all_missing
    else:
        return None


def run_main(
    settings: Optional[SeismoLoaderSettings] = None,
    from_file: Optional[str] = None,
    stop_event: threading.Event = None
    ) -> None:
    """Main entry point for seismic data retrieval and processing.

    Coordinates the overall workflow for retrieving and processing seismic data,
    handling both continuous and event-based data collection based on settings.

    Args:
        settings: Configuration settings for data retrieval and processing.
            If None, settings must be provided via from_file.
        from_file: Path to configuration file to load settings from.
            Only used if settings is None.
        stop_event: Optional event flag for canceling the operation mid-execution.
            If provided and set, the function will terminate gracefully at the next safe point.

    Returns:
        The result from run_continuous or run_event, or None if cancelled.

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

    # Check for cancellation before starting any data processing
    # This allows early termination before any resource-intensive operations begin
    if stop_event and stop_event.is_set():
        print("Run cancelled!")
        return None

    # Process continuous data
    if download_type == DownloadType.CONTINUOUS:
        settings.station.selected_invs = get_stations(settings)
        return run_continuous(settings, stop_event)
        # run_continuous(settings) # this doesn't return anything

    # Process event-based data
    if download_type == DownloadType.EVENT:
        settings.event.selected_catalogs = get_events(settings)
        settings.station.selected_invs = get_stations(settings)
        event_traces, missing = run_event(settings, stop_event) # this returns a stream containing all the downloaded traces, and a dictionary of what's missing

    return None
