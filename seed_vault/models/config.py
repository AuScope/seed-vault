import re
from pydantic import BaseModel
import json
from typing import IO, Dict, Optional, List, Tuple, Union, Any
from datetime import date, timedelta, datetime
from enum import Enum
import os
import configparser
from configparser import ConfigParser
import pickle

from obspy import UTCDateTime

from .common import RectangleArea, CircleArea, StatusHandler
from .url_mapping import UrlMappings
from seed_vault.enums.config import DownloadType, WorkflowType, GeoConstraintType, Levels


# Convert start and end times to datetime
def parse_time(time_str):
    """
    The function `parse_time` attempts to parse a given time string in various formats and return it in
    ISO format.
    
    Args:
      time_str: The date-time in string format. Some acceptable input formats are:
                '2014,2,1' | '2014001' | '2014,3,2,0,0,5'
    
    Returns:
      The `parse_time` function is attempting to parse a time string using different formats. If
      successful, it returns the parsed time in ISO format. If parsing fails for all formats, it returns
      `None`.
    """
    if not time_str:
        return None

    try:
        return UTCDateTime(time_str).isoformat()
    except:
        time_formats = [
            '%Y,%m,%d',         # Format like '2014,2,1'
            '%Y%j',             # Julian day format like '2014001'
            '%Y,%m,%d,%H,%M,%S' # Format with time '2014,3,2,0,0,5'
        ]
        for time_format in time_formats:
            try:
                return datetime.strptime(time_str, time_format)
            except ValueError:
                continue
    return None
    
def safe_add_to_config(config, section, key, value):
    """
    The function `safe_add_to_config` safely adds key-value pairs to a configuration dictionary,
    handling any exceptions that may occur.
    
    Args:
      config: Config is a dictionary that stores configuration settings. It typically has sections as
              keys, where each section contains key-value pairs representing specific configuration 
              settings. 
              
      section: Section refers to a specific section within the configuration file 
               where the key-value pair will be added. It helps organize and categorize different 
               settings or options within the configuration file.

      key: The `key` parameter in the `safe_add_to_config` function refers to the key of the key-value
           pair that you want to add to the configuration. It is used to uniquely identify the value 
           associated with it within a specific section of the configuration.

      value: Value is the data that you want to add to the configuration file under the specified
             section and key. It could be a string, integer, boolean, or any other data type that 
             you want to store in the configuration.
    """
    try:
        config[section][key] = convert_to_str(value)
    except Exception as e:
        print(f"Failed to add {key} to {section}: {e}")

def convert_to_str(val):
    """
    The function `convert_to_str` converts various types of values to strings, handling different cases
    and providing error handling.
    
    Args:
      val: The `convert_to_str` function takes a value `val` as input and attempts to convert it to a
           string representation. It handles different types of values such as `None`, `Enum`, strings,
           integers, floats, booleans, objects with `__str__` method, and other unsupported
    
    Returns:
      The function `convert_to_str` returns a string representation of the input value `val`. It handles
      different types of input values and converts them to a string using various methods based on their
      type. If the conversion fails, it catches the exception and returns an empty string.
    """
    try:
        if val is None:
            return ''  # Convert None to empty string
        if isinstance(val, Enum):
            return str(val.value)  # Convert Enum values to string
        if isinstance(val, (str, int, float, bool)):
            return str(val)  # Convert valid types to string
        if hasattr(val, '__str__'):
            return str(val)  # Use __str__ for objects
        return repr(val)  # Use repr for unsupported objects
    except Exception as e:
        print(f"Error converting value {val}: {e}")
        return ''  # Return empty string if conversion fails
            
class ProcessingConfig(BaseModel):
    """
    This class defines a configuration for processing with default values for the number of processes,
    gap tolerance, and logging.
    """
    num_processes: Optional    [  int         ] | None = 4
    gap_tolerance: Optional    [  int         ] | None = 60
    logging      : Optional    [  str         ] = None


class AuthConfig(BaseModel):
    """
    The `AuthConfig` class defines attributes for network.station.location.channel code, username, and
    password.
    """
    nslc_code: str  # network.station.location.channel code
    username: str
    password: str


class SeismoQuery(BaseModel):
    """
    This Python class `SeismoQuery` represents a seismic query params with properties for network, station,
    location, channel, start time, and end time, along with methods to convert combined network and
    station string to individual properties.
    """
    network : Optional[str] = None
    station : Optional[str] = None
    location: Optional[str] = None
    channel : Optional[str] = None
    starttime: Optional[datetime] = None
    endtime: Optional[datetime] = None

    def __init__(self, cmb_str_n_s=None, **data):
        super().__init__(**data) 
        if cmb_str_n_s:
            self.cmb_str_n_s_to_props(cmb_str_n_s)

    @property
    def cmb_str(self):
        cmb_str = ''
        if self.network:
            cmb_str += f"{self.network}."
        if self.station:
            cmb_str += f"{self.station}."
        if self.location:
            cmb_str += f"{self.location}."
        if self.channel:
            cmb_str += f"{self.channel}."
        
        if cmb_str.endswith("."):
            cmb_str = cmb_str[:-1]

        return cmb_str
    
    def cmb_str_n_s_to_props(self, cmb_n_s):
        lst_split = cmb_n_s.split(".")
        if len(lst_split) < 2:
            raise ValueError(f"Input station code is malformed: {cmb_n_s}")
        
        for item in lst_split[0:2]:
            if item == "":  # Add other validation checks here
                raise ValueError(f"Input station code is malformed: {cmb_n_s}")
        
        setattr(self, 'network', lst_split[0])
        setattr(self, 'station', lst_split[1])

        if len(lst_split) >= 3:
            setattr(self, 'location', lst_split[2])
        else:
            setattr(self, 'location', None)

        if len(lst_split) >= 4:
            setattr(self, 'channel', lst_split[3])
        else:
            setattr(self, 'channel', None)
        

class DateConfig(BaseModel):
    """
    This class defines a DateConfig with optional start and end times, as well as optional before and
    after time definition used for events.
    """
    start_time  : Optional[Union[date, Any] ] = date.today() - timedelta(days=7)
    end_time    : Optional[Union[date, Any] ] = date.today()
    start_before: Optional[Union[date, Any] ] =      None
    start_after : Optional[Union[date, Any] ] =      None
    end_before  : Optional[Union[date, Any] ] =      None
    end_after   : Optional[Union[date, Any] ] =      None


class WaveformConfig(BaseModel):
    """
    The `WaveformConfig` class defines a data model with optional fields for configuring waveform data
    requests, with a method to reset all fields to their default values.
    """
    client           : Optional     [str] = "EARTHSCOPE"
    channel_pref     : Optional     [str] = None
    location_pref    : Optional     [str] = None
    force_redownload : Optional    [bool] = False

    days_per_request : Optional     [int]             = 1

    def set_default(self):
        """Resets all fields to their default values."""
        self.__fields_set__.clear()
        for field_name, field in self.__fields__.items():
            setattr(self, field_name, field.get_default())

class GeometryConstraint(BaseModel):
    """
    The `GeometryConstraint` class defines a geometry constraint with a specified type and coordinates,
    automatically determining the constraint type based on the provided coordinates.
    """
    geo_type: Optional[GeoConstraintType] = GeoConstraintType.NONE
    coords: Optional[Union[RectangleArea, CircleArea]] = None

    def __init__(self, **data):
        super().__init__(**data)
        if isinstance(self.coords, RectangleArea):
            self.geo_type = GeoConstraintType.BOUNDING
        elif isinstance(self.coords, CircleArea):
            self.geo_type = GeoConstraintType.CIRCLE
        else:
            self.geo_type = GeoConstraintType.NONE


