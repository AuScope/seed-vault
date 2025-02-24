from typing import Dict, List
from datetime import datetime
from pydantic import BaseModel
from seed_vault.utils.constants import AREA_COLOR

class RectangleArea(BaseModel):
    """
    Represents a rectangular area defined by latitude and longitude boundaries.

    This class is used to define geographic bounding boxes for seismic data analysis.

    Attributes:
        min_lat (float): The minimum latitude of the rectangle.
        max_lat (float): The maximum latitude of the rectangle.
        min_lon (float): The minimum longitude of the rectangle.
        max_lon (float): The maximum longitude of the rectangle.

    Properties:
        color (str): Returns the predefined color associated with the area.
    """
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

    @property
    def color(self) -> str:
        return AREA_COLOR  



class CircleArea(BaseModel):
    """
    Represents a circular geographic area for seismic data analysis.

    This class is used to define circular constraints for selecting seismic data based on 
    a central point and a radius.

    Attributes:
        lat (float): The latitude of the circle's center.
        lon (float): The longitude of the circle's center.
        max_radius (float): The maximum radius of the circle.
        min_radius (float, optional): The minimum radius of the circle. Defaults to `0`.

    Properties:
        color (str): Returns the predefined color associated with the area.
    """
    lat   : float
    lon   : float
    max_radius: float
    min_radius : float=0
    @property
    def color(self) -> str:
        return AREA_COLOR 
    

class StatusHandler:
    """
    Manages warning, error, and log messages categorized by type.

    This class provides methods for tracking and organizing status messages, including 
    warnings, errors, and logs, to facilitate debugging and status reporting.

    Attributes:
        status (Dict[str, Dict[str, List[str]]]): 
            A dictionary storing messages categorized under "warnings", "errors", and "logs".

    Methods:
        add_warning(category: str, message: str):
            Adds a warning message to a specific category.

        add_error(category: str, message: str):
            Adds an error message to a specific category.

        add_log(category: str, message: str, level: str = "info"):
            Adds a log message with an optional severity level.

        get_status() -> Dict[str, Dict[str, List[str]]]:
            Returns the complete status dictionary.

        has_errors() -> bool:
            Checks if there are any recorded errors.

        has_warnings() -> bool:
            Checks if there are any recorded warnings.

        display():
            Prints all warnings, errors, and logs stored in the status dictionary.

        generate_status_report(level: str = None) -> str:
            Generates a formatted status report, optionally filtering by level.
    """
    def __init__(self):
        """
        Initializes the `StatusHandler` with empty dictionaries for warnings, errors, and logs.
        """
        self.status: Dict[str, Dict[str, List[str]]] = {
            "warnings": {},
            "errors": {},
            "logs": {},
        }

    def add_warning(self, category: str, message: str):
        """
        Adds a warning message to a specific category in the status dictionary.

        Args:
            category (str): The category under which the warning should be stored.
            message (str): The warning message to add.
        """
        if category not in self.status["warnings"]:
            self.status["warnings"][category] = []
        self.status["warnings"][category].append(self._format_message("Warning", message))

    def add_error(self, category: str, message: str):
        """
        Adds an error message to a specific category in the status dictionary.

        Args:
            category (str): The category under which the error should be stored.
            message (str): The error message to add.
        """
        if category not in self.status["errors"]:
            self.status["errors"][category] = []
        self.status["errors"][category].append(self._format_message("Error", message))

    def add_log(self, category: str, message: str, level: str = "info"):
        """
        Adds a log message to a specific category with an optional severity level.

        Args:
            category (str): The category under which the log should be stored.
            message (str): The log message to add.
            level (str, optional): The severity level of the log (e.g., "info", "warning", "error").
                                   Defaults to `"info"`.
        """
        if category not in self.status["logs"]:
            self.status["logs"][category] = []
        self.status["logs"][category].append(self._format_message(level.capitalize(), message))

    def get_status(self) -> Dict[str, Dict[str, List[str]]]:
        """
        Returns the full status dictionary containing warnings, errors, and logs.

        Returns:
            Dict[str, Dict[str, List[str]]]: The complete status dictionary.
        """
        return self.status

    def has_errors(self) -> bool:
        """
        Checks if there are any recorded error messages.

        Returns:
            bool: `True` if there are errors, `False` otherwise.
        """
        return any(messages for messages in self.status["errors"].values())

    def has_warnings(self) -> bool:
        """
        Checks if there are any recorded warning messages.

        Returns:
            bool: `True` if there are warnings, `False` otherwise.
        """
        return any(messages for messages in self.status["warnings"].values())

    @staticmethod
    def _format_message(level: str, message: str) -> str:
        """
        Formats a status message with a given severity level.

        Args:
            level (str): The severity level of the message (e.g., "Warning", "Error", "Info").
            message (str): The actual message content.

        Returns:
            str: The formatted message string.
        """
        return f"{message}"

    def display(self):
        """
        Prints all warnings, errors, and logs stored in the status dictionary.
        """
        for category, subcategories in self.status.items():
            for subcategory, messages in subcategories.items():
                for message in messages:
                    print(f"{category.capitalize()} [{subcategory}]: {message}")

    def generate_status_report(self, level: str = None) -> str:
        """
        Generates a formatted string report of the current status, optionally filtered by a specified level.

        Args:
            level (str, optional): The status category to filter by (e.g., `"warnings"`, `"errors"`, `"logs"`).
                                   If `None`, includes all categories.

        Returns:
            str: A formatted status report containing warnings, errors, and logs.
                 Returns `"No status messages available."` if no messages are found.
        """
        report_lines = []
        target_levels = [level] if level else self.status.keys()

        for category in target_levels:
            if category not in self.status:
                continue
            report_lines.append(f"**{category.capitalize()}**")  # Category header
            for subcategory, messages in self.status[category].items():
                report_lines.append("") 
                if messages:
                    for i, message in enumerate(messages, start=1):
                        report_lines.append(f"    {i}. {message}")  # Numbered messages

        return "\n".join(report_lines) if report_lines else "No status messages available."
