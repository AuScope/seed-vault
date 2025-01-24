from datetime import datetime
from pydantic import BaseModel
from seed_vault.utils.constants import AREA_COLOR

class RectangleArea(BaseModel):
    min_lat: float
    max_lat: float
    min_lng: float
    max_lng: float

    @property
    def color(self) -> str:
        return AREA_COLOR  


class CircleArea(BaseModel):
    lat   : float
    lng   : float
    max_radius: float
    min_radius : float=0
    @property
    def color(self) -> str:
        return AREA_COLOR 
    
class StatusHandler:
    def __init__(self):
        self.status: Dict[str, Dict[str, List[str]]] = {
            "warnings": {},
            "errors": {},
            "logs": {},
        }

    def add_warning(self, category: str, message: str):
        """Add a warning message to a specific category."""
        if category not in self.status["warnings"]:
            self.status["warnings"][category] = []
        self.status["warnings"][category].append(self._format_message("Warning", message))

    def add_error(self, category: str, message: str):
        """Add an error message to a specific category."""
        if category not in self.status["errors"]:
            self.status["errors"][category] = []
        self.status["errors"][category].append(self._format_message("Error", message))

    def add_log(self, category: str, message: str, level: str = "info"):
        """Add a log message to a specific category."""
        if category not in self.status["logs"]:
            self.status["logs"][category] = []
        self.status["logs"][category].append(self._format_message(level.capitalize(), message))

    def get_status(self):
        """Retrieve the full status."""
        return self.status

    def has_errors(self):
        """Check if there are any errors."""
        return any(messages for messages in self.status["errors"].values())

    def has_warnings(self):
        """Check if there are any errors."""
        return any(messages for messages in self.status["warnings"].values())
    
    @staticmethod
    def _format_message(level: str, message: str) -> str:
        """Format a message with a timestamp."""
        # timestamp = datetime.now().isoformat()
        # return f"[{timestamp}] {level}: {message}"
        return f"{message}"

    def display(self):
        """Print all warnings, errors, and logs."""
        for category, subcategories in self.status.items():
            for subcategory, messages in subcategories.items():
                for message in messages:
                    print(f"{category.capitalize()} [{subcategory}]: {message}")

    def generate_status_report(self, level: str = None) -> str:
        """
        Generate a string report of the current status, optionally filtered by level.

        Args:
            level (str, optional): The status level to filter by (e.g., 'warnings', 'errors', 'logs').

        Returns:
            str: A formatted string report of the status.
        """
        report_lines = []
        target_levels = [level] if level else self.status.keys()

        for category in target_levels:
            if category not in self.status:
                continue
            report_lines.append(f"**{category.capitalize()}**")  # Category header
            report_lines.append("") 
            for subcategory, messages in self.status[category].items():
                report_lines.append("") 
                if messages:
                    # report_lines.append(f"  *{subcategory.capitalize()}*")  
                    for i, message in enumerate(messages, start=1):
                        report_lines.append(f"    {i}. {message}")  # Numbered messages
                        report_lines.append("")  # Add a blank line between categories


        return "\n".join(report_lines) if report_lines else "No status messages available."
