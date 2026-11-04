#!/usr/bin/env python3
"""Merge multiple lead CSV files into a single master sheet with duplicate removal."""
import argparse
import csv
import glob
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def merge_csv_files(pattern="*.csv", output_file="master_all_leads.csv"):
    files = [f for f in glob.glob(pattern) if os.path.abspath(f) != os.path.abspath(output_file)]
    if not files:
        print(f"No CSV files found matching '{pattern}'.")
        return

    print(f"Merging {len(files)} file(s) into '{output_file}'...")
    all_rows = []
    all_fields = []
    seen = set()
    skipped_duplicates = 0

    for file in files:
        try:
            with open(file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames:
                    for field in reader.fieldnames:
                        if field not in all_fields:
                            all_fields.append(field)
                for row in reader:
                    # Deduplicate based on title, phone, and website
                    key = (
                        (row.get("title") or "").strip().lower(),
                        (row.get("phone") or "").strip(),
                        (row.get("website") or "").strip().lower()
                    )
                    if key in seen and any(key):
                        skipped_duplicates += 1
                        continue
                    seen.add(key)
                    all_rows.append(row)
        except Exception as e:
            print(f"  Warning: could not read {file}: {e}")

    with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"✓ Success: {len(all_rows)} total leads saved to '{output_file}'.")
    if skipped_duplicates > 0:
        print(f"  ({skipped_duplicates} duplicate entries removed)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge lead CSV files into one master file.")
    parser.add_argument("--pattern", default="*.csv", help="Glob pattern for files to merge (default: *.csv)")
    parser.add_argument("--out", default="master_all_leads.csv", help="Output file name (default: master_all_leads.csv)")
    args = parser.parse_args()
    merge_csv_files(args.pattern, args.out)
