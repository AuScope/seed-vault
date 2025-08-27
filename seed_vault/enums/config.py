from enum import Enum
from .common import DescribedEnum


class DownloadType(str, Enum):
    """
    The class `DownloadType` defines an enumeration with two members, `EVENT` and `CONTINUOUS`, each
    associated with a specific string value.
    """
    EVENT  = 'event'
    CONTINUOUS = 'continuous'

class WorkflowType(DescribedEnum):
    """
    The class `WorkflowType` defines an enumeration with three options, each representing a different
    type of workflow with a description and explanation.
    """
    EVENT_BASED = ("Event Based - Starting from Selecting Events", "Search for events, then filter for pertinent stations")
    STATION_BASED = ("Station Based - Starting from Selecting Stations", "Search for stations, then filter for pertinent events")
    CONTINUOUS = ("Requesting Continuous Data", "Search for and download bulk continuous station data")

class GeoConstraintType(str, Enum):
    """
    The class `GeoConstraintType` defines an enumeration of geographic constraint types with values for
    bounding, circle, and neither.
    """
    BOUNDING = 'bounding'
    CIRCLE   = 'circle'
    NONE     = 'neither'

class Levels(str, Enum):
    """
    The class `Levels` is a Python enumeration with three members,
    `RESPONSE`, `CHANNEL` and `STATION`, each associated with a string value.
    """
    RESPONSE = 'response'
    CHANNEL  = 'channel'
    STATION  = 'station'