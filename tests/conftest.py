"""Shared pytest configuration.

Makes the project root importable so test modules can do
`from src.utils.pdf import ...` regardless of how pytest is invoked.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
