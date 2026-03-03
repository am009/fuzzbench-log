#!/usr/bin/env python3
# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Directly manages experiment: builds images, launches runner containers with
cpuset scheduling, and waits for all trials to complete."""

import argparse
import datetime
import multiprocessing
import os
import re
import subprocess
import sys
import time
from collections import namedtuple
from typing import Dict, List, Optional, Union

import yaml

from common import benchmark_utils
from common import experiment_utils
from common import filestore_utils
from common import filesystem
from common import fuzzer_utils
from common import gsutil
from common import logs
from common import utils
from common import yaml_utils

BENCHMARKS_DIR = os.path.join(utils.ROOT_DIR, 'benchmarks')
FUZZERS_DIR = os.path.join(utils.ROOT_DIR, 'fuzzers')
FUZZER_NAME_REGEX = re.compile(r'^[a-z][a-z0-9_]+$')
EXPERIMENT_CONFIG_REGEX = re.compile(r'^[a-z0-9-]{0,30}$')
_OSS_FUZZ_CORPUS_BACKUP_URL_FORMAT = (
    'gs://{project}-backup.clusterfuzz-external.appspot.com/corpus/'
    'libFuzzer/{fuzz_target}/public.zip')
DEFAULT_CONCURRENT_BUILDS = 30

Requirement = namedtuple('Requirement',
                         ['mandatory', 'type', 'lowercase', 'startswith'])


def _set_default_config_values(config: Dict[str, Union[int, str, bool]],
                               local_experiment: bool):
    """Set the default configuration values if they are not specified."""
    config['local_experiment'] = local_experiment
    config['worker_pool_name'] = config.get('worker_pool_name', '')
    config['snapshot_period'] = config.get(
        'snapshot_period', experiment_utils.DEFAULT_SNAPSHOT_SECONDS)
    config['private'] = config.get('private', False)
    config['micro_experiment'] = config.get('micro_experiment', False)


def _validate_config_parameters(
        config: Dict[str, Union[int, str, bool]],
        config_requirements: Dict[str, Requirement]) -> bool:
    """Validates if the required |params| exist in |config|."""
    if 'cloud_experiment_bucket' in config or 'cloud_web_bucket' in config:
        logs.error('"cloud_experiment_bucket" and "cloud_web_bucket" are now '
                   '"experiment_filestore" and "report_filestore".')

    missing_params, optional_params = [], []
    for param, requirement in config_requirements.items():
        if param in config:
            continue
        if requirement.mandatory:
            missing_params.append(param)
            continue
        optional_params.append(param)

    for param in missing_params:
        logs.error('Config does not contain required parameter "%s".', param)

    return not missing_params


# pylint: disable=too-many-arguments
def _validate_config_values(
        config: Dict[str, Union[str, int, bool]],
        config_requirements: Dict[str, Requirement]) -> bool:
    """Validates if |params| types and formats in |config| are correct."""

    valid = True
    for param, value in config.items():
        requirement = config_requirements.get(param, None)
        # Unrecognised parameter.
        error_param = 'Config parameter "%s" is "%s".'
        if requirement is None:
            valid = False
            error_reason = 'This parameter is not recognized.'
            logs.error(f'{error_param} {error_reason}', param, str(value))
            continue

        if not isinstance(value, requirement.type):
            valid = False
            error_reason = f'It must be a {requirement.type}.'
            logs.error(f'{error_param} {error_reason}', param, str(value))

        if not isinstance(value, str):
            continue

        if requirement.lowercase and not value.islower():
            valid = False
            error_reason = 'It must be a lowercase string.'
            logs.error(f'{error_param} {error_reason}', param, str(value))

        if requirement.startswith and not value.startswith(
                requirement.startswith):
            valid = False
            error_reason = (
                'Local experiments only support Posix file systems filestores.'
                if config.get('local_experiment', False) else
                'Google Cloud experiments must start with "gs://".')
            logs.error(f'{error_param} {error_reason}', param, value)

    return valid


# pylint: disable=too-many-locals
def read_and_validate_experiment_config(config_filename: str) -> Dict:
    """Reads |config_filename|, validates it, finds as many errors as possible,
    and returns it."""
    # Reads config from file.
    config = yaml_utils.read(config_filename)

    # Validates config contains all the required parameters.
    local_experiment = config.get('local_experiment', False)

    # Requirement of each config field.
    config_requirements = {
        'experiment_filestore':
            Requirement(True, str, True, '/' if local_experiment else 'gs://'),
        'report_filestore':
            Requirement(True, str, True, '/' if local_experiment else 'gs://'),
        'docker_registry':
            Requirement(True, str, True, ''),
        'trials':
            Requirement(True, int, False, ''),
        'max_total_time':
            Requirement(True, int, False, ''),
        'cloud_compute_zone':
            Requirement(not local_experiment, str, True, ''),
        'cloud_project':
            Requirement(not local_experiment, str, True, ''),
        'worker_pool_name':
            Requirement(not local_experiment, str, False, ''),
        'cloud_sql_instance_connection_name':
            Requirement(False, str, True, ''),
        'snapshot_period':
            Requirement(False, int, False, ''),
        'local_experiment':
            Requirement(False, bool, False, ''),
        'private':
            Requirement(False, bool, False, ''),
        'merge_with_nonprivate':
            Requirement(False, bool, False, ''),
        'preemptible_runners':
            Requirement(False, bool, False, ''),
        'runner_machine_type':
            Requirement(False, str, True, ''),
        'runner_num_cpu_cores':
            Requirement(False, int, False, ''),
        'runner_memory':
            Requirement(False, str, False, ''),
        'micro_experiment':
            Requirement(False, bool, False, ''),
    }

    all_params_valid = _validate_config_parameters(config, config_requirements)
    all_values_valid = _validate_config_values(config, config_requirements)
    if not all_params_valid or not all_values_valid:
        raise ValidationError(f'Config: {config_filename} is invalid.')

    _set_default_config_values(config, local_experiment)
    return config


class ValidationError(Exception):
    """Error validating user input to this program."""


def get_directories(parent_dir):
    """Returns a list of subdirectories in |parent_dir|."""
    return [
        directory for directory in os.listdir(parent_dir)
        if os.path.isdir(os.path.join(parent_dir, directory))
    ]


# pylint: disable=too-many-locals
def validate_custom_seed_corpus(custom_seed_corpus_dir, benchmarks):
    """Validate seed corpus provided by user"""
    if not os.path.isdir(custom_seed_corpus_dir):
        raise ValidationError(
            f'Corpus location "{custom_seed_corpus_dir}" is invalid.')

    for benchmark in benchmarks:
        benchmark_corpus_dir = os.path.join(custom_seed_corpus_dir, benchmark)
        if not os.path.exists(benchmark_corpus_dir):
            raise ValidationError('Custom seed corpus directory for '
                                  f'benchmark "{benchmark}" does not exist.')
        if not os.path.isdir(benchmark_corpus_dir):
            raise ValidationError(
                f'Seed corpus of benchmark "{benchmark}" must be a directory.')
        if not os.listdir(benchmark_corpus_dir):
            raise ValidationError(
                f'Seed corpus of benchmark "{benchmark}" is empty.')


def validate_benchmarks(benchmarks: List[str]):
    """Parses and validates list of benchmarks."""
    benchmark_types = set()
    for benchmark in set(benchmarks):
        if benchmarks.count(benchmark) > 1:
            raise ValidationError(
                f'Benchmark "{benchmark}" is included more than once.')
        # Validate benchmarks here. It's possible someone might run an
        # experiment without going through presubmit. Better to catch an invalid
        # benchmark than see it in production.
        if not benchmark_utils.validate(benchmark):
            raise ValidationError(f'Benchmark "{benchmark}" is invalid.')

        benchmark_types.add(benchmark_utils.get_type(benchmark))

    if (benchmark_utils.BenchmarkType.CODE.value in benchmark_types and
            benchmark_utils.BenchmarkType.BUG.value in benchmark_types):
        raise ValidationError(
            'Cannot mix bug benchmarks with code coverage benchmarks.')


def validate_fuzzer(fuzzer: str):
    """Parses and validates a fuzzer name."""
    if not fuzzer_utils.validate(fuzzer):
        raise ValidationError(f'Fuzzer: {fuzzer} is invalid.')


def validate_experiment_name(experiment_name: str):
    """Validate |experiment_name| so that it can be used in creating
    instances."""
    if not re.match(EXPERIMENT_CONFIG_REGEX, experiment_name):
        raise ValidationError(
            f'Experiment name "{experiment_name}" is invalid. '
            f'Must match: "{EXPERIMENT_CONFIG_REGEX.pattern}"')


def set_up_experiment_config_file(config):
    """Set up the config file that will actually be used in the
    experiment (not the one given to run_experiment.py)."""
    filesystem.recreate_directory(experiment_utils.CONFIG_DIR)
    experiment_config_filename = (
        experiment_utils.get_internal_experiment_config_relative_path())
    with open(experiment_config_filename, 'w',
              encoding='utf-8') as experiment_config_file:
        yaml.dump(config, experiment_config_file, default_flow_style=False)


def check_no_uncommitted_changes():
    """Make sure that there are no uncommitted changes."""
    if subprocess.check_output(['git', 'diff'], cwd=utils.ROOT_DIR):
        raise ValidationError('Local uncommitted changes found, exiting.')


def get_git_hash(allow_uncommitted_changes):
    """Return the git hash for the last commit in the local repo."""
    try:
        output = subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                         cwd=utils.ROOT_DIR)
        return output.strip().decode('utf-8')
    except subprocess.CalledProcessError as error:
        if not allow_uncommitted_changes:
            raise error
        return ''


def _filter_incompatible_benchmarks(config: dict,
                                    benchmarks: List[str]) -> List[str]:
    """Removes benchmarks that are incompatible with build/run environment."""
    if config['local_experiment']:
        return benchmarks
    if 'openh264_decoder_fuzzer' in benchmarks:
        benchmarks.remove('openh264_decoder_fuzzer')
    if 'stb_stbi_read_fuzzer' in benchmarks:
        benchmarks.remove('stb_stbi_read_fuzzer')
    return benchmarks


def start_experiment(  # pylint: disable=too-many-arguments
        experiment_name: str,
        config_filename: str,
        benchmarks: List[str],
        fuzzers: List[str],
        description: Optional[str] = None,
        no_seeds: bool = False,
        no_dictionaries: bool = False,
        oss_fuzz_corpus: bool = False,
        allow_uncommitted_changes: bool = False,
        concurrent_builds: Optional[int] = DEFAULT_CONCURRENT_BUILDS,
        measurers_cpus: Optional[int] = None,
        runners_cpus: Optional[int] = None,
        region_coverage: bool = False,
        custom_seed_corpus_dir: Optional[str] = None):
    """Start a fuzzer benchmarking experiment."""
    if not allow_uncommitted_changes:
        check_no_uncommitted_changes()

    validate_experiment_name(experiment_name)
    validate_benchmarks(benchmarks)

    config = read_and_validate_experiment_config(config_filename)
    config['fuzzers'] = fuzzers
    config['benchmarks'] = _filter_incompatible_benchmarks(config, benchmarks)
    config['experiment'] = experiment_name
    config['git_hash'] = get_git_hash(allow_uncommitted_changes)
    config['no_seeds'] = no_seeds
    config['no_dictionaries'] = no_dictionaries
    config['oss_fuzz_corpus'] = oss_fuzz_corpus
    config['description'] = description
    config['concurrent_builds'] = concurrent_builds
    config['measurers_cpus'] = measurers_cpus
    config['runners_cpus'] = runners_cpus
    config['runner_machine_type'] = config.get('runner_machine_type',
                                               'n1-standard-1')
    config['runner_num_cpu_cores'] = config.get('runner_num_cpu_cores', 1)
    assert (runners_cpus is None or
            runners_cpus >= config['runner_num_cpu_cores'])
    # Note this is only used if runner_machine_type is None.
    # 12GB is just the amount that KLEE needs, use this default to make KLEE
    # experiments easier to run.
    config['runner_memory'] = config.get('runner_memory', '12GB')
    config['region_coverage'] = region_coverage

    config['custom_seed_corpus_dir'] = custom_seed_corpus_dir
    if config['custom_seed_corpus_dir']:
        validate_custom_seed_corpus(config['custom_seed_corpus_dir'],
                                    benchmarks)

    return start_experiment_from_full_config(config)


def start_experiment_from_full_config(config):
    """Start a fuzzer benchmarking experiment from a full (internal) config."""

    set_up_experiment_config_file(config)

    local_experiment = config.get('local_experiment', False)
    if not local_experiment:
        raise ValidationError(
            'This refactored run_experiment.py only supports local experiments.')

    # 1. Set environment variables (before importing builder which checks them)
    setup_environment(config)

    # 2. Initialize SQLite database
    multiprocessing.set_start_method('spawn')
    from database import models
    from database import utils as db_utils
    db_utils.initialize()
    models.Base.metadata.create_all(db_utils.engine)

    # 3. Create Experiment record in DB
    _initialize_experiment_in_db(config, db_utils, models)

    # 4. Build images + create Trial records
    from experiment.build import builder
    from experiment.dispatcher import build_images_for_trials
    trials = build_images_for_trials(
        config['fuzzers'], config['benchmarks'],
        config['trials'], config.get('preemptible_runners', False))
    _initialize_trials_in_db(trials, db_utils)

    # 5. Create work subdirectories
    work_dir = experiment_utils.get_work_dir()
    for subdir in ['experiment-folders', 'measurement-folders']:
        subdir_path = os.path.join(work_dir, subdir)
        if not os.path.exists(subdir_path):
            os.makedirs(subdir_path)

    # 6. Copy resources (config, oss-fuzz corpus, custom seed corpus)
    copy_resources_to_bucket(experiment_utils.CONFIG_DIR, config)

    # 7. Launch all runners and wait for completion
    run_all_trials(config, trials, db_utils)

    # 8. Record experiment end time
    _record_experiment_time_ended(config['experiment'], db_utils, models)

    logs.info('Experiment runners completed.')


def setup_environment(config):
    """Set environment variables needed by the experiment infrastructure."""
    experiment_filestore_path = os.path.abspath(config['experiment_filestore'])
    filesystem.create_directory(experiment_filestore_path)

    os.environ['LOCAL_EXPERIMENT'] = 'True'
    os.environ['FORCE_LOCAL'] = 'True'
    os.environ['EXPERIMENT'] = config['experiment']
    os.environ['EXPERIMENT_FILESTORE'] = config['experiment_filestore']
    os.environ['REPORT_FILESTORE'] = config['report_filestore']
    os.environ['SNAPSHOT_PERIOD'] = str(config['snapshot_period'])
    os.environ['DOCKER_REGISTRY'] = config['docker_registry']
    os.environ['CONCURRENT_BUILDS'] = str(config['concurrent_builds'])
    os.environ['WORKER_POOL_NAME'] = config.get('worker_pool_name', '')

    # SQL database URL for local SQLite
    sql_db_url = (
        f'sqlite:///{os.path.join(experiment_filestore_path, "local.db")}'
        '?check_same_thread=False')
    os.environ['SQL_DATABASE_URL'] = sql_db_url

    # WORK directory = experiment_filestore/experiment_name
    work_dir = os.path.join(experiment_filestore_path, config['experiment'])
    os.environ['WORK'] = work_dir
    filesystem.create_directory(work_dir)

    # Docker registry login if credentials are set
    docker_registry = config['docker_registry']
    registry_user = os.environ.get('FUZZBENCH_REGISTRY_USER')
    registry_password = os.environ.get('FUZZBENCH_REGISTRY_PASSWORD')
    if registry_user and registry_password:
        cmd = (f'docker login {docker_registry} '
               f'--username "{registry_user}" '
               f'--password "{registry_password}"')
        logs.info('Logging into docker registry: %s', docker_registry)
        os.system(cmd)


def _initialize_experiment_in_db(config, db_utils, models):
    """Create the experiment entity in the database."""
    with db_utils.session_scope() as session:
        experiment_exists = session.query(models.Experiment).filter(
            models.Experiment.name == config['experiment']).first()
    if experiment_exists:
        raise Exception('Experiment already exists in database.')

    db_utils.add_all([
        db_utils.get_or_create(
            models.Experiment,
            name=config['experiment'],
            git_hash=config['git_hash'],
            private=config.get('private', True),
            experiment_filestore=config['experiment_filestore'],
            description=config['description']),
    ])


def _initialize_trials_in_db(trials, db_utils):
    """Bulk insert trial records into the database."""
    db_utils.bulk_save(trials)


def _record_experiment_time_ended(experiment_name, db_utils, models):
    """Record experiment end time in the database."""
    with db_utils.session_scope() as session:
        experiment = session.query(models.Experiment).filter(
            models.Experiment.name == experiment_name).one()
    experiment.time_ended = datetime.datetime.utcnow()
    db_utils.add_all([experiment])


def run_all_trials(config, trials, db_utils):
    """Launch all trial runners with cpuset-based scheduling and wait for
    completion."""
    runners_cpus = config.get('runners_cpus')
    runner_num_cpu_cores = config['runner_num_cpu_cores']

    # Calculate cpuset allocation (mirrors scheduler.py logic)
    core_allocation = None
    if runners_cpus is not None:
        processes = runners_cpus // runner_num_cpu_cores
        logs.info('Scheduling runners from core 0 to %d (%d slots).',
                  runner_num_cpu_cores * processes - 1, processes)
        core_allocation = {}
        for cpu in range(0, runner_num_cpu_cores * processes,
                         runner_num_cpu_cores):
            core_allocation[f'{cpu}-{cpu + runner_num_cpu_cores - 1}'] = None

    pending = list(trials)
    running = {}  # cpuset_or_id -> (trial, subprocess.Popen)

    logs.info('Starting %d trials.', len(pending))

    while pending or running:
        # Check for completed runner processes
        for key in list(running):
            trial, proc = running[key]
            if proc.poll() is not None:
                trial.time_ended = datetime.datetime.utcnow()
                db_utils.add_all([trial])
                del running[key]
                if core_allocation is not None:
                    core_allocation[key] = None
                logs.info('Trial %d finished (exit code %d). '
                          'Running: %d, Pending: %d.',
                          trial.id, proc.returncode,
                          len(running), len(pending))

        # Determine free slots
        if core_allocation is not None:
            free = [k for k, v in core_allocation.items() if v is None]
        else:
            free = [None] * len(pending)

        # Launch new trials on free slots
        while pending and free:
            trial = pending.pop(0)
            cpuset = free.pop(0)
            proc = launch_trial(trial, config, cpuset)
            trial.time_started = datetime.datetime.utcnow()
            db_utils.add_all([trial])
            key = cpuset if cpuset is not None else trial.id
            running[key] = (trial, proc)
            if core_allocation is not None and cpuset is not None:
                core_allocation[cpuset] = trial.id
            logs.info('Started trial %d (%s/%s). Running: %d, Pending: %d.',
                      trial.id, trial.fuzzer, trial.benchmark,
                      len(running), len(pending))

        time.sleep(10)

    logs.info('All trials completed.')


def launch_trial(trial, config, cpuset=None):
    """Launch a single trial runner container via subprocess."""
    from experiment import scheduler

    instance_name = experiment_utils.get_trial_instance_name(
        config['experiment'], trial.id)

    startup_script = scheduler.render_startup_script_template(
        instance_name, trial.fuzzer, trial.benchmark, trial.id,
        trial.trial_group_num or 0, config, cpuset)

    script_path = f'/tmp/{instance_name}-start-docker.sh'
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(startup_script)

    proc = subprocess.Popen(
        ['/bin/bash', script_path],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc


def add_oss_fuzz_corpus(benchmark, oss_fuzz_corpora_dir):
    """Add latest public corpus from OSS-Fuzz as the seed corpus for various
    fuzz targets."""
    project = benchmark_utils.get_project(benchmark)
    fuzz_target = benchmark_utils.get_fuzz_target(benchmark)
    oss_fuzz_corpus_target = benchmark_utils.get_oss_fuzz_corpus_target(
        benchmark)

    if oss_fuzz_corpus_target:
        full_fuzz_target = oss_fuzz_corpus_target
    elif not fuzz_target.startswith(project):
        full_fuzz_target = f'{project}_{fuzz_target}'
    else:
        full_fuzz_target = fuzz_target

    src_corpus_url = _OSS_FUZZ_CORPUS_BACKUP_URL_FORMAT.format(
        project=project, fuzz_target=full_fuzz_target)
    dest_corpus_url = os.path.join(oss_fuzz_corpora_dir, f'{benchmark}.zip')
    gsutil.cp(src_corpus_url, dest_corpus_url, parallel=True, expect_zero=False)


def copy_resources_to_bucket(config_dir: str, config: Dict):
    """Copy resources needed for the experiment to the experiment_filestore."""
    experiment_filestore_path = experiment_utils.get_experiment_filestore_path()

    # Send config files.
    base_destination = os.path.join(experiment_filestore_path, 'input')
    destination = os.path.join(base_destination, 'config')
    filestore_utils.rsync(config_dir, destination, parallel=True)

    # If |oss_fuzz_corpus| flag is set, copy latest corpora from each benchmark
    # (if available) in our filestore bucket.
    if config['oss_fuzz_corpus']:
        oss_fuzz_corpora_dir = (
            experiment_utils.get_oss_fuzz_corpora_filestore_path())
        for benchmark in config['benchmarks']:
            add_oss_fuzz_corpus(benchmark, oss_fuzz_corpora_dir)

    if config['custom_seed_corpus_dir']:
        for benchmark in config['benchmarks']:
            benchmark_custom_corpus_dir = os.path.join(
                config['custom_seed_corpus_dir'], benchmark)
            filestore_utils.cp(
                benchmark_custom_corpus_dir,
                experiment_utils.get_custom_seed_corpora_filestore_path() + '/',
                recursive=True,
                parallel=True)


def main():
    """Run an experiment."""
    return run_experiment_main()


def run_experiment_main(args=None):
    """Run an experiment."""
    logs.initialize()

    parser = argparse.ArgumentParser(
        description='Begin an experiment that evaluates fuzzers on one or '
        'more benchmarks.')

    all_benchmarks = benchmark_utils.get_all_benchmarks()
    coverage_benchmarks = benchmark_utils.get_coverage_benchmarks()

    parser.add_argument('-b',
                        '--benchmarks',
                        help=('Benchmark names. '
                              'All code coverage benchmarks of them by '
                              'default.'),
                        nargs='+',
                        required=False,
                        default=coverage_benchmarks,
                        choices=all_benchmarks)
    parser.add_argument('-c',
                        '--experiment-config',
                        help='Path to the experiment configuration yaml file.',
                        required=True)
    parser.add_argument('-e',
                        '--experiment-name',
                        help='Experiment name.',
                        required=True)
    parser.add_argument('-d',
                        '--description',
                        help='Description of the experiment.',
                        required=False)
    parser.add_argument('-cb',
                        '--concurrent-builds',
                        help='Max concurrent builds allowed.',
                        default=DEFAULT_CONCURRENT_BUILDS,
                        type=int,
                        required=False)
    parser.add_argument('-mc',
                        '--measurers-cpus',
                        help='Cpus available to the measurers.',
                        type=int,
                        required=False)
    parser.add_argument('-rc',
                        '--runners-cpus',
                        help='Cpus available to the runners.',
                        type=int,
                        required=False)
    parser.add_argument('-cs',
                        '--custom-seed-corpus-dir',
                        help='Path to the custom seed corpus',
                        required=False)

    all_fuzzers = fuzzer_utils.get_fuzzer_names()
    parser.add_argument('-f',
                        '--fuzzers',
                        help='Fuzzers to use.',
                        nargs='+',
                        required=False,
                        default=None,
                        choices=all_fuzzers)
    parser.add_argument('-ns',
                        '--no-seeds',
                        help='Should trials be conducted without seed corpora.',
                        required=False,
                        default=False,
                        action='store_true')
    parser.add_argument('-nd',
                        '--no-dictionaries',
                        help='Should trials be conducted without dictionaries.',
                        required=False,
                        default=False,
                        action='store_true')
    parser.add_argument('-a',
                        '--allow-uncommitted-changes',
                        help='Skip check that no uncommited changes made.',
                        required=False,
                        default=False,
                        action='store_true')
    parser.add_argument('-cr',
                        '--region-coverage',
                        help='Use region as coverage metric.',
                        required=False,
                        default=False,
                        action='store_true')
    parser.add_argument(
        '-o',
        '--oss-fuzz-corpus',
        help='Should trials be conducted with OSS-Fuzz corpus (if available).',
        required=False,
        default=False,
        action='store_true')
    args = parser.parse_args(args)
    fuzzers = args.fuzzers or all_fuzzers

    concurrent_builds = args.concurrent_builds
    if concurrent_builds is not None and concurrent_builds <= 0:
        parser.error('The concurrent build argument must be a positive number,'
                     f' received {concurrent_builds}.')

    runners_cpus = args.runners_cpus
    if runners_cpus is not None and runners_cpus <= 0:
        parser.error('The runners cpus argument must be a positive number,'
                     f' received {runners_cpus}.')

    # measurers_cpus is kept for backward compatibility but not used here.
    # Measurement is now done separately via run_measurer.py.
    measurers_cpus = args.measurers_cpus

    if args.custom_seed_corpus_dir:
        if args.no_seeds:
            parser.error('Cannot enable options "custom_seed_corpus_dir" and '
                         '"no_seeds" at the same time')
        if args.oss_fuzz_corpus:
            parser.error('Cannot enable options "custom_seed_corpus_dir" and '
                         '"oss_fuzz_corpus" at the same time')

    if benchmark_utils.are_benchmarks_mixed(args.benchmarks):
        benchmark_types = ';'.join(
            [f'{b}: {benchmark_utils.get_type(b)}' for b in args.benchmarks])
        raise ValidationError(
            'Selected benchmarks are a mix between coverage '
            'and bug benchmarks. This is currently not supported.'
            f'Selected benchmarks: {benchmark_types}')

    start_experiment(args.experiment_name,
                     args.experiment_config,
                     args.benchmarks,
                     fuzzers,
                     description=args.description,
                     no_seeds=args.no_seeds,
                     no_dictionaries=args.no_dictionaries,
                     oss_fuzz_corpus=args.oss_fuzz_corpus,
                     allow_uncommitted_changes=args.allow_uncommitted_changes,
                     concurrent_builds=concurrent_builds,
                     measurers_cpus=measurers_cpus,
                     runners_cpus=runners_cpus,
                     region_coverage=args.region_coverage,
                     custom_seed_corpus_dir=args.custom_seed_corpus_dir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
