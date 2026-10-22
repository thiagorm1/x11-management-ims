import sys
from pathlib import Path

# Automatically add src directory to sys.path for test discovery
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
