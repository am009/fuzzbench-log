"""Utilities for reading experiment data directly from the filesystem
(blockdom coverage data) instead of from the SQLite database."""

import glob
import json
import os
import re

import pandas as pd
import yaml

from common import benchmark_utils
from common import logs

logger = logs.Logger()

_DEFAULT_SNAPSHOT_PERIOD = 900  # seconds
EXPERIMENT_DATA_DIRS = ['/sn640/fuzzerlog/experiment-data']
KNOWN_BENCHMARKS = sorted(benchmark_utils.get_all_benchmarks(),
                          key=lambda benchmark: (-len(benchmark), benchmark))


def _parse_benchmark_fuzzer_from_dirname(dirname):
    """Split a {benchmark}-{fuzzer} directory name into its components."""
    for benchmark in KNOWN_BENCHMARKS:
        prefix = f'{benchmark}-'
        if dirname.startswith(prefix):
            fuzzer = dirname[len(prefix):]
            if fuzzer:
                return benchmark, fuzzer
    return None


def _parse_benchmark_fuzzer_from_dirs(experiment_folders_dir):
    """Parse benchmark/fuzzer pairs from experiment-folders directory names."""
    pairs = []
    dirs = sorted(d for d in os.listdir(experiment_folders_dir)
                  if os.path.isdir(os.path.join(experiment_folders_dir, d)))
    for dirname in dirs:
        parsed = _parse_benchmark_fuzzer_from_dirname(dirname)
        if parsed is None:
            logger.warning('Failed to parse benchmark/fuzzer from %s',
                           dirname)
            continue
        benchmark, fuzzer = parsed
        pairs.append((benchmark, fuzzer, dirname))
    return pairs


def _read_experiment_metadata(exp_dir, experiment_data_dir):
    """Read experiment metadata from experiment.yaml when available."""
    yaml_path = os.path.join(exp_dir, 'input', 'config', 'experiment.yaml')
    snapshot_period = _DEFAULT_SNAPSHOT_PERIOD
    git_hash = None
    experiment_filestore = experiment_data_dir

    if not os.path.isfile(yaml_path):
        return snapshot_period, git_hash, experiment_filestore

    try:
        with open(yaml_path) as file_handle:
            config = yaml.safe_load(file_handle) or {}
        snapshot_period = config.get('snapshot_period',
                                     _DEFAULT_SNAPSHOT_PERIOD)
        git_hash = config.get('git_hash')
        experiment_filestore = config.get('experiment_filestore',
                                          experiment_data_dir)
    except (yaml.YAMLError, OSError) as error:
        logger.warning('Failed to read %s: %s', yaml_path, error)

    return snapshot_period, git_hash, experiment_filestore


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

        snapshot_period, git_hash, experiment_filestore = (
            _read_experiment_metadata(exp_dir, experiment_data_dir))

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


def get_experiment_data_by_fuzzers(fuzzer_names, experiment_data_dirs=None):
    """Read experiment data by scanning experiment directories for fuzzers."""
    all_rows = []
    experiment_data_dirs = experiment_data_dirs or EXPERIMENT_DATA_DIRS
    fuzzer_name_set = set(fuzzer_names)

    for experiment_data_dir in experiment_data_dirs:
        if not os.path.isdir(experiment_data_dir):
            logger.warning('Experiment data directory not found: %s',
                           experiment_data_dir)
            continue

        experiment_names = sorted(
            name for name in os.listdir(experiment_data_dir)
            if os.path.isdir(os.path.join(experiment_data_dir, name)))

        for experiment_name in experiment_names:
            exp_dir = os.path.join(experiment_data_dir, experiment_name)
            exp_folders_dir = os.path.join(exp_dir, 'experiment-folders')
            if not os.path.isdir(exp_folders_dir):
                continue

            snapshot_period, git_hash, experiment_filestore = (
                _read_experiment_metadata(exp_dir, experiment_data_dir))

            for dirname in sorted(os.listdir(exp_folders_dir)):
                bf_dir = os.path.join(exp_folders_dir, dirname)
                if not os.path.isdir(bf_dir):
                    continue

                parsed = _parse_benchmark_fuzzer_from_dirname(dirname)
                if parsed is None:
                    logger.warning('Failed to parse benchmark/fuzzer from %s',
                                   bf_dir)
                    continue

                benchmark, fuzzer = parsed
                if fuzzer not in fuzzer_name_set:
                    continue

                for trial_dir in sorted(glob.glob(os.path.join(
                        bf_dir, 'trial-*'))):
                    trial_match = re.search(r'trial-(\d+)$', trial_dir)
                    if not trial_match:
                        continue
                    trial_id = int(trial_match.group(1))

                    corpus_dir = os.path.join(trial_dir, 'corpus')
                    if not os.path.isdir(corpus_dir):
                        continue

                    snapshots = _read_trial_data(corpus_dir, snapshot_period)
                    if not snapshots:
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

    description = ('from filesystem by fuzzer: '
                   f'{",".join(fuzzer_names)} in '
                   f'{",".join(experiment_data_dirs)}')
    return df, description
