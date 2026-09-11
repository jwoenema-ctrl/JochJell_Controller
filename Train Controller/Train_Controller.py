
"""Visual Studio entry point for the H0 Z21 train controller."""

from __future__ import annotations

import sys
from pathlib import Path


# The Visual Studio Python project lives one directory below the modular backend.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.api.server import run  # noqa: E402


if __name__ == "__main__":
    run()
