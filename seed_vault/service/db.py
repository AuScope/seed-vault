"""
Database management module for the SEED-vault archive

This module provides a DatabaseManager class for handling seismic data storage in SQLite,
including archive data and arrival data. It implements connection management, data insertion,
querying, and database maintenance operations.
"""

import sqlite3
import contextlib
import time
import random
import datetime
from pathlib import Path
from obspy import UTCDateTime
import pandas as pd
from typing import Union, List, Dict, Tuple, Optional, Any

def to_timestamp(time_obj: Union[int, float, datetime.datetime, UTCDateTime]) -> float:
    """
    Convert various time objects to Unix timestamp.

    Args:
        time_obj: Time object to convert. Can be int/float timestamp, datetime, or UTCDateTime.

    Returns:
        float: Unix timestamp.

    Raises:
        ValueError: If the time object type is not supported.
    """
    if isinstance(time_obj, (int, float)):
        return float(time_obj)
    elif isinstance(time_obj, datetime.datetime):
        return time_obj.timestamp()
    elif isinstance(time_obj, UTCDateTime):
        return time_obj.timestamp
    else:
        raise ValueError(f"Unsupported time type: {type(time_obj)}")

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
                    time.sleep(delay)
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
                    event_id TEXT,
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
                    PRIMARY KEY (event_id, s_netcode, s_stacode, s_start)
                )
            ''')

    def display_contents(self, table_name: str, start_time: Union[int, float, datetime.datetime, UTCDateTime] = 0,
                        end_time: Union[int, float, datetime.datetime, UTCDateTime] = 4102444799, limit: int = 100):
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

    def reindex_archive_data(self):
        """Rebuild the index on archive_data table."""
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("REINDEX idx_archive_data")

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
                       start_time: Union[int, float, datetime.datetime, UTCDateTime] = 0,
                       end_time: Union[int, float, datetime.datetime, UTCDateTime] = 4102444799) -> int:
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

        print(f"Database cleaned. Deleted {len(to_delete)} rows, updated {len(to_update)} rows.")

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
            now = int(datetime.datetime.now().timestamp())
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
            columns = ['event_id', 'e_mag', 'e_lat', 'e_lon', 'e_depth', 'e_time',
                      's_netcode', 's_stacode', 's_lat', 's_lon', 's_elev', 's_start', 's_end',
                      'dist_deg', 'dist_km', 'azimuth', 'p_arrival', 's_arrival', 'model',
                      'importtime']
            
            placeholders = ', '.join(['?' for _ in columns])
            query = f'''
                INSERT OR REPLACE INTO arrival_data
                ({', '.join(columns)})
                VALUES ({placeholders})
            '''
            
            now = int(datetime.datetime.now().timestamp())
            arrival_list = [tuple(list(ele) + [now]) for ele in arrival_list]
            cursor.executemany(query, arrival_list)
            
            return cursor.rowcount

    def get_arrival_data(self, event_id: str, netcode: str, stacode: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve complete arrival data for a specific event and station.

        Args:
            event_id: Unique identifier for the seismic event.
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
                WHERE event_id = ? AND s_netcode = ? AND s_stacode = ?
            ''', (event_id, netcode, stacode))
            result = cursor.fetchone()
            if result:
                columns = [description[0] for description in cursor.description]
                return dict(zip(columns, result))
        return None

    def get_stations_for_event(self, event_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all station data associated with a specific seismic event.

        Args:
            event_id: Unique identifier for the seismic event.

        Returns:
            List[Dict[str, Any]]: List of dictionaries containing arrival data for all
                stations that recorded the event. Returns empty list if no stations found.
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM arrival_data 
                WHERE event_id = ?
            ''', (event_id,))
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

    def fetch_arrivals(self, event_id: str, netcode: str, stacode: str) -> Optional[Tuple[float, float]]:
        """
        Retrieve P and S wave arrival times for a specific event and station.

        Args:
            event_id: Unique identifier for the seismic event.
            netcode: Network code for the station.
            stacode: Station code.

        Returns:
            Optional[Tuple[float, float]]: Tuple containing (p_arrival, s_arrival) times
                as timestamps, or None if no matching record is found.
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT p_arrival, s_arrival 
                FROM arrival_data 
                WHERE event_id = ? AND s_netcode = ? AND s_stacode = ?
            ''', (event_id, netcode, stacode))
            result = cursor.fetchone()
            if result:
                return (result[0], result[1])
        return None

    def fetch_arrivals_distances(self, event_id: str, netcode: str, stacode: str) -> Optional[Tuple[float, float, float, float, float]]:
        """
        Retrieve arrival times and distance metrics for a specific event and station.

        Args:
            event_id: Unique identifier for the seismic event.
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
                WHERE event_id = ? AND s_netcode = ? AND s_stacode = ?
            ''', (event_id, netcode, stacode))
            result = cursor.fetchone()
            if result:
                return (result[0], result[1], result[2], result[3], result[4])
        return None
