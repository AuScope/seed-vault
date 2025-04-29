"""
Database management module for the SEED-vault archive

This module provides a DatabaseManager class for handling seismic data storage in SQLite,
including archive data and arrival data. It implements connection management, data insertion,
querying, and database maintenance operations.
"""

import os
import sqlite3
import contextlib
import random
import fnmatch
import multiprocessing
from time import sleep
from tqdm import tqdm
from datetime import datetime, timedelta
from pathlib import Path
from obspy import UTCDateTime,Stream
from obspy.core.stream import read as streamread
import pandas as pd
from typing import Union, List, Dict, Tuple, Optional, Any

from seed_vault.service.utils import to_timestamp



def stream_to_db_elements(st: Stream) -> List[Tuple[str, str, str, str, str, str]]:
    """
    Convert an ObsPy Stream object to multiple database element tuples, properly handling gaps.
    Creates database elements from a stream, assuming all traces have the same 
    Network-Station-Location-Channel (NSLC) codes (e.g. an SDS file).
    
    Args:
        st: ObsPy Stream object containing seismic traces.
    
    Returns:
        List[Tuple[str, str, str, str, str, str]]: A list of tuples, each containing:
            - network: Network code
            - station: Station code
            - location: Location code
            - channel: Channel code
            - start_time: ISO format start time
            - end_time: ISO format end time
            Returns empty list if stream is empty.
    
    Example:
        >>> stream = obspy.read()
        >>> elements = stream_to_db_element(stream)
        >>> for element in elements:
        ...     network, station, location, channel, start, end = element
    """
    if len(st) == 0:
        print("Warning: Empty stream provided")
        return []
    
    # Sort traces by start time
    st.sort(['starttime'])
    
    # Get NSLC codes from the first trace (assuming all are the same)
    network = st[0].stats.network
    station = st[0].stats.station
    location = st[0].stats.location
    channel = st[0].stats.channel
    
    # Group continuous segments
    elements = []
    current_segment_start = st[0].stats.starttime
    current_segment_end = st[0].stats.endtime
    
    for i in range(1, len(st)):
        # If there's a gap, add the current segment and start a new one
        if st[i].stats.starttime > current_segment_end:
            elements.append((
                network, station, location, channel,
                current_segment_start.isoformat(), current_segment_end.isoformat()
            ))
            current_segment_start = st[i].stats.starttime
        
        # Update the end time of the current segment
        current_segment_end = max(current_segment_end, st[i].stats.endtime)
    
    # Add the final segment
    elements.append((
        network, station, location, channel,
        current_segment_start.isoformat(), current_segment_end.isoformat()
    ))
    
    return elements


