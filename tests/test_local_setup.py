"""Behavioral regressions for reviewed setup, safe return and cache separation."""
from contextlib import redirect_stdout, redirect_stderr
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'web'))
from local_setup import CACHE_ROOT, DEFAULTS, PREFIX, describe, assess_resources
from test_local_resources import observation
spec = importlib.util.spec_from_file_location('local_instance_setup_test', ROOT / 'bin/local_instance.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class LocalSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for key, value in [('ROOT', self.root), ('ENV_FILE', self.root / '.env')]:
            patch = mock.patch.object(cli, key, value); patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch.object(cli, 'resources', return_value=assess_resources(observation())); patch.start(); self.addCleanup(patch.stop)
        self.output = io.StringIO()

    def run_cli(self, *args, interactive=False, answers=()):
        with mock.patch.object(sys, 'argv', ['local_instance.py', *args]), mock.patch('sys.stdin.isatty', return_value=interactive), \
                mock.patch('builtins.input', side_effect=answers), redirect_stdout(self.output), redirect_stderr(self.output):
            return cli.main()

    def fresh(self, *args):
        self.assertEqual(self.run_cli('init', '--non-interactive', *args), 0, self.output.getvalue())
        return cli.read_config()[1]

    def test_cli_saves_concurrency_and_detector_targets(self):
        values = self.fresh('--concurrent-jobs', '3', '--genome-parallelism', '3', '--record-parallelism', '3')
        self.assertEqual(values['WORKER_CONCURRENCY'], '3')
        self.assertEqual(values[PREFIX + 'PUBLIC_GENOME_PARALLELISM'], '3')
        self.assertEqual(values[PREFIX + 'PUBLIC_ANTISMASH_RECORD_PARALLELISM'], '3')
        self.assertEqual(describe(values)['concurrent_jobs'], 3)

    def test_defaults_shortcut_saves_recommended_settings_and_prepares_without_questions(self):
        with mock.patch.object(cli, 'weave') as weave:
            self.assertEqual(self.run_cli('init', '--defaults', interactive=True), 0)
            weave.assert_called_once()
            args = weave.call_args.args[0]
            self.assertTrue(args.non_interactive)
            self.assertTrue(args.open_browser)
        values = cli.read_config()[1]
        settings = describe(values)
        self.assertEqual((settings['worker_cpus'], settings['worker_memory_gib']), (4, 16))
        self.assertTrue(settings['cache_enabled'])
        self.assertTrue(settings['automatic_startup'])
        self.assertTrue(settings['open_browser'])
        self.assertEqual(values[PREFIX + 'JOB_RETENTION_DAYS'], 'never')
        self.assertEqual(values[PREFIX + 'BIND_ADDRESS'], '127.0.0.1')
        for name in ('JOB_TOKEN_SECRET', 'ADMIN_TOKEN'):
            self.assertNotIn(values[PREFIX + name], self.output.getvalue())

    def test_defaults_terminal_banner_is_independent_of_accepting_defaults(self):
        self.fresh()
        original = cli.ENV_FILE.read_bytes()
        for extra, input_tty, output_tty, expected in [([], True, True, 1),
                (['--non-interactive'], True, True, 0), ([], True, False, 0), ([], False, True, 0)]:
            self.output = io.StringIO()
            with mock.patch.object(self.output, 'isatty', return_value=output_tty), \
                    mock.patch.object(cli, 'weave') as weave:
                self.assertEqual(self.run_cli('init', '--defaults', *extra, interactive=input_tty), 0)
                weave.assert_not_called()
            self.assertEqual(self.output.getvalue().count('Please cite:'), expected)
            self.assertEqual(cli.ENV_FILE.read_bytes(), original)

    def test_defaults_shortcut_preserves_existing_setup_and_resource_checks(self):
        values = self.fresh('--no-cache', '--port', '8098')
        original = cli.ENV_FILE.read_bytes()
        with mock.patch.object(cli, 'weave') as weave:
            self.assertEqual(self.run_cli('init', '--defaults', interactive=True), 0)
            self.assertEqual(self.run_cli('init', '--defaults', '--reconfigure'), 1)
            weave.assert_not_called()
        self.assertEqual(cli.ENV_FILE.read_bytes(), original)
        self.assertIn('./bin/local_instance.sh start', self.output.getvalue())
        cli.ENV_FILE.unlink()
        with mock.patch.object(cli, 'resources', return_value=assess_resources(observation(total=16))), \
                mock.patch.object(cli, 'weave') as weave:
            self.assertEqual(self.run_cli('init', '--defaults', interactive=True), 1)
            weave.assert_not_called()
        self.assertFalse(cli.ENV_FILE.exists())

    def test_recommended_repeat_review_and_explicit_reconfiguration_preserve_secrets_and_data(self):
        values = self.fresh()
        self.assertEqual(describe(values)['cache_enabled'], True)
        self.assertEqual(values[PREFIX + 'ACCESSION_CACHE_ROOT'], CACHE_ROOT)
        self.assertEqual(values[PREFIX + 'LOCAL_RESTART_POLICY'], 'no')
        self.assertEqual(cli.ENV_FILE.stat().st_mode & 0o777, 0o600)
        original = cli.ENV_FILE.read_bytes()
        result = self.root / 'saved-result'; result.write_bytes(b'retained')
        self.assertEqual(self.run_cli('init', interactive=True), 0)
        self.assertEqual(cli.ENV_FILE.read_bytes(), original)
        self.assertEqual(self.run_cli('init', '--reconfigure', '--non-interactive', '--port', '8089'), 1)
        self.assertEqual(cli.ENV_FILE.read_bytes(), original)
        self.assertEqual(self.run_cli('init', '--reconfigure', '--non-interactive', '--apply', '--port', '8089', '--no-cache'), 0)
        updated = cli.read_config()[1]
        for key in ('JOB_TOKEN_SECRET', 'ADMIN_TOKEN'):
            self.assertEqual(values[PREFIX + key], updated[PREFIX + key])
            self.assertNotIn(values[PREFIX + key], self.output.getvalue())
        self.assertEqual(updated[PREFIX + 'PUBLIC_BASE_URL'], 'http://127.0.0.1:8089/')
        self.assertFalse(describe(updated)['cache_enabled'])
        self.assertEqual(result.read_bytes(), b'retained')

    def test_custom_prompts_and_cancellation(self):
        answers = ['3', 'many', '99', '6', '3', '3', '3', '3', '20', '8090', '2', '12', '7', '75', '80', 'yes', 'no', 'yes', 'yes', 'yes', 'no']
        self.assertEqual(self.run_cli('init', interactive=True, answers=answers), 0, self.output.getvalue())
        settings = describe(cli.read_config()[1])
        self.assertEqual((settings['worker_cpus'], settings['job_cpus'], settings['worker_memory_gib']), (6, 3, 20))
        self.assertEqual((settings['cache_max_bytes'], settings['cache_max_entries'], settings['cache_max_age_seconds']), (2 * 1024**3, 12, 7 * 86400))
        self.assertEqual(cli.read_config()[1]['PIPELINE_CPUS'], '3')
        self.assertTrue(settings['automatic_startup']); self.assertTrue(settings['open_browser'])
        self.assertFalse(settings['cache_enabled'])
        self.assertEqual(cli.read_config()[1][PREFIX + 'MAX_ACCESSIONS'], '75')
        self.assertEqual(cli.read_config()[1][PREFIX + 'MAX_GENOME_FILES'], '80')
        original = cli.ENV_FILE.read_bytes()
        for answers in (['4'], ['1', 'no', 'no', 'no']):
            self.assertEqual(self.run_cli('init', '--reconfigure', interactive=True, answers=answers), 0)
            self.assertEqual(cli.ENV_FILE.read_bytes(), original)

    def test_invalid_values_resources_and_cancel_never_write(self):
        for args in (['--port', '0'], ['--port', '65536'], ['--worker-cpus', '9'], ['--job-cpus', '5'],
                     ['--memory-gib', '15'], ['--memory-gib', '31'], ['--cache-entries', '-1'], ['--cache-days', '0']):
            self.assertEqual(self.run_cli('init', '--non-interactive', *args), 1, args)
            self.assertFalse(cli.ENV_FILE.exists())
        self.assertEqual(self.run_cli('init', interactive=True, answers=['1', 'no', 'no', 'no']), 0)
        self.assertFalse(cli.ENV_FILE.exists())
        with mock.patch('builtins.input', side_effect=EOFError), mock.patch('sys.stdin.isatty', return_value=True), \
                mock.patch.object(sys, 'argv', ['local_instance.py', 'init']), redirect_stdout(self.output), redirect_stderr(self.output):
            self.assertEqual(cli.main(), 130)
        self.assertFalse(cli.ENV_FILE.exists())

    def test_hosted_custom_cache_and_concurrent_edits_are_not_replaced(self):
        self.fresh()
        original, values = cli.read_config()
        cli.write_config(original, {PREFIX + 'ACCESS_PROFILE': 'hosted'})
        original = cli.ENV_FILE.read_bytes()
        self.assertEqual(self.run_cli('init', '--reconfigure', '--non-interactive', '--apply'), 1)
        self.assertEqual(cli.ENV_FILE.read_bytes(), original)
        with self.assertRaises(ValueError): cli.write_config('different', {'HOST_PORT': '8090'})
        self.assertEqual(cli.ENV_FILE.read_bytes(), original)
        cli.ENV_FILE.unlink(); cli.ENV_FILE.symlink_to(self.root / 'missing')
        self.assertEqual(self.run_cli('init', '--non-interactive'), 1)
        self.assertFalse((self.root / 'missing').exists())

    def test_start_is_bounded_no_acquisition_and_stop_disable_do_not_start_services(self):
        self.fresh('--autostart', '--open-browser', '--port', '8091')
        with mock.patch.object(cli, 'docker_available'), mock.patch.object(cli, 'compose') as compose, \
                mock.patch.object(cli, 'wait_ready') as ready, mock.patch.object(cli, 'open_browser') as browser, mock.patch.object(cli.subprocess, 'run'):
            compose.return_value.stdout = 'clusterweave-web:latest\nclusterweave-worker:latest\n'
            for _ in range(2): self.assertEqual(self.run_cli('start'), 0)
            self.assertEqual(browser.call_args.args, ('http://127.0.0.1:8091/',))
            self.assertEqual(browser.call_count, 2)  # one tab for each explicit invocation
            for call in compose.call_args_list:
                self.assertNotIn('prepare-runtime', call.args)
                self.assertNotIn('build', call.args)
                if call.args[1] != 'config': self.assertIn('never', call.args)
            ready.side_effect = ValueError('not ready')
            browser.reset_mock()
            self.assertEqual(self.run_cli('open', '--timeout', '1'), 1)
            browser.assert_not_called()
            compose.reset_mock()
            self.assertEqual(self.run_cli('stop'), 0)
            self.assertEqual(compose.call_args.args[1:], ('stop',))
            compose.return_value.stdout = 'fixture-web fixture-worker\n'
            with mock.patch.object(cli.subprocess, 'run') as run:
                self.assertEqual(self.run_cli('disable-autostart'), 0)
                self.assertEqual(run.call_args.args[0], ['docker', 'update', '--restart=no', 'fixture-web', 'fixture-worker'])
                self.assertEqual(self.run_cli('disable-autostart'), 0)
            settings = describe(cli.read_config()[1])
            self.assertFalse(settings['automatic_startup']); self.assertFalse(settings['open_browser'])
            self.assertEqual(compose.call_args.args[1:], ('ps', '--all', '--quiet', 'web', 'worker'))

    def test_missing_docker_images_and_browser_integration_leave_a_manual_path(self):
        values = self.fresh()
        original = cli.ENV_FILE.read_bytes()
        with mock.patch.object(cli.subprocess, 'run', side_effect=FileNotFoundError('docker')), mock.patch.object(cli, 'compose') as compose:
            self.assertEqual(self.run_cli('start'), 1)
            compose.assert_not_called()
        self.assertEqual(cli.ENV_FILE.read_bytes(), original)
        with mock.patch.object(cli, 'docker_available'), mock.patch.object(cli, 'compose') as compose, \
                mock.patch.object(cli.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['docker', 'image', 'inspect'])), \
                mock.patch.object(cli, 'open_browser') as browser:
            compose.return_value.stdout = 'clusterweave-worker:latest\nclusterweave-web:latest'
            self.assertEqual(self.run_cli('start'), 1)
            self.assertEqual(compose.call_count, 1)
            browser.assert_not_called()
        with mock.patch.object(cli.platform, 'system', return_value='Linux'), mock.patch.object(cli.platform, 'release', return_value='generic'), \
                mock.patch.dict(os.environ, {}, clear=True), redirect_stdout(self.output), mock.patch.object(cli.subprocess, 'run') as launch:
            cli.open_browser('http://127.0.0.1:8097/')
            launch.assert_not_called()
            self.assertIn('http://127.0.0.1:8097/', self.output.getvalue())
        for system, release, command in [('Darwin', 'generic', 'open'), ('Linux', 'generic', 'xdg-open'), ('Linux', 'microsoft', 'wslview')]:
            with mock.patch.object(cli.platform, 'system', return_value=system), mock.patch.object(cli.platform, 'release', return_value=release), \
                    mock.patch.dict(os.environ, {'DISPLAY': ':1'}), mock.patch.object(cli.shutil, 'which', return_value='/fixture/wslview'), \
                    mock.patch.object(cli.subprocess, 'run') as launch:
                cli.open_browser('http://127.0.0.1:8097/')
                self.assertEqual(launch.call_count, 1)
                self.assertEqual(launch.call_args.args[0], [command, 'http://127.0.0.1:8097/'])

    def test_existing_operator_cache_is_displayed_and_never_migrated(self):
        self.fresh()
        original, _ = cli.read_config()
        cli.write_config(original, {PREFIX + 'ACCESSION_CACHE_ROOT': '/operator/cache'})
        original = cli.ENV_FILE.read_bytes()
        self.assertEqual(describe(cli.read_config()[1])['storage'], 'Existing operator-managed cache storage')
        self.assertEqual(self.run_cli('init', '--non-interactive'), 0)
        self.assertEqual(self.run_cli('init', '--reconfigure', '--non-interactive', '--apply', '--cache'), 1)
        self.assertEqual(cli.ENV_FILE.read_bytes(), original)

    def test_readiness_rejects_stale_status_and_opens_only_after_worker_ready(self):
        values = self.fresh('--port', '8092')
        response = mock.MagicMock()
        response.__enter__.return_value = response
        opener = mock.Mock(); opener.open.return_value = response
        payloads = [{'online': True}, {'ready': True, 'stale': True}, {'ready': True}]
        with mock.patch.object(cli.urllib.request, 'build_opener', return_value=opener), \
                mock.patch.object(cli.json, 'load', side_effect=payloads), mock.patch.object(cli.time, 'sleep'):
            cli.wait_ready(describe(values), values, 2)
        self.assertEqual(opener.open.call_count, 3)
        self.assertEqual(opener.open.call_args.args[0].full_url, 'http://127.0.0.1:8092/api/system/status')
        with mock.patch.object(cli.urllib.request, 'build_opener', return_value=opener), \
                mock.patch.object(cli.time, 'monotonic', side_effect=[0, 2]):
            with self.assertRaisesRegex(ValueError, 'Return manually'): cli.wait_ready(describe(values), values, 1)

    def test_lower_worker_budget_caps_the_default_job_budget_before_review(self):
        values = self.fresh('--worker-cpus', '2')
        self.assertEqual(values['CLUSTERWEAVE_MAX_CPUS_PER_JOB'], '2')
        self.assertEqual(values['PIPELINE_CPUS'], '2')
        self.assertIn('job limit: 2 CPUs', self.output.getvalue())

    def test_preflight_blocks_before_prompts_and_rechecks_before_apply(self):
        with mock.patch.object(cli, 'resources', return_value=assess_resources(observation(total=16))), \
                mock.patch('builtins.input') as prompt, mock.patch('sys.stdin.isatty', return_value=True), \
                mock.patch.object(sys, 'argv', ['local_instance.py', 'init']), redirect_stdout(self.output), redirect_stderr(self.output):
            self.assertEqual(cli.main(), 1)
            prompt.assert_not_called()
        self.assertFalse(cli.ENV_FILE.exists())
        values = self.fresh()
        original = cli.ENV_FILE.read_bytes()
        reports = [assess_resources(observation()), assess_resources(observation(available=8))]
        with mock.patch.object(cli, 'resources', side_effect=reports):
            self.assertEqual(self.run_cli('init', '--reconfigure', '--non-interactive', '--apply', '--port', '8098'), 1)
        self.assertEqual(cli.ENV_FILE.read_bytes(), original)
        for key in ['CLUSTERWEAVE_JOB_TOKEN_SECRET', 'CLUSTERWEAVE_ADMIN_TOKEN']:
            self.assertNotIn(values[key], self.output.getvalue())

    def test_default_budgets_follow_scan_and_scan_json_never_touches_config(self):
        with mock.patch.object(cli, 'resources', return_value=assess_resources(observation(cpus=32, total=128, available=100, docker_cpus=32, docker_memory=128))):
            values = self.fresh()
        self.assertEqual(values['CLUSTERWEAVE_WORKER_MEM_LIMIT'], '32g')
        original = cli.ENV_FILE.read_bytes()
        output = io.StringIO()
        with mock.patch.object(sys, 'argv', ['local_instance.py', 'scan', '--json']), redirect_stdout(output):
            self.assertEqual(cli.main(), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report['verdict'], 'ready')
        self.assertEqual(cli.ENV_FILE.read_bytes(), original)
        self.assertNotIn('CLUSTERWEAVE_JOB_TOKEN_SECRET', output.getvalue())

    def test_maximum_recommendation_uses_measured_capacity_and_preserves_secrets(self):
        values = self.fresh('--recommendation', 'maximum')
        self.assertEqual((values[PREFIX + 'WORKER_CPU_LIMIT'], values[PREFIX + 'MAX_CPUS_PER_JOB'],
                          values[PREFIX + 'WORKER_MEM_LIMIT']), ('7', '7', '28g'))
        original = cli.ENV_FILE.read_bytes()
        with mock.patch.object(cli, 'weave') as weave:
            self.assertEqual(self.run_cli('init', '--reconfigure', interactive=True,
                                         answers=['2', 'no', 'no', 'yes', 'no']), 0)
            weave.assert_not_called()
        self.assertEqual(cli.ENV_FILE.read_bytes(), original)
        self.assertEqual(self.run_cli('init', '--reconfigure', '--non-interactive', '--apply',
                                     '--recommendation', 'conservative'), 0)
        updated = cli.read_config()[1]
        self.assertEqual(updated[PREFIX + 'WORKER_CPU_LIMIT'], '4')
        self.assertEqual(updated[PREFIX + 'JOB_TOKEN_SECRET'], values[PREFIX + 'JOB_TOKEN_SECRET'])

    def test_interactive_startup_banner_once_and_scripted_scan_remains_json(self):
        for width in [39, 80]:
            self.output = io.StringIO()
            with mock.patch.object(self.output, 'isatty', return_value=True), \
                    mock.patch.object(cli.shutil, 'get_terminal_size', return_value=os.terminal_size((width, 24))):
                self.assertEqual(self.run_cli('init', interactive=True, answers=['4']), 0)
            text = self.output.getvalue()
            self.assertEqual(text.count('Please cite:'), 1)
            self.assertIn('10.11578/PMI/dc.20260608.2', text)
            self.assertNotIn('\x1b', text)
        self.output = io.StringIO()
        with mock.patch('sys.stdout.isatty', return_value=True):
            self.assertEqual(self.run_cli('scan', '--json', interactive=True), 0)
        self.assertEqual(json.loads(self.output.getvalue())['verdict'], 'ready')
        self.assertFalse(cli.ENV_FILE.exists())

    def test_prompt_retries_and_ready_confirmation_connect_only_after_saving(self):
        with mock.patch.object(cli, 'weave') as weave:
            self.assertEqual(self.run_cli('init', interactive=True,
                answers=['oops', '1', 'maybe', 'n', 'n', 'y', 'y']), 0)
            weave.assert_called_once()
            self.assertTrue(cli.ENV_FILE.exists())
        self.assertIn('Pick 1, 2, 3 or 4', self.output.getvalue())
        self.assertIn('A quick yes or no', self.output.getvalue())
        self.assertEqual(self.run_cli('init', '--reconfigure', interactive=True,
                                     answers=['1', 'no', 'no', 'yes', 'no']), 0)
        with mock.patch.object(cli, 'weave') as weave:
            self.assertEqual(self.run_cli('init', '--reconfigure', '--apply', '--non-interactive', '--weave'), 0)
            weave.assert_called_once()

    def test_interrupted_confirmation_keeps_applied_settings_and_has_resume_command(self):
        self.assertEqual(self.run_cli('init', interactive=True,
                                     answers=['1', 'no', 'no', 'yes', EOFError()]), 130)
        self.assertTrue(cli.ENV_FILE.exists())
        values = cli.read_config()[1]
        self.assertTrue(values[PREFIX + 'JOB_TOKEN_SECRET'])
        self.assertIn('weave to resume', self.output.getvalue())

    def test_weave_orders_build_web_browser_preparation_check_worker_and_ready(self):
        self.fresh('--port', '8099')
        events = []
        def compose(values, *args, **kwargs):
            events.append(args)
            if 'build' in args or 'prepare-runtime' in args or 'check-runtime' in args:
                self.assertIsNone(kwargs.get('timeout', 180))
            return mock.Mock(stdout='')
        with mock.patch.object(cli, 'docker_available'), mock.patch.object(cli, 'compose', side_effect=compose), \
                mock.patch.object(cli, 'wait_web', side_effect=lambda *a: events.append(('web-ready',))), \
                mock.patch.object(cli, 'wait_ready', side_effect=lambda *a: events.append(('worker-ready',))), \
                mock.patch.object(cli, 'open_browser', side_effect=lambda url: events.append(('browser', url))):
            self.assertEqual(self.run_cli('weave', '--open-browser'), 0)
        self.assertEqual(events[0], ('ps', '--status', 'running', '--quiet', 'worker'))
        self.assertEqual(events[1], ('build',))
        self.assertEqual(events[3], ('up', '-d', '--no-deps', '--no-build', '--pull', 'never', 'web'))
        self.assertEqual(events[4:6], [('web-ready',), ('browser', 'http://127.0.0.1:8099/')])
        self.assertIn('prepare-runtime', events[6])
        self.assertEqual(events[6][-2:], ('--status-file', '/data/worker/status.json'))
        self.assertIn('check-runtime', events[7])
        self.assertEqual(events[8], ('up', '-d', '--no-build', '--pull', 'never', 'worker'))
        self.assertEqual(events[9], ('worker-ready',))
        self.assertFalse(any('setup-status' in event and 'error' in event for event in events))

    def test_weave_failure_does_not_start_worker_and_retry_keeps_configuration(self):
        values = self.fresh()
        original = cli.ENV_FILE.read_bytes()
        for failure in ['build', 'prepare-runtime', 'check-runtime']:
            calls = []
            def compose(values, *args, **kwargs):
                calls.append(args)
                if failure in args: raise subprocess.CalledProcessError(1, ['docker', 'compose', failure])
                return mock.Mock(stdout='')
            with mock.patch.object(cli, 'docker_available'), mock.patch.object(cli, 'compose', side_effect=compose), \
                    mock.patch.object(cli, 'wait_web'), mock.patch.object(cli, 'wait_ready') as ready, \
                    mock.patch.object(cli, 'open_browser') as browser:
                self.assertEqual(self.run_cli('weave', '--non-interactive'), 1)
                ready.assert_not_called(); browser.assert_not_called()
            self.assertFalse(any(call[0] == 'up' and call[-1] == 'worker' for call in calls))
            if failure != 'build': self.assertEqual(calls[-1][-2:], ('setup-status', 'error'))
            self.assertEqual(cli.ENV_FILE.read_bytes(), original)
            self.assertNotIn(values[PREFIX + 'JOB_TOKEN_SECRET'], self.output.getvalue())
        with mock.patch.object(cli, 'compose') as compose, mock.patch.object(cli, 'docker_available'):
            compose.return_value.stdout = 'running-worker-id'
            self.assertEqual(self.run_cli('weave'), 1)
            self.assertEqual(compose.call_count, 1)
        with mock.patch.object(cli, 'resources', return_value=assess_resources(observation(docker_state='remote'))), \
                mock.patch.object(cli, 'compose') as compose, mock.patch.object(cli, 'docker_available') as docker:
            self.assertEqual(self.run_cli('weave'), 1)
            compose.assert_not_called(); docker.assert_not_called()

    def test_disabled_cache_and_external_profile_have_no_scientific_cache_access(self):
        for file in ('docker-compose.yml', 'clusterweave.yml'):
            result = subprocess.run(['docker', 'compose', '--env-file', '/dev/null', '-f', str(ROOT / file), 'config', '--format', 'json'], capture_output=True, text=True, check=True)
            services = json.loads(result.stdout)['services']
            for name, service in services.items():
                targets = [mount['target'] for mount in service['volumes']]
                if file == 'docker-compose.yml' and name == 'worker':
                    self.assertIn('/var/cache/clusterweave', targets)
                    self.assertEqual(service['environment']['CLUSTERWEAVE_ACCESSION_CACHE_ROOT'], '')
                else:
                    self.assertNotIn('/var/cache/clusterweave', targets)
            if file == 'clusterweave.yml':
                self.assertNotIn('/var/run/docker.sock', [m['target'] for m in services['worker']['volumes']])


if __name__ == '__main__': unittest.main()
