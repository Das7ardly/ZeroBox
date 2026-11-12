import os
import sys

from . import APP_NAME


def data_dir() -> str:
    d = os.environ.get("ZEROBOX_DATA_DIR") or os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def resource_path(*parts) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *parts)