def miniseed_to_db_elements(file_path: str) -> Optional[Tuple[str, str, str, str, str, str]]:
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
        return []
    try:
        file = os.path.basename(file_path)
        parts = file.split('.')
        if len(parts) != 7:
            return []  # Skip files that don't match expected format
        
        network, station, location, channel, _, year, dayfolder = parts
        
        # Read the file to get actual start and end times
        st = streamread(file_path, headonly=True)

        db_elements = stream_to_db_elements(st)
    
        return db_elements #this is now a list of tuples
    
    except Exception as e:
        print(f"Error processing file {file_path}: {str(e)}")
        return []


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
        - Files are processed using miniseed_to_db_elements() function
        - After insertion, continuous segments are joined based on gap_tolerance
        - Progress is displayed using tqdm progress bars
        - If newer_than is provided, it's converted to a Unix timestamp for comparison

    Raises:
        RuntimeError: If bulk insertion into database fails
    """

    db_manager = DatabaseManager(db_path)

    # Set to possibly the maximum number of CPUs!
    if num_processes is None or num_processes <= 0:
        num_processes = os.cpu_count()
    
    # Convert newer_than (means to filter only new files) to timestamp
    if newer_than:
        newer_than = to_timestamp(newer_than)

    # Collect all file paths
    file_paths = []

    print("Scanning archive... ")
    for root, dirs, files in os.walk(sds_path,followlinks=True):
        for f in files:
            if any(fnmatch.fnmatch(f, pattern) for pattern in search_patterns):
                file_path = os.path.join(root,f)
                if newer_than is None or os.path.getmtime(file_path) > newer_than:
                    file_paths.append(os.path.join(root, f))
    
    total_files = len(file_paths)
    print(f"Found {total_files} files to process.")
    
    # Process files with or without multiprocessing
    # TODO TODO TODO ensure cross platform compatibility with windows especially
    if num_processes > 1:
        try:
            with multiprocessing.Pool(processes=num_processes) as pool:
                results = list(tqdm(pool.imap(miniseed_to_db_elements, file_paths), 
                              total=total_files, desc="Processing files"))
                to_insert_db = [item for sublist in results for item in sublist]

        except Exception as e:
            print(f"Multiprocessing failed: {str(e)}. Falling back to single-process execution.")
            num_processes = 1
    else:
        to_insert_db = []
        for fp in tqdm(file_paths, desc="Scanning %s..." % sds_path):
            to_insert_db.extend(miniseed_to_db_elements(fp))

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
    now = int(datetime.now().timestamp())
    for fp in file_paths:
        try:
            results = miniseed_to_db_elements(fp)
        except Exception as e:
            print(f"error in miniseed_to_db_elements: {fp}")
            continue
        if results:
            for result in results:
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
    the spans are merged. Uses miniseed_to_db_elements() to parse file metadata.

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
        - Skips files that fail metadata extraction (when miniseed_to_db_elements returns None)

    Examples:
        >>> import sqlite3
        >>> conn = sqlite3.connect('archive.db')
        >>> cursor = conn.cursor()
        >>> files = ['/path/to/IU.ANMO.00.BHZ.mseed', '/path/to/IU.ANMO.00.BHN.mseed']
        >>> populate_database_from_files(cursor, files)
        >>> conn.commit()
    """
    now = int(datetime.now().timestamp())
    for fp in file_paths:
        try:
            results = miniseed_to_db_elements(fp)
        except Exception as e:
            print(f"error in miniseed_to_db_elements: {fp}")
            continue
        
        for result in results:  # Process each tuple in the list
            if not result or len(result) != 6:
                print(f"populate_database_from_files: invalid result: {result}")
            else:
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
 

