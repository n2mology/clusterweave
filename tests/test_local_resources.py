"""Resource scans respect observable limits and never invent spare capacity."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'bin'), str(ROOT / 'web')]
import local_resources as probe
from local_setup import assess_resources

GIB = 1024**3


def observation(*, cpus=8, total=32, available=32, docker_cpus=8, docker_memory=32, docker_state='available'):
    return {'host': {'logical_cpus': cpus, 'effective_cpus': cpus, 'total_memory_bytes': total * GIB,
                     'effective_memory_bytes': total * GIB,
                     'available_memory_bytes': None if available is None else available * GIB,
                     'availability_source': 'controlled fixture'},
            'docker': {'state': docker_state, 'cpus': docker_cpus, 'memory_bytes': docker_memory * GIB},
            'disk_free_bytes': 100 * GIB, 'observed_at': 1}


class LocalResourceTests(unittest.TestCase):
    def test_small_busy_unknown_and_docker_limited_machines_are_distinguished(self):
        for inputs, expected in [({'cpus': 2}, 'blocked'), ({'total': 16}, 'blocked'),
                                 ({'total': 64, 'available': 10}, 'busy'), ({'available': None}, 'unknown'),
                                 ({'docker_cpus': 2}, 'blocked'), ({'docker_memory': 16}, 'blocked')]:
            with self.subTest(inputs=inputs):
                report = assess_resources(observation(**inputs))
                self.assertEqual(report['verdict'], expected)
                self.assertFalse(report['can_configure'])
                self.assertIsNone(report['recommended'])
                self.assertIsNone(report['maximum'])
                self.assertTrue(report['reasons'])

    def test_recommendations_grow_with_observed_room_and_custom_limits_leave_headroom(self):
        small = assess_resources(observation(cpus=4, total=24, available=24, docker_cpus=4, docker_memory=18))
        large = assess_resources(observation(cpus=64, total=128, available=100, docker_cpus=64, docker_memory=128))
        self.assertEqual(small['verdict'], 'ready')
        self.assertEqual(small['recommended']['worker_cpus'], 3)
        self.assertEqual(small['recommended']['worker_memory_gib'], 16)
        self.assertGreater(large['recommended']['worker_memory_gib'], small['recommended']['worker_memory_gib'])
        self.assertLessEqual(large['recommended']['worker_memory_gib'], 32)
        self.assertLess(large['limits']['worker_cpus'], 64)
        self.assertLess(large['limits']['worker_memory_gib'] * GIB, 100 * GIB)
        self.assertEqual(large['maximum'], {'worker_cpus': 63, 'job_cpus': 63, 'worker_memory_gib': 96})
        self.assertEqual(small['maximum'], {'worker_cpus': 3, 'job_cpus': 3, 'worker_memory_gib': 16})
        self.assertNotIn('performance', json.dumps(large))

    def test_missing_or_remote_docker_gives_a_provisional_host_verdict(self):
        for state in ['unavailable', 'remote']:
            report = assess_resources(observation(docker_state=state))
            self.assertEqual(report['verdict'], 'needs_docker')
            self.assertTrue(report['can_configure'])
            self.assertEqual(report['host']['available_memory_bytes'], 32 * GIB)

    def test_affinity_and_parent_cgroup_limits_beat_host_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); proc = root / 'proc'; group = root / 'cgroup'
            (proc / 'self').mkdir(parents=True); (group / 'slice/job').mkdir(parents=True)
            (proc / 'meminfo').write_text('MemTotal: 134217728 kB\nMemAvailable: 104857600 kB\n')
            (proc / 'self/cgroup').write_text('0::/slice/job\n')
            (group / 'cpu.max').write_text('max 100000')
            (group / 'slice/cpu.max').write_text('400000 100000')
            (group / 'slice/job/cpu.max').write_text('800000 100000')
            (group / 'slice/memory.max').write_text(str(24 * GIB))
            (group / 'slice/memory.current').write_text(str(3 * GIB))
            with mock.patch.object(probe.os, 'cpu_count', return_value=32), \
                    mock.patch.object(probe.os, 'sched_getaffinity', return_value=set(range(8))), \
                    mock.patch.object(probe.platform, 'system', return_value='Linux'):
                host = probe.host_resources(proc_root=proc, cgroup_root=group)
            self.assertEqual(host['logical_cpus'], 32)
            self.assertEqual(host['effective_cpus'], 4)
            self.assertEqual(host['effective_memory_bytes'], 24 * GIB)
            self.assertEqual(host['available_memory_bytes'], 21 * GIB)

    def test_v1_quota_and_memory_usage_and_sub_cpu_quota_do_not_round_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); proc = root / 'proc'; group = root / 'cgroup'
            proc.mkdir(); (group / 'cpu').mkdir(parents=True); (group / 'memory').mkdir()
            (proc / 'meminfo').write_text('MemTotal: 67108864 kB\nMemAvailable: 62914560 kB\n')
            (group / 'cpu/cpu.cfs_quota_us').write_text('50000')
            (group / 'cpu/cpu.cfs_period_us').write_text('100000')
            (group / 'memory/memory.limit_in_bytes').write_text(str(32 * GIB))
            (group / 'memory/memory.usage_in_bytes').write_text(str(20 * GIB))
            with mock.patch.object(probe.platform, 'system', return_value='Linux'):
                host = probe.host_resources(proc_root=proc, cgroup_root=group)
            self.assertEqual(host['effective_cpus'], 0)
            self.assertEqual(host['available_memory_bytes'], 12 * GIB)

    def test_remote_docker_is_never_contacted_and_context_overrides_host(self):
        for env in [{'DOCKER_HOST': 'ssh://private-fixture.invalid'},
                    {'DOCKER_CONTEXT': 'remote-fixture', 'DOCKER_HOST': 'unix:///unused'}]:
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(probe, '_run', return_value='"ssh://private-fixture.invalid"') as run:
                report = probe.docker_resources()
                self.assertEqual(report['state'], 'remote')
                self.assertNotIn('private-fixture', json.dumps(report))
                self.assertLessEqual(run.call_count, 1)
                self.assertFalse(any('info' in call.args[0] for call in run.call_args_list))

    def test_docker_json_is_bounded_to_capacity_and_malformed_values_are_unknown(self):
        for info, state in [({'NCPU': 8, 'MemTotal': 32 * GIB, 'HttpProxy': 'private-fixture'}, 'available'),
                            ({'NCPU': -1, 'MemTotal': None}, 'unavailable')]:
            with mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(probe, '_run', side_effect=['"unix:///fixture.sock"', json.dumps(info)]):
                report = probe.docker_resources()
                self.assertEqual(report['state'], state)
                self.assertNotIn('private-fixture', json.dumps(report))

    def test_macos_memory_probe_and_unknown_availability_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vm = 'Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free: 1000.\nPages inactive: 2000.\nPages speculative: 3000.\n'
            with mock.patch.object(probe.platform, 'system', return_value='Darwin'), \
                    mock.patch.object(probe.os, 'sysconf', side_effect=ValueError), \
                    mock.patch.object(probe, '_run', side_effect=[str(32 * GIB), vm]):
                host = probe.host_resources(proc_root=root / 'proc', cgroup_root=root / 'groups')
            self.assertEqual(host['total_memory_bytes'], 32 * GIB)
            self.assertEqual(host['available_memory_bytes'], 6000 * 16384)
            self.assertIn('estimate', host['availability_source'])
            with mock.patch.object(probe.platform, 'system', return_value='Linux'), \
                    mock.patch.object(probe.os, 'sysconf', side_effect=ValueError):
                host = probe.host_resources(proc_root=root / 'proc', cgroup_root=root / 'groups')
            self.assertIsNone(host['available_memory_bytes'])
            self.assertIsNone(host['effective_memory_bytes'])


if __name__ == '__main__': unittest.main()
