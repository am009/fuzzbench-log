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
"""Tests for filesystem_data_utils.py."""

import json

from analysis import filesystem_data_utils


def _write_trial_json(corpus_dir, archive_num, covered_block_count):
    path = corpus_dir / f'corpus-archive-{archive_num:04d}.tar.gz.json'
    path.write_text(json.dumps({'covered_block_count': covered_block_count}))


def test_parse_benchmark_fuzzer_from_dirname_prefers_longest_benchmark():
    parsed = filesystem_data_utils._parse_benchmark_fuzzer_from_dirname(
        'bloaty_fuzz_target_52948c-aflplusplus')

    assert parsed == ('bloaty_fuzz_target_52948c', 'aflplusplus')


def test_get_experiment_data_by_fuzzers(tmp_path):
    first_root = tmp_path / 'experiment-data-1'
    second_root = tmp_path / 'experiment-data-2'

    exp_a = first_root / 'exp-a'
    corpus_a = (exp_a / 'experiment-folders' / 'libxml2_xml-aflplusplus' /
                'trial-1' / 'corpus')
    corpus_a.mkdir(parents=True)
    _write_trial_json(corpus_a, 1, 111)
    _write_trial_json(corpus_a, 2, 222)
    other_corpus = (exp_a / 'experiment-folders' / 're2_fuzzer-libfuzzer' /
                    'trial-9' / 'corpus')
    other_corpus.mkdir(parents=True)
    _write_trial_json(other_corpus, 1, 999)
    config_dir = exp_a / 'input' / 'config'
    config_dir.mkdir(parents=True)
    (config_dir / 'experiment.yaml').write_text(
        'snapshot_period: 60\n'
        'git_hash: abc123\n'
        'experiment_filestore: gs://bucket-a\n')

    exp_b = second_root / 'exp-b'
    corpus_b = (exp_b / 'experiment-folders' /
                'bloaty_fuzz_target-aflplusplus' / 'trial-2' / 'corpus')
    corpus_b.mkdir(parents=True)
    _write_trial_json(corpus_b, 3, 333)

    experiment_df, description = (
        filesystem_data_utils.get_experiment_data_by_fuzzers(
            ['aflplusplus'], [str(first_root), str(second_root)]))

    assert description == (
        f'from filesystem by fuzzer: aflplusplus in '
        f'{first_root},{second_root}')
    assert sorted(experiment_df['experiment'].unique()) == ['exp-a', 'exp-b']
    assert sorted(experiment_df['benchmark'].unique()) == [
        'bloaty_fuzz_target', 'libxml2_xml'
    ]
    assert experiment_df['fuzzer'].unique().tolist() == ['aflplusplus']

    exp_a_rows = experiment_df[experiment_df['experiment'] == 'exp-a']
    assert exp_a_rows['time'].tolist() == [60, 120]
    assert exp_a_rows['edges_covered'].tolist() == [111, 222]
    assert exp_a_rows['git_hash'].unique().tolist() == ['abc123']
    assert exp_a_rows['experiment_filestore'].unique().tolist() == [
        'gs://bucket-a'
    ]

    exp_b_rows = experiment_df[experiment_df['experiment'] == 'exp-b']
    assert exp_b_rows['time'].tolist() == [2700]
    assert exp_b_rows['edges_covered'].tolist() == [333]
