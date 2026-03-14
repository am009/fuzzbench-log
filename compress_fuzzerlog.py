#!/usr/bin/env python3
"""Recursively compress fuzzerlog.txt files with zstd."""

import argparse
import os
import subprocess
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

    if not _has_zstd():
        print("Error: 'zstd' command not found in PATH", file=sys.stderr)
        sys.exit(1)

    compressed_count = 0

    for root, _, files in os.walk(directory):
        for filename in files:
            if "fuzzerlog.txt" == filename:
                filepath = os.path.join(root, filename)
                # check for running container
                import re
                trial = re.search(r'/trial-([0-9]+)/', filepath).group(1)
                running = subprocess.check_output(["docker", "ps"]).decode('utf-8')
                if f'runner-{trial}\n' in running:
                    continue

                print(f"Compressing {filepath}")
                try:
                    subprocess.run(
                        ["zstd", "--fast", "--rm", filepath],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        text=True,
                    )

                    print(f"Compressed: {filepath}")
                    compressed_count += 1

                except subprocess.CalledProcessError as e:
                    error = e.stderr.strip() or str(e)
                    print(f"Error compressing {filepath}: {error}", file=sys.stderr)

    return compressed_count


def _has_zstd() -> bool:
    return subprocess.run(
        ["zstd", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def main():
    parser = argparse.ArgumentParser(
        description="Recursively compress fuzzerlog.txt files with zstd"
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
