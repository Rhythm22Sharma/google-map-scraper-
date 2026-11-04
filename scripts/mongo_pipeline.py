"""Forwarding proxy to inner mongo_pipeline module."""
import importlib.util
import os
import sys

_INNER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "googlemaps_scraper",
    "google-maps-scraper-kit",
    "scripts",
    "mongo_pipeline.py",
)

if os.path.exists(_INNER_PATH):
    _spec = importlib.util.spec_from_file_location("_inner_mongo_pipeline", _INNER_PATH)
    if _spec and _spec.loader:
        _module = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_module)
        for _attr in dir(_module):
            if not _attr.startswith("__"):
                globals()[_attr] = getattr(_module, _attr)
