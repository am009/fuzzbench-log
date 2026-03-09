#!/usr/bin/env python3
"""Recursively compress fuzzerlog.txt files with gzip."""

import argparse
import gzip
import os
import shutil
import sys


def compress_fuzzerlog_files(directory: str) -> int:
    """Recursively find and compress fuzzerlog.txt files.

    Args:
        directory: Path to the directory to search.

    Returns:
        Number of files compressed.
    """
    if not os.path.isdir(directory):
        print(f"Error: '{directory}' is not a valid directory", file=sys.stderr)
        sys.exit(1)

    compressed_count = 0

    for root, _, files in os.walk(directory):
        for filename in files:
            if "fuzzerlog.txt" in filename and not filename.endswith(".gz"):
                filepath = os.path.join(root, filename)
                gz_filepath = filepath + ".gz"

                try:
                    # Compress the file
                    with open(filepath, 'rb') as f_in:
                        with gzip.open(gz_filepath, 'wb', compresslevel=1) as f_out:
                            shutil.copyfileobj(f_in, f_out)

                    # Remove the original file
                    os.remove(filepath)

                    print(f"Compressed: {filepath}")
                    compressed_count += 1

                except Exception as e:
                    print(f"Error compressing {filepath}: {e}", file=sys.stderr)
                    # Clean up partial gz file if it exists
                    if os.path.exists(gz_filepath):
                        os.remove(gz_filepath)

    return compressed_count


def main():
    parser = argparse.ArgumentParser(
        description="Recursively compress fuzzerlog.txt files with gzip"
    )
    parser.add_argument(
        "directory",
        help="Directory path to search for fuzzerlog.txt files"
    )

    args = parser.parse_args()

    count = compress_fuzzerlog_files(args.directory)
    print(f"\nTotal files compressed: {count}")


if __name__ == "__main__":
    main()
