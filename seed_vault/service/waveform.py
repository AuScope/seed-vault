import pandas as pd
import os
import itertools
from typing import Tuple, List, Optional
import obspy
from obspy import UTCDateTime, Stream
from obspy.clients.filesystem.sds import Client as LocalClient

from seed_vault.models.config import SeismoLoaderSettings, SeismoQuery
from seed_vault.models.exception import NotFoundError

def stream_to_dataframe(stream):
    df = pd.DataFrame()
    for trace in stream:
        data = {
            'time': trace.times("matplotlib"),  # Times in days since '0001-01-01'
            'amplitude': trace.data,
            'channel': trace.stats.channel
        }
        trace_df = pd.DataFrame(data)
        # Adjust origin to '1970-01-01' to avoid overflow
        trace_df['time'] = pd.to_datetime(trace_df['time'], unit='D', origin=pd.Timestamp('1970-01-01'))
        df = pd.concat([df, trace_df], ignore_index=True)
    return df

def check_is_archived(cursor, req: SeismoQuery): 
    cursor.execute('''
        SELECT starttime, endtime FROM archive_data
        WHERE network = ? AND station = ? AND location = ? AND channel = ?
        AND endtime >= ? AND starttime <= ?
        ORDER BY starttime
    ''', (req.network, req.station, req.location, req.channel, req.starttime.isoformat(), req.endtime.isoformat()))
    
    existing_data = cursor.fetchall()
    if not existing_data:
        return False
    return True

#only in use for run_event
def get_local_waveform(request: Tuple[str, str, str, str, str, str], settings: SeismoLoaderSettings) -> Optional[Stream]:
    """
    Get waveform data from a local client, handling comma-separated values for network, 
    station, location, and channel fields. Unlike remote requests, local SDS does not handle such things.
    
    Args:
        request: Tuple containing (network, station, location, channel, starttime, endtime)
        settings: Settings object containing SDS path

    Returns:
        Stream object containing requested waveform data, or None if no data found
    """
    client = LocalClient(settings.sds_path)

    # Parse the comma-separated values
    networks = [n.strip().upper() for n in request[0].split(',')]
    stations = [s.strip().upper() for s in request[1].split(',')]
    # sometimes location is ''...
    locations = []
    if request[2]:
        for loc in request[2].split(','):
            loc = loc.strip().upper()
            locations.append(loc)
    else:
        locations = ['']
    channels = [c.strip().upper() for c in request[3].split(',')]

    combined_stream = Stream()

    # Generate all combinations of network, station, location, channel
    combinations = list(itertools.product(networks, stations, locations, channels))

    for network, station, location, channel in combinations:
        try:
            kwargs = {
                'network': network,
                'station': station,
                'location': location,
                'channel': channel,
                'starttime': UTCDateTime(request[4]),
                'endtime': UTCDateTime(request[5])
            }

            stream = client.get_waveforms(**kwargs)
            
            if stream and len(stream) > 0:
                combined_stream += stream
 
        except Exception as e:
            # Continue to the next combination if this one fails
            print("get_local_waveform problem:",e)
            continue

    # Return the combined stream, or None if empty
    if len(combined_stream) > 0:
        return combined_stream
    else:
        return None