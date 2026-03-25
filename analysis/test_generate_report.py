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
"""Tests for generate_report.py."""

from unittest import mock

from analysis import generate_report
from analysis import test_data_utils


def test_get_arg_parser_accepts_multiple_experiment_data_dirs():
    parser = generate_report.get_arg_parser()

    args = parser.parse_args([
        '--from-filesystem',
        '--experiment-data-dir',
        '/tmp/one',
        '--experiment-data-dir',
        '/tmp/two',
        'aflplusplus',
    ])

    assert args.from_filesystem is True
    assert args.experiment_data_dir == ['/tmp/one', '/tmp/two']
    assert args.experiments == ['aflplusplus']


@mock.patch('analysis.filesystem_data_utils.get_experiment_data_by_fuzzers')
def test_get_experiment_data_uses_fuzzer_filesystem_loader(mock_loader):
    mock_loader.return_value = ('df', 'desc')

    experiment_df, description = generate_report.get_experiment_data(
        ['aflplusplus'],
        'aflplusplus',
        from_cached_data=False,
        data_path='/tmp/unused.csv',
        from_filesystem=True,
        experiment_data_dirs=['/tmp/one', '/tmp/two'])

    assert (experiment_df, description) == ('df', 'desc')
    mock_loader.assert_called_once_with(['aflplusplus'], ['/tmp/one', '/tmp/two'])


@mock.patch('analysis.generate_report.filesystem.write')
@mock.patch('analysis.generate_report.rendering.render_report',
            return_value='<html></html>')
@mock.patch('analysis.generate_report.plotting.Plotter')
@mock.patch('analysis.generate_report.filesystem.create_directory')
@mock.patch('analysis.generate_report.get_experiment_data')
def test_generate_report_defaults_name_to_joined_fuzzers_in_filesystem_mode(
        mock_get_experiment_data, _mock_create_directory, _mock_plotter,
        mock_render_report, _mock_write, tmp_path):
    mock_get_experiment_data.return_value = (
        test_data_utils.create_experiment_data(
            experiment='filesystem-exp').reset_index(drop=True),
        'filesystem description')

    generate_report.generate_report(
        experiment_names=['aflplusplus', 'libfuzzer'],
        report_directory=str(tmp_path),
        from_filesystem=True)

    assert mock_get_experiment_data.call_args.kwargs['experiment_data_dirs'] is None
    experiment_ctx = mock_render_report.call_args.args[0]
    assert experiment_ctx.name == 'aflplusplus-libfuzzer'