class StationConfig(BaseModel):
    """
    The `StationConfig` class defines configuration settings for querying seismic stations.

    This class allows users to specify parameters such as the seismic network, station selection, 
    and geographical constraints while retrieving station metadata.

    Attributes:
        client (Optional[str]): The FDSN client for retrieving station metadata. Defaults to `"EARTHSCOPE"`.
        force_stations (Optional[List[SeismoQuery]]): A list of stations to forcefully include in the query.
        exclude_stations (Optional[List[SeismoQuery]]): A list of stations to exclude from the query.
        date_config (DateConfig): The date range for station availability queries.
        local_inventory (Optional[str]): Path to a local station inventory file, if applicable.
        network (Optional[str]): The seismic network code (e.g., `"IU"`, `"NE"`) to filter stations.
        station (Optional[str]): The station code to filter results.
        location (Optional[str]): The location code for further filtering.
        channel (Optional[str]): The channel code (e.g., `"BHZ"`, `"HHZ"`) to specify station channels.
        highest_samplerate_only (bool): Whether to select only the station with the highest sample rate. Defaults to `False`.
        selected_invs (Optional[Any]): A list of pre-selected inventories.
        geo_constraint (Optional[List[GeometryConstraint]]): Geospatial constraints to filter stations.
        include_restricted (bool): Whether to include restricted (non-public) stations. Defaults to `False`.
        level (Levels): The level of station metadata detail to retrieve. Defaults to `Levels.CHANNEL`.
    """
    client             : Optional   [ str] = "EARTHSCOPE"
    force_stations     : Optional   [ List          [SeismoQuery]] = []
    exclude_stations   : Optional   [ List          [SeismoQuery]] = []
    date_config        : DateConfig                                = DateConfig(
        start_time=(datetime.now() - timedelta(days=30)).isoformat(),
        end_time=datetime.now().isoformat()
    )
    local_inventory    : Optional   [ str           ] = None
    network            : Optional   [ str           ] = "IU"
    station            : Optional   [ str           ] = "*"
    location           : Optional   [ str           ] = "*"
    channel            : Optional   [ str           ] = "?H?,?N?"
    highest_samplerate_only : bool = False
    selected_invs      : Optional   [Any] = None
    geo_constraint     : Optional   [ List          [GeometryConstraint]] = None
    include_restricted : bool       = False
    level              : Levels     = Levels        .CHANNEL

    class Config:
        json_encoders = {
            Any: lambda v: None  
        }
        exclude = {"selected_invs"}

    def set_default(self):
        """Resets all fields to their default values."""
        self.__fields_set__.clear()
        for field_name, field in self.__fields__.items():
            setattr(self, field_name, field.get_default())                 


    # TODO: check if it makes sense to use SeismoLocation instead of separate
    # props.
    # seismo_location: List[SeismoLocation] = None

    # FIXME: for now we just assume all values are 
    # given in one string separated with "," -> e.g.
    # channel = CH,HH,BH,EH


class EventConfig(BaseModel):
    """
    The `EventConfig` class defines parameters for configuring earthquake event queries with default
    values. It is designed to store criteria for filtering earthquake events.

    Attributes:
        client (Optional[str]): The FDSN client to use for retrieving earthquake data. Defaults to `"EARTHSCOPE"`.
        date_config (DateConfig): The date range for querying earthquake events.
        model (str): The seismic velocity model to use. Defaults to `"IASP91"`.
        min_depth (float): The minimum earthquake depth in kilometers. Defaults to `-5.0`.
        max_depth (float): The maximum earthquake depth in kilometers. Defaults to `1000.0`.
        min_magnitude (float): The minimum earthquake magnitude. Defaults to `5.5`.
        max_magnitude (float): The maximum earthquake magnitude. Defaults to `10.0`.
        min_radius (float): The minimum distance from the event in degrees. Defaults to `30.0`.
        max_radius (float): The maximum distance from the event in degrees. Defaults to `90.0`.
        before_p_sec (int): The number of seconds before the P-wave arrival. Defaults to `10`.
        after_p_sec (int): The number of seconds after the P-wave arrival. Defaults to `130`.
        include_all_origins (bool): Whether to include all origins of an event. Defaults to `False`.
        include_all_magnitudes (bool): Whether to include all magnitude values for an event. Defaults to `False`.
        include_arrivals (bool): Whether to include phase arrivals in the results. Defaults to `False`.
        local_catalog (Optional[str]): The local earthquake catalog name, if applicable.
        eventtype (Optional[str]): The type of earthquake event (e.g., "earthquake", "explosion").
        catalog (Optional[str]): The name of the earthquake catalog used for querying events.
        contributor (Optional[str]): The name of the contributor providing the earthquake data.
        updatedafter (Optional[str]): The UTC timestamp indicating the last update time for event selection.
        limit (Optional[str]): The maximum number of events to retrieve.
        offset (Optional[str]): The offset for paginated earthquake data retrieval.
        selected_catalogs (Optional[Any]): A list of user-selected earthquake catalogs.
        geo_constraint (Optional[List[GeometryConstraint]]): Geospatial constraints on earthquake events.
    """
    client              : Optional   [str] = "EARTHSCOPE"
    date_config         : DateConfig                 = DateConfig(
        start_time=(datetime.now() - timedelta(days=30)).isoformat(),        
        end_time=datetime.now().isoformat()
    )
    model               : str = 'IASP91'
    min_depth           : float = -5.0
    max_depth           : float = 1000.0
    min_magnitude       : float = 5.5
    max_magnitude       : float = 10.0
    min_radius          : float = 30.0
    max_radius          : float = 90.0
    before_p_sec        : int = 10
    after_p_sec         : int = 130
    include_all_origins : bool = False
    include_all_magnitudes: bool = False
    include_arrivals    : bool = False
    local_catalog       : Optional[str] = None
    eventtype           : Optional[str] = None
    catalog             : Optional[str] = None
    contributor         : Optional[str] = None
    updatedafter        : Optional[str] = None #this is a UTCDateTime object fwiw
    limit               : Optional[str] = None
    offset              : Optional[str] = None

    selected_catalogs   : Optional[Any] = None

    geo_constraint      : Optional[List[GeometryConstraint]] = None

    class Config:
        json_encoders = {
            Any: lambda v: None  
        }
        exclude = {"selected_catalogs"}

    def set_default(self):
        """Resets all fields to their default values."""
        self.__fields_set__.clear()
        for field_name, field in self.__fields__.items():
            setattr(self, field_name, field.get_default())      


class PredictionData(BaseModel):
    """
    The `PredictionData` class stores predicted arrival times of seismic waves at a given station.

    This class represents the association between an event and a station, including estimated 
    P-wave and S-wave arrival times.

    Attributes:
        resource_id (str): The unique identifier for the seismic event.
        station_id (str): The identifier of the seismic station where arrivals are recorded.
        p_arrival (datetime): The predicted arrival time of the primary (P) wave.
        s_arrival (datetime): The predicted arrival time of the secondary (S) wave.
    """
    resource_id: str
    station_id: str
    p_arrival: datetime
    s_arrival: datetime

