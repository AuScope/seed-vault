from enum import Enum


class DescribedEnum(Enum):
    def __new__(cls, value, description):
        obj = object.__new__(cls)
        obj._value_ = value
        obj.description = description
        return obj

    def __str__(self):
        return f"{self.name} ({self.value}): {self.description}"


class GeometryType(str, Enum):
    """
    The class `GeometryType` defines an enumeration with two members, `POLYGON` and `POINT`,
    representing different types of geometric shapes.
    """
    POLYGON = 'Polygon'
    POINT   = 'Point'




class ClientType(str, Enum):
    """
    The class `ClientType` defines an enumeration with three options: `ALL`, `ORIGINAL`, and `EXTRA`.
    """
    ALL = "ALL"
    ORIGINAL = "ORIGINAL"
    EXTRA = "EXTRA"