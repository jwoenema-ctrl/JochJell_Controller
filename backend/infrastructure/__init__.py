"""Adapters and persistence ports for simulated and physical track systems."""

from .interfaces import CommandResult, ConnectionState, ConnectionStatus, TrackSnapshot, TrainMotion
from .real_track import Z21TrackSystem
from .simulation import SimulatedTrackSystem
from .train_database import (
    DecoderFunctionMapping,
    MaintenanceRecord,
    RollingStockRecord,
    SQLiteTrainDatabase,
    TrainDetails,
    TrainModel,
)
from .train_catalogue import (
    CATALOGUE_FORMAT,
    CATALOGUE_VERSION,
    DCC_ADDRESS_MAX,
    DCC_ADDRESS_MIN,
    CatalogueConflictError,
    CatalogueMergeResult,
    CatalogueValidationError,
    TrainCatalogue,
    TrainCatalogueRecord,
    export_csv,
    export_json,
    import_csv,
    import_json,
    validate_record,
)
from .z21 import Z21LanTransport

__all__ = [
    "CommandResult",
    "CATALOGUE_FORMAT",
    "CATALOGUE_VERSION",
    "ConnectionState",
    "ConnectionStatus",
    "CatalogueConflictError",
    "CatalogueMergeResult",
    "CatalogueValidationError",
    "DCC_ADDRESS_MAX",
    "DCC_ADDRESS_MIN",
    "DecoderFunctionMapping",
    "MaintenanceRecord",
    "RollingStockRecord",
    "SQLiteTrainDatabase",
    "SimulatedTrackSystem",
    "TrackSnapshot",
    "TrainDetails",
    "TrainModel",
    "TrainMotion",
    "TrainCatalogue",
    "TrainCatalogueRecord",
    "Z21LanTransport",
    "Z21TrackSystem",
    "export_csv",
    "export_json",
    "import_csv",
    "import_json",
    "validate_record",
]