class SeismoLoaderSettings(BaseModel):
    """
    The `SeismoLoaderSettings` class defines configuration settings for managing seismic data retrieval, 
    processing, and storage. It provides attributes to control how seismic waveforms, station metadata, 
    and event data are handled.

    This class also includes methods for configuring download types, reading settings from a configuration 
    file, managing authentication, and persisting settings to disk.

    Attributes:
        sds_path (str): The directory path for the Seismic Data Structure (SDS). Defaults to `data/SDS`.
        db_path (str): The database file path for tracking downloaded data. Defaults to `data/database.sqlite`.
        download_type (DownloadType): The type of download to perform (e.g., event-based or continuous).
        selected_workflow (WorkflowType): The selected workflow type (e.g., event-based, station-based).
        processing (ProcessingConfig): Configuration settings for data processing. Defaults to `None`.
        client_url_mapping (Optional[UrlMappings]): A mapping of client URLs for data retrieval.
        extra_clients (Optional[dict]): A dictionary of additional clients for querying seismic data.
        auths (Optional[List[AuthConfig]]): A list of authentication configurations.
        waveform (WaveformConfig): Configuration for waveform retrieval. Defaults to `None`.
        station (StationConfig): Configuration for station metadata retrieval. Defaults to `None`.
        event (EventConfig): Configuration for event data retrieval. Defaults to `None`.
        predictions (Dict[str, PredictionData]): A dictionary mapping event-station pairs to arrival time predictions.
        status_handler (StatusHandler): A handler for tracking status messages and errors.

    Methods:
        set_download_type_from_workflow():
            Sets the `download_type` attribute based on the selected workflow.
        
        from_cfg_file(cls, cfg_source: Union[str, IO]) -> "SeismoLoaderSettings":
            Loads and initializes a `SeismoLoaderSettings` instance from a configuration file.

        add_prediction(resource_id: str, station_id: str, p_arrival: datetime, s_arrival: datetime):
            Adds a predicted P-wave and S-wave arrival time for a given event and station.

        get_prediction(resource_id: str, station_id: str) -> Optional[PredictionData]:
            Retrieves the predicted arrival time for a given event and station.

        to_pickle(pickle_path: str) -> None:
            Serializes the `SeismoLoaderSettings` instance to a pickle file.

        from_pickle_file(cls, pickle_path: str) -> "SeismoLoaderSettings":
            Loads a `SeismoLoaderSettings` instance from a pickle file.
    """
    sds_path          : str                                   = "data/SDS"
    db_path           : str                                   = "data/database.sqlite"
    download_type     : DownloadType                          = DownloadType.EVENT
    selected_workflow : WorkflowType                          = WorkflowType.EVENT_BASED
    processing        : ProcessingConfig                      = None
    client_url_mapping: Optional[UrlMappings]                 = UrlMappings()
    extra_clients     : Optional[dict]                        = {}
    auths             : Optional        [List[AuthConfig]]    = []
    waveform          : WaveformConfig                        = None
    station           : StationConfig                         = None
    event             : Optional[EventConfig]                 = None
    predictions       : Dict            [str, PredictionData] = {}
    status_handler    : StatusHandler                         = StatusHandler()


    @classmethod
    def create_default(cls):
        """Creates an instance of SeismoLoaderSettings with default values."""

        station_instance = StationConfig()
        station_instance.set_default()

        event_instance = EventConfig()
        event_instance.set_default()

        return cls(
            sds_path='data/SDS',
            db_path='data/database.sqlite',
            download_type=DownloadType.EVENT,
            selected_workflow=WorkflowType.EVENT_BASED,
            processing=ProcessingConfig(
                num_processes=2,
                gap_tolerance=60,
            ),
            client_url_mapping=UrlMappings(),
            extra_clients={},
            auths=[],
            waveform=WaveformConfig(), 
            station=station_instance,  
            event=event_instance,      
            predictions={},
            status_handler=StatusHandler(),
        )
    
    def set_download_type_from_workflow(self):
        """
        Sets the download type based on the selected workflow.

        If `selected_workflow` is `EVENT_BASED` or `STATION_BASED`, sets `download_type` to `EVENT`.
        If `selected_workflow` is `CONTINUOUS`, sets `download_type` to `CONTINUOUS`.
        """
        if (
            self.selected_workflow == WorkflowType.EVENT_BASED or
            self.selected_workflow == WorkflowType.STATION_BASED
        ):
            self.download_type = DownloadType.EVENT

        if (self.selected_workflow == WorkflowType.CONTINUOUS):
            self.download_type = DownloadType.CONTINUOUS

    @classmethod
    def _check_val(cls, val, default_val, val_type: str = "int", return_empty_str: bool = False):
        if val is not None and not isinstance(val, str):
            return val
        
        if val is None or val.strip().lower() == 'none':
            return default_val
        
        # For cases where user purposedly is passing empty string
        if val.strip() == '':
            if return_empty_str:
                return ''
            return default_val

        else:            
            if val_type == "int":
                return int(val)
            if val_type == "float":
                return float(val)
            return val
        

    @classmethod
    def _is_none(cls, val):
        if val is None or isinstance(val, str): 
            if val.strip() == '' or val.strip().lower() == 'none':
                return True
        return False
            
    @classmethod
    def from_cfg_file(cls, cfg_source: Union[str, IO]) -> "SeismoLoaderSettings":
        """
        Loads a `SeismoLoaderSettings` instance from a configuration file.

        Args:
            cfg_source (Union[str, IO]): The path to the configuration file or a file-like object.

        Returns:
            SeismoLoaderSettings: A populated instance of the class.
        """
        status_handler= StatusHandler()       
        config = configparser.ConfigParser()
        config.optionxform = str

        # Load configuration file
        cls._load_config_file(cfg_source, config)


        # Parse sections
        sds_path = cls._parse_sds_section(config, status_handler)
        db_path = cls._parse_database_section(config, sds_path, status_handler)
        processing_config, download_type = cls._parse_processing_section(config, status_handler)
        lst_auths = cls._parse_auth_section(config, status_handler)
        waveform = cls._parse_waveform_section(config, status_handler)
        station_config = cls._parse_station_section(config, status_handler)
        event_config = cls._parse_event_section(config, status_handler, download_type)

        # status_handler.display()


        # Return the populated SeismoLoaderSettings
        return cls(
            sds_path=sds_path,
            db_path=db_path,
            download_type=download_type,
            processing=processing_config,
            auths=lst_auths,
            waveform=waveform,
            station=station_config,
            event=event_config,
            status_handler =status_handler
        )
    
    @classmethod
    def _load_config_file(cls, cfg_source, config):
        if isinstance(cfg_source, str):
            cfg_path = os.path.abspath(cfg_source)
            if not os.path.exists(cfg_path):
                raise ValueError(f"File not found in the following path: {cfg_path}")
            config.read(cfg_path)
        else:
            try:
                config.read_file(cfg_source)
            except Exception as e:
                raise ValueError(f"Failed to read configuration file: {str(e)}")

    @classmethod
    def _parse_sds_section(cls, config, status_handler ):
        try:
            sds_path = config.get('SDS', 'sds_path', fallback=None)
            if not sds_path:
                sds_path = "data/SDS"
                status_handler.add_warning("input_parameters" , "'sds_path' is missing in the [SDS] section. Using default value: 'data/SDS'.")
            return sds_path
        except Exception as e:
            status_handler.add_error("input_parameters" , f"Error parsing [SDS] section: {str(e)}")
            return None            

    @classmethod
    def _parse_database_section(cls, config, sds_path, status_handler):
        try:
            db_path = config.get('DATABASE', 'db_path', fallback=None).strip()
            if not db_path:
                db_path = f'{sds_path}/database.sqlite'
                status_handler.add_warning("input_parameters", f": 'db_path' is missing or empty in the [DATABASE] section. Using default value: '{db_path}'.")
            return db_path
        except Exception as e:
            status_handler.add_error("input_parameters", f"Error parsing [DATABASE] section: {str(e)}")
            return None
                    
    @classmethod
    def _parse_processing_section(cls, config, status_handler):
        # Parse num_processes
        num_processes = config.get('PROCESSING', 'num_processes', fallback=None)
        try:
            num_processes = cls._check_val(num_processes, 2, "int")
        except ValueError:
            num_processes = 2  # Default value
            status_handler.add_warning("input_parameters", "'num_processes' is missing or invalid in the [PROCESSING] section. Using default value: '2'.")

        # Parse gap_tolerance
        gap_tolerance = config.get('PROCESSING', 'gap_tolerance', fallback=None)
        try:
            gap_tolerance = cls._check_val(gap_tolerance, 60, "int")
        except ValueError:
            gap_tolerance = 60  # Default value
            status_handler.add_warning("input_parameters", "'gap_tolerance' is missing or invalid in the [PROCESSING] section. Using default value: '60'.")

        # Parse and validate download_type
        download_type_str = config.get('PROCESSING', 'download_type', fallback='').strip().lower()
        if download_type_str not in DownloadType._value2member_map_:
            status_handler.add_warning("input_parameters", f"Invalid download_type '{download_type_str}' found in config. Defaulting to 'event'.")
            download_type_str = DownloadType.EVENT.value  # Default to 'event'
        download_type = DownloadType(download_type_str)

        # Return the ProcessingConfig object
        return ProcessingConfig(
            num_processes=num_processes,
            gap_tolerance=gap_tolerance,
        ), download_type


    @classmethod
    def _parse_auth_section(cls, config, status_handler ):
        try:
            if 'AUTH' not in config:
                return []
            
            credentials = list(config['AUTH'].items())
            return [
                AuthConfig(nslc_code=nslc, username=cred.split(':')[0], password=cred.split(':')[1])
                for nslc, cred in credentials
            ]
        except Exception as e:
            status_handler.add_error("input_parameters", f"Error parsing [AUTH] section: {str(e)}")
            return []
        

    @classmethod
    def _parse_waveform_section(cls, config, status_handler ):
        waveform_section = 'WAVEFORM'
        if not config.has_section(waveform_section):
            status_handler.add_error("input_parameters", f"The [{waveform_section}] section is missing in the configuration file.")

        client = cls._parse_param(
            config=config,
            section=waveform_section,
            key='client',
            default="EARTHSCOPE",
            status_handler =status_handler,
            error_message=f"'client' is missing in the [{waveform_section}] section. Specify the client for station data retrieval.",
            warning_message=f"'client' is empty in the [{waveform_section}] section. Defaulting to 'EARTHSCOPE'.",
            validation_fn=lambda x: bool(x.strip())  # Ensure the value is not empty after stripping
        )
        days_per_request = cls._parse_param(
            config=config,
            section=waveform_section,
            key="days_per_request",
            default=1,
            validation_fn=lambda x: x.isdigit() and int(x) > 0,  # Ensure it's a positive integer
            status_handler=status_handler,
            error_message=f"'days_per_request' is missing or invalid in the [{waveform_section}] section.",
            warning_message=f"'days_per_request' is empty in the [{waveform_section}] section. Using default value: 1.",
        )

        channel_pref = config.get(waveform_section, 'channel_pref', fallback='').strip()
        location_pref = config.get(waveform_section, 'location_pref', fallback='').strip()
        # channel_pref = cls.parse_optional (config.get(waveform_section, 'channel_pref', fallback=None))
        # location_pref =cls.parse_optional(config.get(waveform_section, 'location_pref', fallback=None))

        return WaveformConfig(
            client=client,
            channel_pref=channel_pref,
            location_pref=location_pref,
            days_per_request=days_per_request,
        )
            
    @classmethod
    def _parse_station_section(cls, config, status_handler):
        station_section = 'STATION'
        if not config.has_section(station_section):
            status_handler.add_error("input_parameters", f"The [{station_section}] section is missing in the configuration file. Please provide station details.")
        
        station_client = cls._parse_param(
            config=config,
            section=station_section,
            key='client',
            default="EARTHSCOPE",
            status_handler =status_handler,
            error_message=f"'client' is missing in the [{station_section}] section. Specify the client for station data retrieval.",
            warning_message=f"'client' is empty in the [{station_section}] section. Defaulting to 'EARTHSCOPE'.",
            validation_fn=lambda x: bool(x.strip())  # Ensure the value is not empty after stripping
        )

        network = cls._parse_param(
            config=config,
            section=station_section,
            key='network',
            default="IU",
            status_handler =status_handler,
            error_message=f"'network' is missing in the [{station_section}] section. Please specify a network.",
            warning_message=f"'network' is empty in the [{station_section}] section. Defaulting to '_GSN'."
        )

        station = cls._parse_param(
            config=config,
            section=station_section,
            key='station',
            default="*",
            status_handler =status_handler,
            error_message=f"'station' is missing in the [{station_section}] section. Please specify a station.",
            warning_message=f"'station' is empty in the [{station_section}] section. Defaulting to '*'."
        )

        location = cls._parse_param(
            config=config,
            section=station_section,
            key='location',
            default="*",
            status_handler =status_handler,
            error_message=f"'location' is missing in the [{station_section}] section. Please specify a location.",
            warning_message=f"'location' is empty in the [{station_section}] section. Defaulting to '*'."
        )

        channel = cls._parse_param(
            config=config,
            section=station_section,
            key='channel',
            default="?H?,?N?",
            status_handler =status_handler,
            error_message=f"'channel' is missing in the [{station_section}] section. Please specify a channel.",
            warning_message=f"'channel' is empty in the [{station_section}] section. Defaulting to '?H?,?N?'.",
            # validation_fn=lambda x: bool(re.match(r'^(\?[\w]\?,?)+$', x))
        )
        
        start_time = cls._parse_param(
            config=config,
            section=station_section,
            key="starttime",
            default=(datetime.now() - timedelta(days=30)).isoformat(),
            status_handler=status_handler,
            error_message=f"'starttime' is missing in the [{station_section}] section. Specify a valid start time.",
            warning_message=f"'starttime' is empty in the [{station_section}] section. Defaulting to 1 month before the current time.",
            validation_fn=lambda x: parse_time(x) is not None
        )
        start_time = parse_time(start_time)

        end_time = cls._parse_param(
            config=config,
            section=station_section,
            key="endtime",
            default=datetime.now().isoformat(),
            status_handler=status_handler,
            error_message=f"'endtime' is missing in the [{station_section}] section. Specify a valid end time.",
            warning_message=f"'endtime' is empty in the [{station_section}] section. Defaulting to the current time.",
            validation_fn=lambda x: parse_time(x) is not None
        )
        end_time = parse_time(end_time)

        geo_constraint_station = cls._parse_geo_constraint(cls, config, 'STATION', status_handler)

        # Parse force_stations (can be network.station.location.channel)
        force_stations_cmb_n_s = config.get(station_section, 'force_stations', fallback='').split(',')
        force_stations = [SeismoQuery(cmb_str_n_s=cmb_n_s,starttime=start_time,endtime=end_time) for cmb_n_s in force_stations_cmb_n_s if cmb_n_s.strip()]

        # Parse exclude_stations (just network.station)
        exclude_stations_cmb_n_s = config.get(station_section, 'exclude_stations', fallback='').split(',')
        exclude_stations = [SeismoQuery(cmb_str_n_s=cmb_n_s) for cmb_n_s in exclude_stations_cmb_n_s if cmb_n_s.strip()]

        # Parse local_inventory
        local_inventory = cls.parse_optional(config.get(station_section, 'local_inventory', fallback=None))
        highest_samplerate_only = cls._check_val(config.get(station_section, "highest_samplerate_only", fallback=False), False, "bool")

        # Parse include_restricted
        include_restricted = cls._check_val(
            config.get(station_section, 'include_restricted', fallback='False'), False, "bool"
        )

        # Parse level
        level = config.get(station_section, 'level', fallback='channel')
        if level is None:  # Key is missing
            status_handler.add_error("input_parameters", f"'level' is missing in the [{station_section}] section. Please specify a level (e.g., 'channel').")
        else:
            level = level.strip()
            if not level:  # Value is empty
                level= Levels.CHANNEL
                status_handler.add_warning("input_parameters", f"'level' is empty in the [{station_section}] section. Defaulting to 'channel'.")


        # Parse date configurations
        date_config = DateConfig(
            start_time=start_time,
            end_time=end_time,
            start_before=cls.parse_optional(parse_time(config.get(station_section, 'startbefore', fallback=None))),
            start_after=cls.parse_optional(parse_time(config.get(station_section, 'startafter', fallback=None))),
            end_before=cls.parse_optional(parse_time(config.get(station_section, 'endbefore', fallback=None))),
            end_after=cls.parse_optional(parse_time(config.get(station_section, 'endafter', fallback=None))),
        )

        # Build the StationConfig object
        return StationConfig(
            client=station_client,
            local_inventory=local_inventory,
            force_stations=force_stations,
            exclude_stations=exclude_stations,
            date_config=date_config,
            network=network,
            station=station,
            location=location,
            channel=channel,
            highest_samplerate_only=highest_samplerate_only, #double check this belongs here
            geo_constraint=[geo_constraint_station] if geo_constraint_station else [],
            include_restricted=include_restricted,
            level=level,
        )

    @classmethod
    def _parse_event_section(cls, config, status_handler, download_type):
        """
        Parse and validate the EVENT section of the configuration file.

        Args:
            config: ConfigParser object.
            warnings: List to append warnings.
            errors: List to append errors.

        Returns:
            EventConfig object.
        """
        event_section = "EVENT"

        # Ensure the EVENT section exists
        if not config.has_section(event_section):
            if download_type == DownloadType.EVENT:
                status_handler.add_error("input_parameters", f"The [{event_section}] section is missing in the configuration file.")
            return None

        # Parse required parameters
        event_client = cls._parse_param(
            config=config,
            section=event_section,
            key="client",
            default="EARTHSCOPE",
            status_handler=status_handler,
            error_message=f"'client' is missing in the [{event_section}] section. Specify a client.",
            warning_message=f"'client' is empty in the [{event_section}] section. Defaulting to 'EARTHSCOPE'.",
            validation_fn=lambda x: bool(x.strip())
        )

        model = cls._parse_param(
            config=config,
            section=event_section,
            key="model",
            default="iasp91",
            status_handler=status_handler,
            error_message=f"'model' is missing in the [{event_section}] section. Specify a model.",
            warning_message=f"'model' is empty in the [{event_section}] section. Defaulting to 'iasp91'."
        )

        start_time = cls._parse_param(
            config=config,
            section=event_section,
            key="starttime",
            default=(datetime.now() - timedelta(days=30)).isoformat(),
            status_handler=status_handler,
            error_message=f"'starttime' is missing in the [{event_section}] section. Specify a valid start time.",
            warning_message=f"'starttime' is empty in the [{event_section}] section. Defaulting to 1 month before the current time.",
            validation_fn=lambda x: parse_time(x) is not None
        )
        start_time = parse_time(start_time)

        end_time = cls._parse_param(
            config=config,
            section=event_section,
            key="endtime",
            default=datetime.now().isoformat(),
            status_handler=status_handler,
            error_message=f"'endtime' is missing in the [{event_section}] section. Specify a valid end time.",
            warning_message=f"'endtime' is empty in the [{event_section}] section. Defaulting to the current time.",
            validation_fn=lambda x: parse_time(x) is not None
        )
        end_time = parse_time(end_time)

        before_p_sec = cls._parse_param(
            config=config,
            section=event_section,
            key="before_p_sec",
            default=20,
            status_handler=status_handler,
            error_message=f"'before_p_sec' is missing in the [{event_section}] section. Specify a valid integer.",
            warning_message=f"'before_p_sec' is empty in the [{event_section}] section. Defaulting to '20'.",
            validation_fn=lambda x: x.isdigit()
        )
        before_p_sec = int(before_p_sec)

        after_p_sec = cls._parse_param(
            config=config,
            section=event_section,
            key="after_p_sec",
            default=130,
            status_handler=status_handler,
            error_message=f"'after_p_sec' is missing in the [{event_section}] section. Specify a valid integer.",
            warning_message=f"'after_p_sec' is empty in the [{event_section}] section. Defaulting to '130'.",
            validation_fn=lambda x: x.isdigit()
        )
        after_p_sec = int(after_p_sec)

        # Parse optional numerical parameters
        min_depth = cls._check_val(config.get(event_section, "min_depth", fallback=-3), -3, "float")
        max_depth = cls._check_val(config.get(event_section, "max_depth", fallback=600), 600, "float")
        min_magnitude = cls._check_val(config.get(event_section, "minmagnitude", fallback=5.5), 5.5, "float")
        max_magnitude = cls._check_val(config.get(event_section, "maxmagnitude", fallback=7.7), 7.7, "float")
        min_radius = cls._check_val(config.get(event_section, "minradius", fallback=30.0), 30.0, "float")
        max_radius = cls._check_val(config.get(event_section, "maxradius", fallback=90.0), 90.0, "float")

        if min_radius < 0 or max_radius < 0:
            status_handler.add_error("input_parameters" , f"'min_radius' and 'max_radius' must be positive values in the [{event_section}] section.")
        if min_radius >= max_radius:
            status_handler.add_error("input_parameters" ,f"'min_radius' must be less than 'max_radius' in the [{event_section}] section.")

        # Parse boolean flags
        include_all_origins = cls._check_val(config.get(event_section, "includeallorigins", fallback=False), False, "bool")
        include_all_magnitudes = cls._check_val(config.get(event_section, "includeallmagnitudes", fallback=False), False, "bool")
        include_arrivals = cls._check_val(config.get(event_section, "includearrivals", fallback=False), False, "bool")
        

        # Parse optional strings
        limit = cls.parse_optional(config.get(event_section, "limit", fallback=None))
        offset = cls.parse_optional(config.get(event_section, "offset", fallback=None))
        local_catalog = cls.parse_optional(config.get(event_section, "local_catalog", fallback=None))
        contributor = cls.parse_optional(config.get(event_section, "contributor", fallback=None))
        updatedafter = cls.parse_optional(config.get(event_section, "updatedafter", fallback=None))
        catalog = cls.parse_optional(config.get(event_section, "catalog", fallback=None))
        eventtype = cls.parse_optional(config.get(event_section, "eventtype", fallback=None))

        # Parse geo_constraint
        geo_constraint_event = cls._parse_geo_constraint(cls, config, event_section, status_handler,)

        # Return EventConfig object
        return EventConfig(
            client=event_client,
            model=model,
            date_config=DateConfig(start_time=start_time, end_time=end_time),
            min_depth=min_depth,
            max_depth=max_depth,
            min_magnitude=min_magnitude,
            max_magnitude=max_magnitude,
            min_radius=min_radius,
            max_radius=max_radius,
            before_p_sec=before_p_sec,
            after_p_sec=after_p_sec,
            geo_constraint=[geo_constraint_event] if geo_constraint_event else [],
            include_all_origins=include_all_origins,
            include_all_magnitudes=include_all_magnitudes,
            include_arrivals=include_arrivals,
            limit=limit,
            offset=offset,
            local_catalog=local_catalog,
            contributor=contributor,
            updatedafter=updatedafter,
            catalog =catalog,
            eventtype=eventtype,
        )

    @staticmethod
    def parse_optional(value):
        return value if value and value.strip() else None

    @staticmethod
    def _parse_param(
        config,
        section,
        key,
        default=None,
        validation_fn=None,
        status_handler=None,
        error_message=None,
        warning_message=None,
    ):
        """
        Parse and validate a parameter from the configuration.

        Args:
            config: ConfigParser object.
            section: Section name (e.g., 'STATION' or 'EVENT').
            key: Parameter key to parse.
            default: Default value to use if the parameter is missing or invalid.
            validation_fn: Optional function to validate the parameter's value.
            status_handler: StatusHandler object to handle warnings and errors.
            error_message: Custom error message for missing parameters.
            warning_message: Custom warning message for empty parameters.

        Returns:
            The parsed and validated parameter value.
        """
        try:
            value = config.get(section, key, fallback=None)
            if value is None:  # Key is missing
                if error_message and status_handler:
                    status_handler.add_error("input_parameters", error_message)
                return default
            value = value.strip()
            if not value:  # Value is empty
                if warning_message and status_handler:
                    status_handler.add_warning("input_parameters", warning_message)
                return default
            if validation_fn and not validation_fn(value):
                if error_message and status_handler:
                    status_handler.add_error("input_parameters", error_message)
                return default
            return value
        except Exception as e:
            if status_handler:
                status_handler.add_error("input_parameters", f"Error parsing '{key}' in the [{section}] section: {str(e)}")
            return default

    @staticmethod
    def _parse_geo_constraint(cls, config, section, status_handler):
        """
        Parse and validate the geo_constraint for a given section.

        Args:
            config: ConfigParser object.
            section: Section name (e.g., 'STATION' or 'EVENT').
            warnings: List to append warnings.
            errors: List to append errors.

        Returns:
            A GeometryConstraint object if valid geo_constraint is found; otherwise, an empty list.
        """
        geo_constraint_type = config.get(section, 'geo_constraint', fallback=None)
        geo_constraint = []

        if geo_constraint_type == GeoConstraintType.BOUNDING:
            # Parse bounding box coordinates
            min_lat = cls._check_val(config.get(section, 'minlatitude'), None, "float")
            max_lat = cls._check_val(config.get(section, 'maxlatitude'), None, "float")
            min_lon = cls._check_val(config.get(section, 'minlongitude'), None, "float")
            max_lon = cls._check_val(config.get(section, 'maxlongitude'), None, "float")

            # Validate longitude range and adjust if necessary
            if max_lon is not None and max_lon > 180:
                max_lon -= 360
                status_handler.add_warning("input_parameters" ,f"'maxlongitude' exceeded 180 in the [{section}] section. Adjusted to {max_lon}.")
            if min_lon is not None and min_lon < -180:
                min_lon += 360
                status_handler.add_warning("input_parameters" ,f"'minlongitude' was below -180 in the [{section}] section. Adjusted to {min_lon}.")

            # Create bounding box constraint
            geo_constraint = GeometryConstraint(
                coords=RectangleArea(
                    min_lat=min_lat,
                    max_lat=max_lat,
                    min_lon=min_lon,
                    max_lon=max_lon,
                )
            )

        elif geo_constraint_type == GeoConstraintType.CIRCLE:
            # Parse circle area coordinates
            lat = cls._check_val(config.get(section, 'latitude'), None, "float")
            lon = cls._check_val(config.get(section, 'longitude'), None, "float")
            min_radius = cls._check_val(config.get(section, 'minsearchradius'), None, "float")
            max_radius = cls._check_val(config.get(section, 'maxsearchradius'), None, "float")

            # Validate longitude range and adjust if necessary
            if lon is not None and lon > 180:
                lon -= 360
                status_handler.add_warning("input_parameters" ,f"'longitude' exceeded 180 in the [{section}] section. Adjusted to {lon}.")
            if lon is not None and lon < -180:
                lon += 360
                status_handler.add_warning("input_parameters" ,f"'longitude' was below -180 in the [{section}] section. Adjusted to {lon}.")

            # Create circular area constraint
            geo_constraint = GeometryConstraint(
                coords=CircleArea(
                    lat=lat,
                    lon=lon,
                    min_radius=min_radius,
                    max_radius=max_radius,
                )
            )


        elif geo_constraint_type is not None:  # Invalid type provided
            if geo_constraint_type == '' or geo_constraint_type.isspace():
                geo_constraint = None
            else:
            # Log error for invalid geo_constraint types
                status_handler.add_error("input_parameters" ,
                    f"Invalid 'geo_constraint' type '{geo_constraint_type}' in the [{section}] section. "
                    f"Allowed values are 'BOUNDING' or 'CIRCLE'."
                )
              
        return geo_constraint


    def to_cfg(self) -> ConfigParser:
        """
        Converts the `SeismoLoaderSettings` instance into a `ConfigParser` object.

        This method constructs a configuration file representation of the current settings
        stored in the `SeismoLoaderSettings` instance. It organizes the settings into sections
        such as `SDS`, `DATABASE`, `PROCESSING`, `AUTH`, `WAVEFORM`, `STATION`, and `EVENT`.

        Returns:
            configparser.ConfigParser: A `ConfigParser` object representing the current settings.
        """
        config = ConfigParser()

        # Populate the [SDS] section
        config['SDS'] = {}
        safe_add_to_config(config, 'SDS', 'sds_path', self.sds_path)

        # Populate the [DATABASE] section
        config['DATABASE'] = {}
        safe_add_to_config(config, 'DATABASE', 'db_path', self.db_path)

        # Populate the [PROCESSING] section
        config['PROCESSING'] = {}
        safe_add_to_config(config, 'PROCESSING', 'num_processes', self.processing.num_processes)
        safe_add_to_config(config, 'PROCESSING', 'gap_tolerance', self.processing.gap_tolerance)
        safe_add_to_config(config, 'PROCESSING', 'download_type', self.download_type.value)

        # Populate the [AUTH] section
        config['AUTH'] = {}
        if self.auths:
            for auth in self.auths:
                safe_add_to_config(config, 'AUTH', auth.nslc_code, f"{auth.username}:{auth.password}")


        # Populate the [WAVEFORM] section
        config['WAVEFORM'] = {}
        safe_add_to_config(config, 'WAVEFORM', 'client', self.waveform.client)
        safe_add_to_config(config, 'WAVEFORM', 'channel_pref', self.waveform.channel_pref)
        safe_add_to_config(config, 'WAVEFORM', 'location_pref', self.waveform.location_pref)
        safe_add_to_config(config, 'WAVEFORM', 'days_per_request', self.waveform.days_per_request)

        # Populate the [STATION] section
        if self.station:
            config['STATION'] = {}
            safe_add_to_config(config, 'STATION', 'client', self.station.client)
            safe_add_to_config(config, 'STATION', 'local_inventory', self.station.local_inventory)
            safe_add_to_config(config, 'STATION', 'force_stations', ','.join([convert_to_str(station.cmb_str) for station in self.station.force_stations if station.cmb_str is not None]))
            safe_add_to_config(config, 'STATION', 'exclude_stations', ','.join([convert_to_str(station.cmb_str) for station in self.station.exclude_stations if station.cmb_str is not None]))
            safe_add_to_config(config, 'STATION', 'highest_samplerate_only', self.station.highest_samplerate_only)
            safe_add_to_config(config, 'STATION', 'starttime', self.station.date_config.start_time)
            safe_add_to_config(config, 'STATION', 'endtime', self.station.date_config.end_time)
            safe_add_to_config(config, 'STATION', 'network', self.station.network)
            safe_add_to_config(config, 'STATION', 'station', self.station.station)
            safe_add_to_config(config, 'STATION', 'location', self.station.location)
            safe_add_to_config(config, 'STATION', 'channel', self.station.channel)
            safe_add_to_config(config, 'STATION', 'station', self.station.station)
            safe_add_to_config(config, 'STATION', 'location', self.station.location)  # Ensure location is added
            safe_add_to_config(config, 'STATION', 'channel', self.station.channel)    # Ensure channel is added


            # FIXME: The settings are updated such that they support multiple geometries.
            # But config file only accepts one geometry at a time. For now we just get
            # the first item.
            if self.station.geo_constraint and hasattr(self.station.geo_constraint[0], 'geo_type'):
                safe_add_to_config(config, 'STATION', 'geo_constraint', self.station.geo_constraint[0].geo_type)
                
                if self.station.geo_constraint[0].geo_type == GeoConstraintType.CIRCLE:
                    safe_add_to_config(config, 'STATION', 'latitude', self.station.geo_constraint[0].coords.lat)
                    safe_add_to_config(config, 'STATION', 'longitude', self.station.geo_constraint[0].coords.lon)
                    safe_add_to_config(config, 'STATION', 'minradius', self.station.geo_constraint[0].coords.min_radius)
                    safe_add_to_config(config, 'STATION', 'maxradius', self.station.geo_constraint[0].coords.max_radius)

                if self.station.geo_constraint[0].geo_type == GeoConstraintType.BOUNDING:
                    safe_add_to_config(config, 'STATION', 'minlatitude', self.station.geo_constraint[0].coords.min_lat)
                    safe_add_to_config(config, 'STATION', 'maxlatitude', self.station.geo_constraint[0].coords.max_lat)
                    safe_add_to_config(config, 'STATION', 'minlongitude', self.station.geo_constraint[0].coords.min_lon)
                    safe_add_to_config(config, 'STATION', 'maxlongitude', self.station.geo_constraint[0].coords.max_lon)

            safe_add_to_config(config, 'STATION', 'includerestricted', self.station.include_restricted)
            safe_add_to_config(config, 'STATION', 'level', self.station.level.value)

        # Check if the main section is EventConfig or StationConfig and populate accordingly
        if self.event:
            config['EVENT'] = {}
            safe_add_to_config(config, 'EVENT', 'client', self.event.client)
            safe_add_to_config(config, 'EVENT', 'min_depth', self.event.min_depth)
            safe_add_to_config(config, 'EVENT', 'max_depth', self.event.max_depth)
            safe_add_to_config(config, 'EVENT', 'minmagnitude', self.event.min_magnitude)
            safe_add_to_config(config, 'EVENT', 'maxmagnitude', self.event.max_magnitude)
            safe_add_to_config(config, 'EVENT', 'minradius', self.event.min_radius)
            safe_add_to_config(config, 'EVENT', 'maxradius', self.event.max_radius)
            safe_add_to_config(config, 'EVENT', 'after_p_sec', self.event.after_p_sec)
            safe_add_to_config(config, 'EVENT', 'before_p_sec', self.event.before_p_sec)
            safe_add_to_config(config, 'EVENT', 'includeallorigins', self.event.include_all_origins)
            safe_add_to_config(config, 'EVENT', 'includeallmagnitudes', self.event.include_all_magnitudes)
            safe_add_to_config(config, 'EVENT', 'includearrivals', self.event.include_arrivals)
            safe_add_to_config(config, 'EVENT', 'limit', self.event.limit)
            safe_add_to_config(config, 'EVENT', 'offset', self.event.offset)
            safe_add_to_config(config, 'EVENT', 'local_catalog', self.event.local_catalog)
            safe_add_to_config(config, 'EVENT', 'contributor', self.event.contributor)
            safe_add_to_config(config, 'EVENT', 'updatedafter', self.event.updatedafter)
            safe_add_to_config(config, 'EVENT', 'eventtype', self.event.eventtype)
            safe_add_to_config(config, 'EVENT', 'catalog', self.event.catalog)

            # FIXME: The settings are updated such that they support multiple geometries.
            # But config file only accepts one geometry at a time.For now we just get
            # the first item.
         
            if self.event.geo_constraint and hasattr(self.event.geo_constraint[0], 'geo_type'):
                safe_add_to_config(config, 'EVENT', 'geo_constraint', self.event.geo_constraint[0].geo_type)

                if self.event.geo_constraint[0].geo_type == GeoConstraintType.CIRCLE:
                    safe_add_to_config(config, 'EVENT', 'latitude', self.event.geo_constraint[0].coords.lat)
                    safe_add_to_config(config, 'EVENT', 'longitude', self.event.geo_constraint[0].coords.lon)
                    safe_add_to_config(config, 'EVENT', 'minsearchradius', self.event.geo_constraint[0].coords.min_radius)
                    safe_add_to_config(config, 'EVENT', 'maxsearchradius', self.event.geo_constraint[0].coords.max_radius)

                if self.event.geo_constraint[0].geo_type == GeoConstraintType.BOUNDING:
                    safe_add_to_config(config, 'EVENT', 'minlatitude', self.event.geo_constraint[0].coords.min_lat)
                    safe_add_to_config(config, 'EVENT', 'maxlatitude', self.event.geo_constraint[0].coords.max_lat)
                    safe_add_to_config(config, 'EVENT', 'minlongitude', self.event.geo_constraint[0].coords.min_lon)
                    safe_add_to_config(config, 'EVENT', 'maxlongitude', self.event.geo_constraint[0].coords.max_lon)

        return config

    def add_to_config(self):
        config_dict = {
            'sds_path': self.sds_path,
            'db_path': self.db_path,
            'processing': {
                'num_processes': self.processing.num_processes,
                'gap_tolerance': self.processing.gap_tolerance,
            },            
            'download_type': self.download_type.value if self.download_type else None,
            'auths': self.auths if self.auths else [],
            'waveform': {
                'client': self.waveform.client if self.waveform and self.waveform.client else None,
                'channel_pref': self.waveform.channel_pref if self.waveform else None,
                'location_pref': self.waveform.location_pref if self.waveform else None,
                'days_per_request': self.waveform.days_per_request if self.waveform and self.waveform.days_per_request is not None else None,
                'force_redownload': self.waveform.force_redownload if self.waveform else None, 
            },
            'station': {
                'client': self.station.client if self.station and self.station.client else None,
                'local_inventory': self.station.local_inventory if self.station else None,
                'force_stations': [station.cmb_str for station in self.station.force_stations if station.cmb_str is not None] if self.station and isinstance(self.station.force_stations, list) else [],
                'exclude_stations': [station.cmb_str for station in self.station.exclude_stations if station.cmb_str is not None] if self.station and isinstance(self.station.exclude_stations, list) else [],
                'highest_samplerate_only': self.station.highest_samplerate_only if self.station else None,
                'starttime': self.station.date_config.start_time if self.station and self.station.date_config else None,
                'endtime': self.station.date_config.end_time if self.station and self.station.date_config else None,
                'startbefore': self.station.date_config.start_before if self.station and self.station.date_config else None,
                'startafter': self.station.date_config.start_after if self.station and self.station.date_config else None,
                'endbefore': self.station.date_config.end_before if self.station and self.station.date_config else None,
                'endafter': self.station.date_config.end_after if self.station and self.station.date_config else None,
                'network': self.station.network if self.station else None,
                'station': self.station.station if self.station else None,
                'location': self.station.location if self.station else None,
                'channel': self.station.channel if self.station else None,
                'geo_constraint': self.station.geo_constraint if self.station else None,
                'includerestricted': self.station.include_restricted if self.station else None,
                'level': self.station.level.value if self.station and self.station.level else None,
            }
        }
        if self.event:
            config_dict['event'] = {
                'client': self.event.client if self.event and self.event.client else None,
                'model': self.event.model if self.event and self.event.model else None,
                'before_p_sec': self.event.before_p_sec if self.event and self.event.before_p_sec is not None else None,
                'after_p_sec': self.event.after_p_sec if self.event and self.event.after_p_sec is not None else None,
                'starttime': self.event.date_config.start_time if self.event and self.event.date_config else None,
                'endtime': self.event.date_config.end_time if self.event and self.event.date_config else None,
                'min_depth': self.event.min_depth if self.event and self.event.min_depth is not None else None,
                'max_depth': self.event.max_depth if self.event and self.event.max_depth is not None else None,
                'minmagnitude': self.event.min_magnitude if self.event and self.event.min_magnitude is not None else None,
                'maxmagnitude': self.event.max_magnitude if self.event and self.event.max_magnitude is not None else None,
                'minradius': self.event.min_radius if self.event and self.event.min_radius is not None else None,
                'maxradius': self.event.max_radius if self.event and self.event.max_radius is not None else None,
                'local_catalog': self.event.local_catalog if self.event else None,
                'geo_constraint': self.event.geo_constraint if self.event else None,
                'includeallorigins': self.event.include_all_origins if self.event else None,
                'includeallmagnitudes': self.event.include_all_magnitudes if self.event else None,
                'includearrivals': self.event.include_arrivals if self.event else None,
                'limit': self.event.limit if self.event and self.event.limit is not None else None,
                'offset': self.event.offset if self.event and self.event.offset is not None else None,
                'contributor': self.event.contributor if self.event and self.event.contributor else None,
                'eventtype': self.event.eventtype if self.event and self.event.eventtype else None,
                'catalog': self.event.catalog if self.event and self.event.catalog else None,
                'updatedafter': self.event.updatedafter if self.event and self.event.updatedafter else None,
            }
        
        return config_dict


    def add_prediction(self, resource_id: str, station_id: str, p_arrival: datetime, s_arrival: datetime):
        """
        Adds a predicted P-wave and S-wave arrival time for a given event and station.

        Args:
            resource_id (str): The unique identifier of the seismic event.
            station_id (str): The identifier of the seismic station.
            p_arrival (datetime): The predicted arrival time of the P-wave.
            s_arrival (datetime): The predicted arrival time of the S-wave.
        """
        key = f"{resource_id}|{station_id}"
        self.predictions[key] = PredictionData(
            resource_id=resource_id,
            station_id=station_id,
            p_arrival=p_arrival,
            s_arrival=s_arrival
        )

    def get_prediction(self, resource_id: str, station_id: str) -> Optional[PredictionData]:
        """
        Retrieves the predicted arrival time for a given event and station.

        Args:
            resource_id (str): The unique identifier of the seismic event.
            station_id (str): The identifier of the seismic station.

        Returns:
            Optional[PredictionData]: The predicted arrival time data, or `None` if not found.
        """
        key = f"{resource_id}|{station_id}"
        return self.predictions.get(key)
    class Config:
        arbitrary_types_allowed = True       
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

    def to_pickle(self, pickle_path: str) -> None:
        """
        Serializes the `SeismoLoaderSettings` instance to a pickle file.

        Args:
            pickle_path (str): The file path where the object should be saved.
        """
        with open(pickle_path, "wb") as f:
            pickle.dump(self, f)
    
    @classmethod
    def from_pickle_file(cls, pickle_path: str) -> "SeismoLoaderSettings":
        """
        Loads a `SeismoLoaderSettings` instance from a pickle file.

        Args:
            pickle_path (str): The file path from which the object should be loaded.

        Returns:
            SeismoLoaderSettings: The loaded instance of the class.
        """
        with open(pickle_path, "rb") as f:
            return pickle.load(f)
        

    def has_changed(self, old_settings: "SeismoLoaderSettings") -> Dict[str, bool]:
        """
        Compare self with old_settings and return a dictionary indicating which parts have changed.

        Args:
            old_settings (SeismoLoaderSettings): The old settings to compare against.

        Returns:
            Dict[str, bool]: A dictionary with keys indicating which properties changed.
        """
        changes = {
            "has_changed": False,
            "event": False,
            "station": False,
            "waveform": False,
            "settings": False,
        }

        if not isinstance(old_settings, SeismoLoaderSettings):
            raise TypeError("old_settings must be an instance of SeismoLoaderSettings")

        # Compare each component and update the dictionary accordingly
        if self.event != old_settings.event:
            changes["event"] = True
            changes["has_changed"] = True

        if self.station != old_settings.station:
            changes["station"] = True
            changes["has_changed"] = True

        if self.waveform != old_settings.waveform:
            changes["waveform"] = True
            changes["has_changed"] = True

        if (self.sds_path != old_settings.sds_path or
            self.db_path != old_settings.db_path or 
            self.processing != old_settings.processing or
            self.auths != old_settings.auths
            ):
            changes["settings"] = True
            changes["has_changed"] = True

        return changes


