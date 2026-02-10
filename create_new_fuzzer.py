#!/usr/bin/env python3
"""Create a new fuzzer by copying an existing one and adding environment variables."""

import argparse
import shutil
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description='Create a new fuzzer by copying an existing one.')
    parser.add_argument('--base', required=True,
                        help='Base fuzzer folder name under fuzzers/')
    parser.add_argument('--new', required=True,
                        help='New fuzzer folder name')
    parser.add_argument('--env', action='append', default=[],
                        metavar='VAR=VALUE',
                        help='Environment variable to add (can be used multiple times)')

    args = parser.parse_args()

    # Get the fuzzers directory (relative to this script)
    script_dir = Path(__file__).parent.resolve()
    fuzzers_dir = script_dir / 'fuzzers'

    base_path = fuzzers_dir / args.base
    new_path = fuzzers_dir / args.new

    # Check if base folder exists
    if not base_path.exists():
        print(f"Error: Base folder '{base_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    if not base_path.is_dir():
        print(f"Error: '{base_path}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    # Check if new folder already exists
    if new_path.exists():
        print(f"Error: Target folder '{new_path}' already exists.", file=sys.stderr)
        sys.exit(1)

    # Check if base has runner.Dockerfile
    base_dockerfile = base_path / 'runner.Dockerfile'
    if not base_dockerfile.exists():
        print(f"Error: '{base_dockerfile}' does not exist.", file=sys.stderr)
        sys.exit(1)

    # Copy the folder
    shutil.copytree(base_path, new_path)
    print(f"Copied '{args.base}' to '{args.new}'")

    # Append environment variables to runner.Dockerfile
    if args.env:
        new_dockerfile = new_path / 'runner.Dockerfile'
        env_lines = []
        for env_str in args.env:
            if '=' not in env_str:
                print(f"Error: Invalid env format '{env_str}', expected VAR=VALUE",
                      file=sys.stderr)
                sys.exit(1)
            var, value = env_str.split('=', 1)
            env_lines.append(f'ENV {var}={value}')

        with open(new_dockerfile, 'a') as f:
            f.write('\n')
            for line in env_lines:
                f.write(line + '\n')
                print(f"Added: {line}")

    print(f"Done. New fuzzer created at: {new_path}")


if __name__ == '__main__':
    main()
