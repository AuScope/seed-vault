from enum import Enum

class Steps(str, Enum):
    """
    The class `Steps` is an enumeration in Python representing different steps with corresponding string
    values.
    """
    EVENT = "event"
    STATION = "station"
    WAVE = "wave"
    NONE = "none"