def convert_geo_to_minus180_180(geo_constraints: List[GeometryConstraint]) -> List[GeometryConstraint]:
    """
    Convert a list of GeometryConstraint objects from [0, 360] to [-180, 180].
    If a bounding box crosses the dateline, it will be split into multiple constraints.
    """
    converted = []
    for constraint in geo_constraints:
        coords = constraint.coords
        if isinstance(coords, RectangleArea):
            rects = convert_bounds_to_minus180_180(coords)  # this returns a list
            for rect in rects:
                converted.append(
                    GeometryConstraint(coords=rect)
                )
        elif isinstance(coords, CircleArea):
            circle_converted = convert_circle_to_minus180_180(coords)
            converted.append(
                GeometryConstraint(coords=circle_converted)
            )
    return converted


def convert_bounds_to_minus180_180(rect: RectangleArea) -> List[RectangleArea]:
    min_lon = rect.min_lon if rect.min_lon <= 180 else rect.min_lon - 360
    max_lon = rect.max_lon if rect.max_lon <= 180 else rect.max_lon - 360

    if min_lon <= max_lon:
        return [RectangleArea(
            min_lat=rect.min_lat,
            max_lat=rect.max_lat,
            min_lon=min_lon,
            max_lon=max_lon,
            color=rect.color
        )]
    else:
        # Split into two bounding boxes
        left_part = RectangleArea(
            min_lat=rect.min_lat,
            max_lat=rect.max_lat,
            min_lon=min_lon,
            max_lon=180,
            color=rect.color
        )
        right_part = RectangleArea(
            min_lat=rect.min_lat,
            max_lat=rect.max_lat,
            min_lon=-180,
            max_lon=max_lon,
            color=rect.color
        )
        return [left_part, right_part]

def convert_circle_to_minus180_180(circle: CircleArea) -> CircleArea:
    return CircleArea(
        lat=circle.lat,
        lon=circle.lon if circle.lon <= 180 else circle.lon - 360,
        max_radius=circle.max_radius,
        min_radius=circle.min_radius,
        color=circle.color
    )

