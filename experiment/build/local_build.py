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
"""Module for building things on Google Cloud Build for use in trials."""

import os
import subprocess
from typing import Tuple

from common import benchmark_utils
from common import environment
from common import experiment_utils
from common import logs
from common import new_process
from common import utils

logger = logs.Logger()  # pylint: disable=invalid-name


def _pull_image(image_url):
    """Pull docker image from registry."""
    logger.info('Pulling image: %s', image_url)
    result = subprocess.run(['docker', 'pull', image_url])
    if result.returncode != 0:
        logger.error('Failed to pull image %s', image_url)
        raise subprocess.CalledProcessError(result.returncode, 'docker pull')
    logger.info('Successfully pulled image: %s', image_url)


def make(targets):
    """Invoke |make| with |targets| and return the result."""
    command = ['make', '-j'] + targets
    # logger.warning(" ".join(command))
    return new_process.execute(command, cwd=utils.ROOT_DIR)


def build_base_images() -> Tuple[int, str]:
    """Build base images locally."""
    return make(['base-image', 'base-builder-new', 'worker'])


def get_shared_coverage_binaries_dir():
    """Returns the shared coverage binaries directory."""
    experiment_filestore_path = experiment_utils.get_experiment_filestore_path()
    return os.path.join(experiment_filestore_path, 'coverage-binaries')


def make_shared_coverage_binaries_dir():
    """Make the shared coverage binaries directory."""
    shared_coverage_binaries_dir = get_shared_coverage_binaries_dir()
    if os.path.exists(shared_coverage_binaries_dir):
        return
    os.makedirs(shared_coverage_binaries_dir)


def build_coverage(benchmark):
    """Build (locally) coverage image for benchmark."""
    docker_registry = environment.get('DOCKER_REGISTRY')
    builder_image_url = benchmark_utils.get_builder_image_url(
        benchmark, 'coverage', docker_registry)

    if os.environ.get('FUZZBENCH_NO_BUILD'):
        # Pull the coverage image instead of building
        _pull_image(builder_image_url)
        # Create a fake successful result
        result = type('Result', (), {'retcode': 0})()
    else:
        image_name = f'build-coverage-{benchmark}'
        result = make([image_name])
        if result.retcode:
            return result

    make_shared_coverage_binaries_dir()
    copy_coverage_binaries(benchmark)
    return result


def copy_coverage_binaries(benchmark):
    """Copy coverage binaries in a local experiment."""
    shared_coverage_binaries_dir = get_shared_coverage_binaries_dir()
    mount_arg = f'{shared_coverage_binaries_dir}:{shared_coverage_binaries_dir}'
    builder_image_url = benchmark_utils.get_builder_image_url(
        benchmark, 'coverage', environment.get('DOCKER_REGISTRY'))
    coverage_build_archive = f'coverage-build-{benchmark}.tar.gz'
    coverage_build_archive_shared_dir_path = os.path.join(
        shared_coverage_binaries_dir, coverage_build_archive)
    command = (
        '(cd /out; '
        f'tar -czvf {coverage_build_archive_shared_dir_path} * /src /work)')
    return new_process.execute([
        'docker', 'run', '-v', mount_arg, builder_image_url, '/bin/bash', '-c',
        command
    ])


def build_fuzzer_benchmark(fuzzer: str, benchmark: str) -> bool:
    """Builds |benchmark| for |fuzzer|."""
    if os.environ.get('FUZZBENCH_NO_BUILD'):
        # Pull the runner image instead of building
        docker_registry = environment.get('DOCKER_REGISTRY')
        experiment = experiment_utils.get_experiment_name()
        runner_image_url = benchmark_utils.get_runner_image_url(
            experiment, benchmark, fuzzer, docker_registry)
        _pull_image(runner_image_url)
    else:
        image_name = f'build-{fuzzer}-{benchmark}'
        make([image_name])
