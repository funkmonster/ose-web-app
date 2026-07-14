"""
Shared pytest configuration.

This inserts the `backend/` directory onto sys.path so tests can do
`from utils.dice import roll` etc. — the same way main.py and engine.py
import things — no matter what directory `pytest` is invoked from.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))