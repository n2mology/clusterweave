"""The SIF dispatcher must give Prodigal writable per-invocation scratch."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AntiSmashScratchRuntimeTests(unittest.TestCase):
    def test_sif_invocations_have_distinct_writable_cwd_and_preserve_exit(self):
        source = (ROOT / 'run_annotation_and_detection.sh').read_text()
        function = source.split('antismash_exec() {', 1)[1].split('\n}\n', 1)[0]
        with tempfile.TemporaryDirectory(prefix='anti scratch ') as directory:
            root = Path(directory)
            engine = root / 'engine'
            engine.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
cwd = pathlib.Path(args[args.index('--pwd') + 1])
(cwd / 'tmp.prodigal.stdin.test').write_text('training input')
with open(os.environ['CALLS'], 'a') as f: f.write(json.dumps(args) + '\\n')
sys.exit(int(os.environ['NATIVE_EXIT']))
''')
            engine.chmod(0o700)
            shell = 'antismash_exec() {' + function + '\n}\n'
            shell += 'BIND_ARGS=(--bind "$WORK_ROOT:$WORK_ROOT"); antismash_exec antismash /input.gbk\n'
            env = {**os.environ, 'ENGINE': str(engine), 'WORK_ROOT': str(root / 'job work'),
                   'ANTISMASH_SIF': '/software/anti.sif', 'CALLS': str(root / 'calls')}
            for code in [0, 17]:
                result = subprocess.run(['bash', '-c', shell], env={**env, 'NATIVE_EXIT': str(code)})
                self.assertEqual(result.returncode, code)
            calls = [json.loads(line) for line in (root / 'calls').read_text().splitlines()]
            directories = [Path(args[args.index('--pwd') + 1]) for args in calls]
            self.assertNotEqual(*directories)
            for cwd, args in zip(directories, calls):
                self.assertTrue(cwd.is_relative_to(root / 'job work' / 'tmp'))
                self.assertEqual(cwd.stat().st_mode & 0o777, 0o700)
                self.assertEqual((cwd / 'tmp.prodigal.stdin.test').read_text(), 'training input')
                self.assertEqual(args[-2:], ['antismash', '/input.gbk'])
                self.assertEqual(args[args.index('/software/anti.sif') + 1:-2],
                                 ['env', f'TMPDIR={cwd}', f'TMP={cwd}', f'TEMP={cwd}',
                                  f'MPLCONFIGDIR={cwd}/matplotlib', f'XDG_CACHE_HOME={cwd}/cache'])


if __name__ == '__main__':
    unittest.main()
