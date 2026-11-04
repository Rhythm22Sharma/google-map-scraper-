"""Root scripts package forwarding to googlemaps_scraper/google-maps-scraper-kit/scripts."""
import os
import sys

_INNER_SCRIPTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "googlemaps_scraper",
    "google-maps-scraper-kit",
    "scripts",
)
if _INNER_SCRIPTS not in sys.path:
    sys.path.insert(0, _INNER_SCRIPTS)
