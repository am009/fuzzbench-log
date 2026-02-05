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
"""Script to push fuzzer/benchmark images to a registry."""

import argparse
import subprocess
import sys


def get_runner_image_url(benchmark, fuzzer, docker_registry):
    """Get the URL of the docker runner image."""
    return f'{docker_registry}/runners/{fuzzer}/{benchmark}:latest'


def get_builder_image_url(benchmark, fuzzer, docker_registry):
    """Get the URL of the docker builder image (measurer uses fuzzer='coverage')."""
    return f'{docker_registry}/builders/{fuzzer}/{benchmark}'


def get_dispatcher_image_url(docker_registry):
    """Get the URL of the dispatcher image."""
    return f'{docker_registry}/dispatcher-image'


def push_image(image_url):
    """Push docker image to registry."""
    print(f'Pushing image: {image_url}')
    result = subprocess.run(['docker', 'push', image_url],
                            capture_output=True,
                            text=True)
    if result.returncode != 0:
        print(f'Failed to push image {image_url}: {result.stderr}',
              file=sys.stderr)
        return False
    print(f'Successfully pushed image: {image_url}')
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Push fuzzer/benchmark images to a registry.')
    parser.add_argument('-f',
                        '--fuzzers',
                        nargs='+',
                        required=True,
                        help='Fuzzer names')
    parser.add_argument('-b',
                        '--benchmarks',
                        nargs='+',
                        required=True,
                        help='Benchmark names')
    parser.add_argument('-r',
                        '--registry',
                        help='Docker registry')
    args = parser.parse_args()

    fuzzers = args.fuzzers
    benchmarks = args.benchmarks
    registry = args.registry

    failed_images = []

    # Push dispatcher image first
    print('=' * 50)
    print('Pushing dispatcher image...')
    print('=' * 50)
    dispatcher_url = get_dispatcher_image_url(registry)
    if not push_image(dispatcher_url):
        failed_images.append(dispatcher_url)

    # Push measurer (coverage builder) images for each benchmark
    print('=' * 50)
    print('Pushing measurer images...')
    print('=' * 50)
    for benchmark in benchmarks:
        measurer_url = get_builder_image_url(benchmark, 'coverage', registry)
        if not push_image(measurer_url):
            failed_images.append(measurer_url)

    # Push runner images for each fuzzer/benchmark combination
    print('=' * 50)
    print('Pushing runner images...')
    print('=' * 50)
    for fuzzer in fuzzers:
        for benchmark in benchmarks:
            runner_url = get_runner_image_url(benchmark, fuzzer, registry)
            if not push_image(runner_url):
                failed_images.append(runner_url)

    # Summary
    print('=' * 50)
    print('Summary')
    print('=' * 50)
    total_images = 1 + len(benchmarks) + len(fuzzers) * len(benchmarks)
    success_count = total_images - len(failed_images)
    print(f'Total: {total_images}, Success: {success_count}, Failed: {len(failed_images)}')

    if failed_images:
        print('\nFailed images:')
        for img in failed_images:
            print(f'  - {img}')
        return 1

    print('\nAll images pushed successfully!')
    return 0


if __name__ == '__main__':
    sys.exit(main())
