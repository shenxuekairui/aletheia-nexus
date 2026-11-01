"""Make shared test fixtures importable when workbench tests run on their own."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
