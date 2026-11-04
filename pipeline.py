#!/usr/bin/env python3
"""Root launcher for the Google Maps Scraper MongoDB Pipeline."""
import os
import sys

target_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "googlemaps_scraper", "google-maps-scraper-kit")
if os.path.isdir(target_dir):
    os.chdir(target_dir)
    sys.path.insert(0, target_dir)
    sys.path.insert(0, os.path.join(target_dir, "scripts"))
    import pipeline
    pipeline.main()
else:
    print(f"Error: Scraper directory not found at {target_dir}")
