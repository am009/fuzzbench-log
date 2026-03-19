#!/usr/bin/env python3
"""Recursively compress fuzzerlog.txt files with zstd."""

import argparse
import os
import subprocess
import sys


LARGE_ZST_SIZE_BYTES = 1 << 30
LEVEL5_MARKER_CONTENT = "5\n"
TARGET_ZSTD_LEVEL = 5


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
            if filename == "fuzzerlog.txt":
                filepath = os.path.join(root, filename)
                if _is_running_trial(filepath):
                    continue

                print(f"Compressing {filepath}")
                try:
                    subprocess.run(
                        ["zstd", f"-{TARGET_ZSTD_LEVEL}", "--rm", filepath],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    _write_level5_marker(_level_marker_path(f"{filepath}.zst"))
                    print(f"Compressed: {filepath}")
                    compressed_count += 1
                except subprocess.CalledProcessError as e:
                    error = e.stderr.strip() or str(e)
                    print(f"Error compressing {filepath}: {error}", file=sys.stderr)
            elif filename == "fuzzerlog.txt.zst":
                filepath = os.path.join(root, filename)
                if os.path.getsize(filepath) <= LARGE_ZST_SIZE_BYTES:
                    continue

                marker_path = _level_marker_path(filepath)
                if _was_recompressed_with_level5(marker_path):
                    print(f"Skipping already level-5 recompressed file: {filepath}")
                    continue

                print(
                    f"Recompressing oversized archive with level {TARGET_ZSTD_LEVEL}: "
                    f"{filepath}"
                )
                try:
                    _recompress_zst_file(filepath)
                    _write_level5_marker(marker_path)
                    print(f"Recompressed: {filepath}")
                    compressed_count += 1
                except (OSError, subprocess.CalledProcessError) as e:
                    error = getattr(e, "stderr", "") or str(e)
                    if isinstance(error, bytes):
                        error = error.decode("utf-8", errors="replace")
                    print(f"Error recompressing {filepath}: {error}", file=sys.stderr)

    return compressed_count


def _has_zstd() -> bool:
    return subprocess.run(
        ["zstd", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def _is_running_trial(filepath: str) -> bool:
    import re

    match = re.search(r"/trial-([0-9]+)/", filepath)
    if match is None:
        return False

    trial = match.group(1)
    running = subprocess.check_output(["docker", "ps"]).decode("utf-8")
    return f"runner-{trial}\n" in running


def _level_marker_path(filepath: str) -> str:
    return f"{filepath}.level.txt"


def _was_recompressed_with_level5(marker_path: str) -> bool:
    try:
        with open(marker_path, "r", encoding="utf-8") as marker_file:
            return marker_file.read().strip() == str(TARGET_ZSTD_LEVEL)
    except FileNotFoundError:
        return False


def _write_level5_marker(marker_path: str) -> None:
    with open(marker_path, "w", encoding="utf-8") as marker_file:
        marker_file.write(LEVEL5_MARKER_CONTENT)


def _recompress_zst_file(filepath: str) -> None:
    tmp_path = f"{filepath}.tmp"

    if os.path.exists(tmp_path):
        os.unlink(tmp_path)

    try:
        _recompress_via_pipe(filepath, tmp_path)
        os.replace(tmp_path, filepath)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _recompress_via_pipe(filepath: str, output_path: str) -> None:
    decoder = subprocess.Popen(
        ["zstd", "-d", "-c", filepath],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert decoder.stdout is not None
    encoder = subprocess.Popen(
        ["zstd", f"-{TARGET_ZSTD_LEVEL}", "-f", "-o", output_path],
        stdin=decoder.stdout,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    decoder.stdout.close()
    encoder_stderr = encoder.communicate()[1]
    decoder_stderr = decoder.communicate()[1]

    if decoder.returncode != 0:
        raise subprocess.CalledProcessError(
            decoder.returncode,
            decoder.args,
            stderr=(decoder_stderr or b"").decode("utf-8", errors="replace"),
        )
    if encoder.returncode != 0:
        raise subprocess.CalledProcessError(
            encoder.returncode,
            encoder.args,
            stderr=(encoder_stderr or b"").decode("utf-8", errors="replace"),
        )


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
