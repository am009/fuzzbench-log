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
"""Independent measurement script. Runs after all trial runners have completed.
Measures coverage for all unmeasured snapshots and stores results in the
database."""

import argparse
import gc
import multiprocessing
import os
import sys
import time

from common import experiment_utils
from common import logs
from common import yaml_utils

logger = logs.Logger()

MEASUREMENT_LOOP_WAIT = 30


def setup_environment(config):
    """Set environment variables needed by the measurement infrastructure."""
    experiment_filestore_path = os.path.abspath(config['experiment_filestore'])

    os.environ['LOCAL_EXPERIMENT'] = 'True'
    os.environ['FORCE_LOCAL'] = 'True'
    os.environ['EXPERIMENT'] = config['experiment']
    os.environ['EXPERIMENT_FILESTORE'] = config['experiment_filestore']
    os.environ['REPORT_FILESTORE'] = config['report_filestore']
    os.environ['SNAPSHOT_PERIOD'] = str(config.get(
        'snapshot_period', experiment_utils.DEFAULT_SNAPSHOT_SECONDS))
    os.environ['DOCKER_REGISTRY'] = config['docker_registry']

    # SQL database URL for local SQLite
    sql_db_url = (
        f'sqlite:///{os.path.join(experiment_filestore_path, "local.db")}'
        '?check_same_thread=False')
    os.environ['SQL_DATABASE_URL'] = sql_db_url

    # WORK directory = experiment_filestore/experiment_name
    work_dir = os.path.join(experiment_filestore_path, config['experiment'])
    os.environ['WORK'] = work_dir


def main():
    """Run the measurer independently after all trials have completed."""
    logs.initialize(default_extras={
        'component': 'measurer',
    })

    parser = argparse.ArgumentParser(
        description='Measure coverage for completed experiment trials.')
    parser.add_argument('-e', '--experiment-name',
                        help='Experiment name.',
                        required=True)
    parser.add_argument('-c', '--experiment-config',
                        help='Path to the experiment configuration yaml file.',
                        required=True)
    parser.add_argument('-mc', '--measurers-cpus',
                        help='Number of CPUs for parallel measurement.',
                        type=int,
                        required=False,
                        default=None)
    parser.add_argument('-cr', '--region-coverage',
                        help='Use region as coverage metric.',
                        required=False,
                        default=False,
                        action='store_true')
    args = parser.parse_args()

    # Read config
    config = yaml_utils.read(args.experiment_config)
    config['experiment'] = args.experiment_name
    config['region_coverage'] = args.region_coverage
    config['snapshot_period'] = config.get(
        'snapshot_period', experiment_utils.DEFAULT_SNAPSHOT_SECONDS)

    # Setup environment before importing modules that depend on env vars
    setup_environment(config)

    measurers_cpus = args.measurers_cpus
    if measurers_cpus is None:
        measurers_cpus = multiprocessing.cpu_count()
    logger.info('Using %d CPUs for measurement.', measurers_cpus)

    # Initialize multiprocessing
    multiprocessing.set_start_method('spawn')

    # Initialize database
    from database import utils as db_utils
    db_utils.initialize()

    # Import measure_manager after environment is set up
    from experiment.measurer import measure_manager
    from experiment.measurer import coverage_utils

    experiment = config['experiment']
    max_total_time = config['max_total_time']
    region_coverage = args.region_coverage

    logger.info('Starting measurement for experiment: %s', experiment)

    # Build measurer images
    from experiment.build import builder
    from database import models
    with db_utils.session_scope() as session:
        benchmarks = [
            row[0] for row in session.query(models.Trial.benchmark).distinct()
            .filter(models.Trial.experiment == experiment)
        ]
        fuzzers = [
            row[0] for row in session.query(models.Trial.fuzzer).distinct()
            .filter(models.Trial.experiment == experiment)
        ]
    config['benchmarks'] = benchmarks
    config['fuzzers'] = fuzzers
    logger.info('Building measurer images for benchmarks: %s', benchmarks)
    builder.build_all_measurers(benchmarks)

    # Set up coverage binaries and run measurement loop
    with multiprocessing.Pool(measurers_cpus) as pool, \
            multiprocessing.Manager() as manager:
        logger.info('Setting up coverage binaries.')
        measure_manager.set_up_coverage_binaries(pool, experiment)

        multiprocessing_queue = manager.Queue()

        logger.info('Starting measurement loop.')
        while True:
            try:
                measured = measure_manager.measure_all_trials(
                    experiment, max_total_time, pool,
                    multiprocessing_queue, region_coverage)
                if not measured:
                    # No more unmeasured snapshots found
                    logger.info('No more unmeasured snapshots. Done.')
                    break
            except Exception:  # pylint: disable=broad-except
                logger.error('Error occurred during measuring.')

            time.sleep(MEASUREMENT_LOOP_WAIT)

    # Clean up
    gc.collect()

    # Generate final coverage reports
    logger.info('Generating coverage reports.')
    coverage_utils.generate_coverage_reports(config)

    logger.info('Measurement completed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
