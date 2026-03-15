"""Utilities for reading experiment data directly from the filesystem
(blockdom coverage data) instead of from the SQLite database."""

import glob
import json
import os
import re

import pandas as pd
import yaml

from common import logs

logger = logs.Logger()

_DEFAULT_SNAPSHOT_PERIOD = 900  # seconds


def _parse_benchmark_fuzzer_from_dirs(experiment_folders_dir):
    """Infer (benchmark, fuzzer) pairs from directory names in
    experiment-folders/.  Each directory follows the pattern
    ``{benchmark}-{fuzzer}`` produced by
    ``experiment_utils.get_benchmark_fuzzer_dir``.

    We find the longest common benchmark prefix shared by all directories.
    """
    dirs = sorted(d for d in os.listdir(experiment_folders_dir)
                  if os.path.isdir(os.path.join(experiment_folders_dir, d)))
    if not dirs:
        return []

    # Find the longest prefix that, when used as benchmark, leaves a non-empty
    # fuzzer suffix for every directory.  The separator between benchmark and
    # fuzzer is '-'.
    parts_list = [d.split('-') for d in dirs]
    # Try progressively shorter prefixes (in number of '-'-separated parts).
    min_parts = min(len(p) for p in parts_list)
    best_prefix_len = 1
    for prefix_len in range(min_parts, 0, -1):
        prefix = '-'.join(parts_list[0][:prefix_len])
        if all(d.startswith(prefix + '-') and len(d) > len(prefix) + 1
               for d in dirs):
            best_prefix_len = prefix_len
            break

    benchmark = '-'.join(parts_list[0][:best_prefix_len])
    pairs = []
    for d in dirs:
        fuzzer = d[len(benchmark) + 1:]  # skip the '-' separator
        pairs.append((benchmark, fuzzer, d))
    return pairs


def _read_trial_data(corpus_dir, snapshot_period):
    """Read blockdom JSON files from a single trial's corpus directory.

    Returns a list of dicts with keys (time, edges_covered), or an empty
    list if no blockdom JSON files exist.
    """
    pattern = os.path.join(corpus_dir, 'corpus-archive-*.tar.gz.json')
    json_files = sorted(glob.glob(pattern))

    # Check for .tar.gz files missing their .json counterpart.
    tar_pattern = os.path.join(corpus_dir, 'corpus-archive-*.tar.gz')
    tar_files = [f for f in glob.glob(tar_pattern)
                 if not f.endswith('.json')]
    json_set = set(json_files)
    for tar_file in sorted(tar_files):
        if tar_file + '.json' not in json_set:
            logger.warning('Missing JSON metadata for %s', tar_file)

    if not json_files:
        return []

    archive_re = re.compile(r'corpus-archive-(\d+)\.tar\.gz\.json$')
    rows = []
    for fpath in json_files:
        match = archive_re.search(fpath)
        if not match:
            continue
        archive_num = int(match.group(1))
        try:
            with open(fpath) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning('Failed to read %s: %s', fpath, e)
            continue
        covered = data.get('covered_block_count', 0)
        rows.append({
            'time': archive_num * snapshot_period,
            'edges_covered': covered,
        })
    return rows


def get_experiment_data_from_filesystem(experiment_names,
                                        experiment_data_dir):
    """Read experiment data from filesystem (blockdom coverage JSON files).

    Returns (DataFrame, description_string) with the same schema as
    ``queries.get_experiment_data()``.
    """
    all_rows = []

    for experiment_name in experiment_names:
        exp_dir = os.path.join(experiment_data_dir, experiment_name)
        if not os.path.isdir(exp_dir):
            logger.warning('Experiment directory not found: %s', exp_dir)
            continue

        # Try reading experiment.yaml for metadata.
        yaml_path = os.path.join(exp_dir, 'input', 'config',
                                 'experiment.yaml')
        snapshot_period = _DEFAULT_SNAPSHOT_PERIOD
        git_hash = None
        experiment_filestore = experiment_data_dir

        if os.path.isfile(yaml_path):
            try:
                with open(yaml_path) as f:
                    config = yaml.safe_load(f)
                snapshot_period = config.get('max_total_time',
                                            82800) // 92  # same heuristic
                # Actually use snapshot_period if explicitly set, otherwise
                # fall back to the default.
                snapshot_period = config.get('snapshot_period',
                                            _DEFAULT_SNAPSHOT_PERIOD)
                git_hash = config.get('git_hash')
                experiment_filestore = config.get('experiment_filestore',
                                                  experiment_data_dir)
            except (yaml.YAMLError, OSError) as e:
                logger.warning('Failed to read %s: %s', yaml_path, e)

        # Discover benchmark-fuzzer pairs from experiment-folders/.
        exp_folders_dir = os.path.join(exp_dir, 'experiment-folders')
        if not os.path.isdir(exp_folders_dir):
            logger.warning('No experiment-folders/ in %s', exp_dir)
            continue

        bf_pairs = _parse_benchmark_fuzzer_from_dirs(exp_folders_dir)
        if not bf_pairs:
            logger.warning('No benchmark-fuzzer dirs found in %s',
                           exp_folders_dir)
            continue

        for benchmark, fuzzer, dir_name in bf_pairs:
            bf_dir = os.path.join(exp_folders_dir, dir_name)
            # Find all trial-* directories.
            trial_dirs = sorted(
                glob.glob(os.path.join(bf_dir, 'trial-*')))

            for trial_dir in trial_dirs:
                trial_match = re.search(r'trial-(\d+)$', trial_dir)
                if not trial_match:
                    continue
                trial_id = int(trial_match.group(1))

                corpus_dir = os.path.join(trial_dir, 'corpus')
                if not os.path.isdir(corpus_dir):
                    continue

                snapshots = _read_trial_data(corpus_dir, snapshot_period)
                if not snapshots:
                    # Skip trials without blockdom data.
                    continue

                for snap in snapshots:
                    all_rows.append({
                        'experiment': experiment_name,
                        'benchmark': benchmark,
                        'fuzzer': fuzzer,
                        'trial_id': trial_id,
                        'time': snap['time'],
                        'edges_covered': snap['edges_covered'],
                        'git_hash': git_hash,
                        'experiment_filestore': experiment_filestore,
                        'time_started': None,
                        'time_ended': None,
                        'fuzzer_stats': None,
                        'crash_key': None,
                    })

    if not all_rows:
        df = pd.DataFrame(columns=[
            'experiment', 'benchmark', 'fuzzer', 'trial_id', 'time',
            'edges_covered', 'git_hash', 'experiment_filestore',
            'time_started', 'time_ended', 'fuzzer_stats', 'crash_key'
        ])
    else:
        df = pd.DataFrame(all_rows)

    description = f'from filesystem: {experiment_data_dir}'
    return df, description
