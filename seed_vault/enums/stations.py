from enum import Enum


class Networks(str, Enum):
    NTWK_DU = "DU"
    NTWK_1K = "1K"


class Stations(str, Enum):
    DU_TPSO = "DU.TPSO"
    DU_BAD1 = "DU.BAD1"
    DU_BAD3 = "DU.BAD3"
    TPSO    = "TPSO"