class DatabaseManager:
    """
    Manages seismic data storage and retrieval using SQLite.

    This class handles database connections, table creation, data insertion,
    and querying for seismic archive and arrival data.

    Attributes:
        db_path (str): Path to the SQLite database file.
    """

    def __init__(self, db_path: str):
        """Initialize DatabaseManager with database path.

        Args:
            db_path: Path where the SQLite database should be created/accessed.
        """
        self.db_path = db_path
        parent_dir = Path(db_path).parent
        parent_dir.mkdir(parents=True, exist_ok=True)
        self.setup_database()

    @contextlib.contextmanager
    def connection(self, max_retries: int = 3, initial_delay: float = 1):
        """
        Context manager for database connections with retry mechanism.

        Args:
            max_retries: Maximum number of connection retry attempts.
            initial_delay: Initial delay between retries in seconds.

        Yields:
            sqlite3.Connection: Database connection object.

        Raises:
            sqlite3.OperationalError: If database connection fails after all retries.
        """
        retry_count = 0
        delay = initial_delay
        
        while retry_count < max_retries:
            try:
                conn = sqlite3.connect(self.db_path, timeout=20)
                # Wise to increase cache_size if your database grows very large / can afford it. mmap seems to be less important
                conn.execute('PRAGMA journal_mode = WAL')
                conn.execute('PRAGMA synchronous = NORMAL')
                conn.execute('PRAGMA cache_size = -128000')  # 128MB
                conn.execute('PRAGMA mmap_size = 256000000')  # 256MB
                conn.execute('PRAGMA temp_store = MEMORY')
                yield conn
                conn.commit()
                return
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e):
                    retry_count += 1
                    if retry_count >= max_retries:
                        print(f"Failed to connect to database after {max_retries} retries.")
                        raise
                    print(f"Database is locked. Retrying in {delay} seconds...")
                    sleep(delay)
                    delay *= 2  # Exponential backoff
                    delay += random.uniform(0, 1)  # Add jitter
                else:
                    raise
            finally:
                if 'conn' in locals():
                    conn.close()

    def setup_database(self):
        """
        Initialize database schema with required tables and indices."""
        with self.connection() as conn:
            cursor = conn.cursor()
            
            # Create archive_data table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS archive_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    network TEXT,
                    station TEXT,
                    location TEXT,
                    channel TEXT,
                    starttime TEXT,
                    endtime TEXT,
                    importtime REAL
                )
            ''')
            
            # Create index for archive_data
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_archive_data 
                ON archive_data (network, station, location, channel, starttime, endtime, importtime)
            ''')
            
            # Create arrival_data table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS arrival_data (
                    resource_id TEXT,
                    e_mag REAL,
                    e_lat REAL,
                    e_lon REAL,
                    e_depth REAL,
                    e_time REAL,
                    s_netcode TEXT,
                    s_stacode TEXT,
                    s_lat REAL,
                    s_lon REAL,
                    s_elev REAL,
                    s_start REAL,
                    s_end REAL,
                    dist_deg REAL,
                    dist_km REAL,
                    azimuth REAL,
                    p_arrival REAL,
                    s_arrival REAL,
                    model TEXT,
                    importtime REAL,
                    PRIMARY KEY (resource_id, s_netcode, s_stacode, s_start)
                )
            ''')

            # For quicker arrival data lookups
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_arrival_by_station_event
                ON arrival_data (resource_id, s_netcode, s_stacode)
            ''')

    def display_contents(
        self, table_name: str, start_time: Union[int, float, datetime, UTCDateTime] = 0,
        end_time: Union[int, float, datetime, UTCDateTime] = 4102444799, limit: int = 100):
        
        """
        Display contents of a specified table within a given time range.

        Args:
            table_name: Name of the table to query ('archive_data' or 'arrival_data').
            start_time: Start time for the query.
            end_time: End time for the query.
            limit: Maximum number of rows to return.
        """
        try:
            start_timestamp = to_timestamp(start_time)
            end_timestamp = to_timestamp(end_time)
        except ValueError as e:
            print(f"Error converting time: {str(e)}")
            return

        with self.connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [col[1] for col in cursor.fetchall()]
            
            query = """
                SELECT * FROM {table_name}
                WHERE importtime BETWEEN ? AND ?
                ORDER BY importtime
                LIMIT ?
            """
            cursor.execute(query, (start_timestamp, end_timestamp, limit))
            
            results = cursor.fetchall()
            
            print(f"\nContents of {table_name} (limited to {limit} rows):")
            print("=" * 80)
            print(" | ".join(columns))
            print("=" * 80)
            for row in results:
                print(" | ".join(str(item) for item in row))
            
            print(f"\nTotal rows: {len(results)}")

    def reindex_tables(self):
        """Reindex both of the tables in our DB"""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("REINDEX TABLE archive_data")
            cursor.execute("REINDEX TABLE arrival_data")

    def vacuum_database(self):
        """Rebuild the database file to reclaim unused space."""
        with self.connection() as conn:
            conn.execute("VACUUM")

    def analyze_table(self, table_name: str):
        """Update table statistics for query optimization.

        Args:
            table_name: Name of the table to analyze.
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"ANALYZE {table_name}")

    def delete_elements(self, table_name: str, 
                       start_time: Union[int, float, datetime, UTCDateTime] = 0,
                       end_time: Union[int, float, datetime, UTCDateTime] = 4102444799) -> int:
        """
        Delete elements from specified table within time range.

        Args:
            table_name: Name of the table ('archive_data' or 'arrival_data').
            start_time: Start time for deletion range.
            end_time: End time for deletion range.

        Returns:
            int: Number of deleted rows.

        Raises:
            ValueError: If table_name is invalid or time format is incorrect.
        """
        if table_name.lower() not in ['archive_data', 'arrival_data']:
            raise ValueError("table_name must be archive_data or arrival_data")

        try:
            start_timestamp = to_timestamp(start_time)
            end_timestamp = to_timestamp(end_time)
        except ValueError as e:
            raise ValueError(f"Invalid time format: {str(e)}")

        with self.connection() as conn:
            cursor = conn.cursor()
            query = """
                DELETE FROM {table_name}
                WHERE importtime >= ? AND importtime <= ?
            """
            cursor.execute(query, (start_timestamp, end_timestamp))
            return cursor.rowcount

    def join_continuous_segments(self, gap_tolerance: float = 30):
        """
        Join continuous data segments in the database.

        Args:
            gap_tolerance: Maximum allowed gap (in seconds) to consider segments continuous.
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, network, station, location, channel, starttime, endtime, importtime
                FROM archive_data
                ORDER BY network, station, location, channel, starttime
            ''')
            
            all_data = cursor.fetchall()
            to_delete = []
            to_update = []
            current_segment = None
            
            for row in all_data:
                id, network, station, location, channel, starttime, endtime, importtime = row
                starttime = UTCDateTime(starttime)
                endtime = UTCDateTime(endtime)
                
                if current_segment is None:
                    current_segment = list(row)
                else:
                    if (network == current_segment[1] and
                        station == current_segment[2] and
                        location == current_segment[3] and
                        channel == current_segment[4] and
                        starttime - UTCDateTime(current_segment[6]) <= gap_tolerance):
                        
                        current_segment[6] = max(endtime, UTCDateTime(current_segment[6])).isoformat()
                        current_segment[7] = max(importtime, current_segment[7]) if importtime and current_segment[7] else None
                        to_delete.append(id)
                    else:
                        to_update.append(tuple(current_segment))
                        current_segment = list(row)
            
            if current_segment:
                to_update.append(tuple(current_segment))
            
            cursor.executemany('''
                UPDATE archive_data
                SET endtime = ?, importtime = ?
                WHERE id = ?
            ''', [(row[6], row[7], row[0]) for row in to_update])
            
            if to_delete:
                for i in range(0, len(to_delete), 500):
                    chunk = to_delete[i:i + 500]
                    cursor.executemany(
                        'DELETE FROM archive_data WHERE id = ?',
                        [(id,) for id in chunk]
                    )

        print(f"\nDatabase cleaned. Deleted {len(to_delete)} rows, updated {len(to_update)} rows.")

    def execute_query(self, query: str) -> Tuple[bool, str, Optional[pd.DataFrame]]:
        """
        Execute an SQL query and return results.

        Args:
            query: SQL query to execute.

        Returns:
            Tuple containing:
                - bool: Whether an error occurred
                - str: Status message or error description
                - Optional[pd.DataFrame]: Results for SELECT queries, None otherwise
        """
        modify_commands = {'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER', 'TRUNCATE'}
        first_word = query.strip().split()[0].upper()
        is_select = first_word == 'SELECT'
        
        try:
            with self.connection() as conn:
                if is_select:
                    df = pd.read_sql_query(query, conn)
                    return False, f"Query executed successfully. {len(df)} rows returned.", df
                else:
                    cursor = conn.cursor()
                    cursor.execute(query)
                    
                    if first_word in modify_commands:
                        return False, f"Query executed successfully. Rows affected: {cursor.rowcount}", None
                    return False, "Query executed successfully.", None
                    
        except Exception as e:
            return True, f"Error executing query: {str(e)}", None

    def bulk_insert_archive_data(self, archive_list: List[Tuple]) -> int:
        """
        Insert multiple archive data records.

        Args:
            archive_list: List of tuples containing archive data records.

        Returns:
            int: Number of inserted records.
        """
        if not archive_list:
            return 0

        with self.connection() as conn:
            cursor = conn.cursor()
            now = int(datetime.now().timestamp())
            archive_list = [tuple(list(ele) + [now]) for ele in archive_list if ele is not None]
            
            cursor.executemany('''
                INSERT OR REPLACE INTO archive_data
                (network, station, location, channel, starttime, endtime, importtime)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', archive_list)
            
            return cursor.rowcount

    def bulk_insert_arrival_data(self, arrival_list: List[Tuple]) -> int:
        """
        Insert multiple arrival data records.

        Args:
            arrival_list: List of tuples containing arrival data records.

        Returns:
            int: Number of inserted records.
        """
        if not arrival_list:
            return 0

        with self.connection() as conn:
            cursor = conn.cursor()
            columns = ['resource_id', 'e_mag', 'e_lat', 'e_lon', 'e_depth', 'e_time',
                      's_netcode', 's_stacode', 's_lat', 's_lon', 's_elev', 's_start', 's_end',
                      'dist_deg', 'dist_km', 'azimuth', 'p_arrival', 's_arrival', 'model',
                      'importtime']
            
            placeholders = ', '.join(['?' for _ in columns])
            query = f'''
                INSERT OR REPLACE INTO arrival_data
                ({', '.join(columns)})
                VALUES ({placeholders})
            '''
            
            now = int(datetime.now().timestamp())
            arrival_list = [tuple(list(ele) + [now]) for ele in arrival_list]
            cursor.executemany(query, arrival_list)
            
            return cursor.rowcount

    def check_data_existence(
        self, netcode: str, stacode: str, location: str, 
        channel: str, starttime: str, endtime: str) -> bool:
        """
        Run a simple check to see if a db element exists for a trace

        Args:
            db_manager (DatabaseManager): Database manager instance
            network (str): Network code
            station (str): Station code
            location (str): Location code
            channel (str): Channel code
            start/endtime (str): Time in iso
        
        Returns:
            bool: True if data exists for the specified parameters, False otherwise
        """

        time_point = datetime.fromisoformat(starttime) + timedelta(seconds=5) # just 5 seconds in is fine
        
        # Use the connection context manager from the DatabaseManager
        with self.connection() as conn:
            cursor = conn.cursor()
            
            # Query to check if any record spans the given time point
            query = """
                SELECT COUNT(*) FROM archive_data
                WHERE network = ? 
                AND station = ? 
                AND location = ? 
                AND channel = ?
                AND starttime <= ?
                AND endtime >= ?
            """
            
            cursor.execute(query, (netcode, stacode, location, channel, starttime, endtime))
            count = cursor.fetchone()[0]
            
            return count > 0        

    def get_arrival_data(
    self, resource_id: str, netcode: str, stacode: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve complete arrival data for a specific event and station.

        Args:
            resource_id: Unique identifier for the seismic event.
            netcode: Network code for the station.
            stacode: Station code.

        Returns:
            Optional[Dict[str, Any]]: Dictionary containing all arrival data fields for the
                specified event and station, or None if no matching record is found.
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM arrival_data 
                WHERE resource_id = ? AND s_netcode = ? AND s_stacode = ?
            ''', (resource_id, netcode, stacode))
            result = cursor.fetchone()
            if result:
                columns = [description[0] for description in cursor.description]
                return dict(zip(columns, result))
        return None

    def get_stations_for_event(self, resource_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all station data associated with a specific seismic event.

        Args:
            resource_id: Unique identifier for the seismic event.

        Returns:
            List[Dict[str, Any]]: List of dictionaries containing arrival data for all
                stations that recorded the event. Returns empty list if no stations found.
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM arrival_data 
                WHERE resource_id = ?
            ''', (resource_id,))
            results = cursor.fetchall()
            if results:
                columns = [description[0] for description in cursor.description]
                return [dict(zip(columns, result)) for result in results]
        return []

    def get_events_for_station(self, netcode: str, stacode: str) -> List[Dict[str, Any]]:
        """
        Retrieve all seismic events recorded by a specific station.

        Args:
            netcode: Network code for the station.
            stacode: Station code.

        Returns:
            List[Dict[str, Any]]: List of dictionaries containing arrival data for all
                events recorded by the station. Returns empty list if no events found.
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM arrival_data 
                WHERE s_netcode = ? AND s_stacode = ?
            ''', (netcode, stacode))
            results = cursor.fetchall()
            if results:
                columns = [description[0] for description in cursor.description]
                return [dict(zip(columns, result)) for result in results]
        return []

    def fetch_arrivals_distances(
    self, resource_id: str, netcode: str, stacode: str
    ) -> Optional[Tuple[float, float, float, float, float]]:    
        """
        Retrieve arrival times and distance metrics for a specific event and station.

        Args:
            resource_id: Unique identifier for the seismic event.
            netcode: Network code for the station.
            stacode: Station code.

        Returns:
            Optional[Tuple[float, float, float, float, float]]: Tuple containing
                (p_arrival, s_arrival, dist_km, dist_deg, azimuth), where:
                - p_arrival: P wave arrival time (timestamp)
                - s_arrival: S wave arrival time (timestamp)
                - dist_km: Distance in kilometers
                - dist_deg: Distance in degrees
                - azimuth: Azimuth angle from event to station
                Returns None if no matching record is found.
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT p_arrival, s_arrival, dist_km, dist_deg, azimuth 
                FROM arrival_data 
                WHERE resource_id = ? AND s_netcode = ? AND s_stacode = ?
            ''', (resource_id, netcode, stacode))
            result = cursor.fetchone()
            if result:
                return (result[0], result[1], result[2], result[3], result[4])
        return None
