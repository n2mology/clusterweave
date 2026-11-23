#!/usr/bin/env python3
"""Run only the prepared, pinned supplied-CDS plantiSMASH SIF profile."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from plantismash_native import PUBLIC_PRODUCER, SUPPORTED_PRODUCERS, PRODUCER, PROFILE, PROFILE_SHA256, SIF_SHA256, ACCEPTED_SIF_SHA256, original_inventory, read_native

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def check_profile():
    path = ROOT / 'config/plantismash-profile.json'
    if digest(path) != PROFILE_SHA256:
        raise ValueError('Prepared plantiSMASH profile identity differs; modified settings require a distinct validated profile')
    return json.loads(path.read_text())


def runtime_identity(sif, engine):
    check_profile()
    sif_digest = digest(sif) if sif.is_file() else None
    if sif_digest not in ACCEPTED_SIF_SHA256:
        raise ValueError('Prepared plantiSMASH SIF is missing or has a different identity. Configure the accepted supplied-CDS runtime; jobs never acquire it.')
    resolved = shutil.which(engine)
    if not resolved:
        raise ValueError('Prepared plantiSMASH needs a configured Apptainer or Singularity executable')
    version = subprocess.run([resolved, '--version'], capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    executable_sha256 = digest(resolved)
    if (engine == 'apptainer' or version.startswith('apptainer version')) and (version != 'apptainer version 1.5.5' or executable_sha256 != '69c11aff0651fbd446d3df9325d455b9bb1b5960b8333f21a9a4becdf9063836'):
        raise ValueError('Prepared Apptainer identity differs from the supported 1.5.5 amd64 package')
    return {'executable': resolved, 'executable_sha256': executable_sha256,
            'version': version, 'sif_sha256': sif_digest}


def isolated_command(engine, sif):
    return [engine, 'exec', '--userns', '--cleanenv', '--containall',
            '--no-home', '--net', '--network', 'none', '--disable-cache']


def check_runtime(sif, engine):
    """Execute the prepared SIF under the same isolation required by jobs."""
    import signal
    import tempfile
    identity = runtime_identity(sif, engine)
    with tempfile.TemporaryDirectory(prefix='plantismash-check-') as scratch:
        env = dict(os.environ, APPTAINER_TMPDIR=scratch, SINGULARITY_TMPDIR=scratch)
        probe = (ROOT / 'bin/plantismash_prereqs.py').read_text()
        command = [*isolated_command(identity['executable'], sif), str(sif.resolve()),
                   '/opt/plantismash/repeat2/bin/python', '-c', probe, json.dumps(check_profile()['arguments'])]
        process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True)
        # The probe has its own process group for timeout cleanup. Forward
        # cancellation of the checker to that group before the checker exits.
        import threading
        previous_handlers = {}
        def cancelled(signum, frame):
            raise SystemExit(128 + signum)
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGTERM, signal.SIGINT):
                previous_handlers[signum] = signal.signal(signum, cancelled)
        try:
            stdout, stderr = process.communicate(timeout=30)
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
        if process.returncode:
            detail = stderr.strip()[-2000:]
            raise ValueError('Prepared plantiSMASH failed isolated execution or requested-feature prerequisite checks: ' + detail)
    return identity['executable']


def collect(results):
    rows = []
    for path in sorted((results / 'plantismash').glob('*/outcome.json')):
        row = json.loads(path.read_text())
        rows.append(row)
    save(results / 'summary_tables/native_detection.json', {'schema': 'native-detection-v1', 'genomes': rows})


def archive_attempt(args):
    import time
    root = args.results.resolve() / 'plantismash' / args.genome
    if root.exists():
        previous = args.results.resolve() / 'plantismash_attempts' / args.genome / str(time.time_ns())
        previous.parent.mkdir(parents=True, exist_ok=True)
        root.rename(previous)
        staged = args.results.resolve() / 'native_bgc' / args.genome
        if staged.exists():
            staged.rename(previous / 'comparison-inputs')


def mark_failed(args, state='FAILED_OR_PARTIAL', error=None):
    archive_attempt(args)
    root = args.results.resolve() / 'plantismash' / args.genome
    save(root / 'outcome.json', {'genome_id':args.genome,'producer':PUBLIC_PRODUCER,'profile_id':PROFILE,'state':state,'calls':None, **({'annotation_error': error} if error else {})})


def retained_profile_matches(root, sif):
    """A detector profile change must execute again, independently of retrieval reuse."""
    try:
        receipt = json.loads((root / 'execution.json').read_text())
        return (receipt.get('producer') in SUPPORTED_PRODUCERS and receipt.get('profile_id') == PROFILE
                and receipt.get('profile_sha256') == PROFILE_SHA256
                and receipt.get('sif_sha256') in ACCEPTED_SIF_SHA256
                and receipt.get('sif_sha256') == digest(sif))
    except (OSError, ValueError, TypeError):
        return False


def run(args):
    results = args.results.resolve()
    root = results / 'plantismash' / args.genome
    source = args.input.resolve()
    profile = check_profile()
    try:
        original = original_inventory(source, args.genome, args.fasta)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        receipt = getattr(exc, 'receipt', {'state': 'ANNOTATION_INCOMPATIBLE', 'reason': str(exc)})
        mark_failed(args, receipt['state'], dict(receipt, detail=str(exc)))
        raise
    if root.exists():
        old = root / 'original-identity.json'
        if not args.force and old.is_file() and retained_profile_matches(root, args.sif) and json.loads(old.read_text()).get('source_file_sha256') == original['source_file_sha256']:
            print('PLANT_PHASE phase=validating', flush=True)
            result = read_native(original, root / 'native')
            if result['valid']:
                return publish(args, original, result, root, retained=True)
        # Keep incomplete and previous attempts rather than turning them into new success.
        archive_attempt(args)
    root.mkdir(parents=True)
    save(root / 'original-identity.json', original)
    row = {'genome_id': args.genome, 'producer': PUBLIC_PRODUCER, 'profile_id': PROFILE, 'state': 'FAILED_OR_PARTIAL', 'calls': None}
    save(root / 'outcome.json', row)
    engine_identity = runtime_identity(args.sif, args.engine)
    check = {'engine': engine_identity, 'profile_id':PROFILE,'profile_sha256':PROFILE_SHA256,'probe':'immutable extras prerequisites and native --check-prereqs', 'state': 'checking'}
    save(root / 'runtime-check.json', check)
    try:
        engine = check_runtime(args.sif, args.engine)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        check.update(state='failed', error=str(error))
        save(root / 'runtime-check.json', check)
        raise
    check['state'] = 'passed'
    save(root / 'runtime-check.json', check)
    if profile['producer'] != PRODUCER or profile['profile_id'] != PROFILE:
        raise ValueError('Plant producer/profile identity mismatch')
    shutil.copyfile(source, root / 'original.gbk')
    def command_factory(work, source, inventory):
        (work / 'tmp').mkdir()
        (work / 'home').mkdir()
        cmd = [*isolated_command(engine, args.sif), '--bind', f'{work}:/work:rw', '--bind', f'{source}:/input.gbk:ro', str(args.sif.resolve()), '/usr/local/bin/plantismash', *profile['arguments'], '--cpus', str(args.cpus), '--outputfolder', '/work/native', '--logfile', '/work/native.log', '/input.gbk']
        env = dict(os.environ, APPTAINER_TMPDIR=str(work / 'tmp'), SINGULARITY_TMPDIR=str(work / 'tmp'))
        for prefix in ('APPTAINERENV_', 'SINGULARITYENV_'):
            for key, value in {'TMPDIR':'/work/tmp','MPLCONFIGDIR':'/work/tmp/matplotlib','XDG_CACHE_HOME':'/work/tmp/cache','PYTHONHASHSEED':'1','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','PYTHONDONTWRITEBYTECODE':'1'}.items():
                env[prefix + key] = value
        save(work / 'execution.json', {'producer':PUBLIC_PRODUCER,'profile_id':PROFILE,'sif_sha256':engine_identity['sif_sha256'],'source_sha256':inventory['source_file_sha256'],'profile_sha256':digest(ROOT / 'config/plantismash-profile.json'),'engine':engine_identity,'argv':cmd})
        return cmd, env
    if args.record_parallelism > 1:
        from plantismash_shards import execute
        save(root / 'execution.json', {'producer':PUBLIC_PRODUCER,'profile_id':PROFILE,'sif_sha256':engine_identity['sif_sha256'],'source_sha256':original['source_file_sha256'],'engine':engine_identity,'profile_sha256':PROFILE_SHA256,'execution_kind':'whole_record_shards','record_parallelism':args.record_parallelism,'cpus_per_shard':args.cpus})
        execute(args, original, root, command_factory)
    else:
        cmd, env = command_factory(root, source, original)
        code = subprocess.call(cmd, env=env)
        save(root / 'native-exit.json', {'exit_code':code,'producer':PRODUCER})
        if code:
            raise ValueError(f'plantiSMASH exited with status {code}; no accepted count')
    print('PLANT_PHASE phase=validating', flush=True)
    result = read_native(original, root / 'native')
    if not result['valid']:
        save(root / 'validation.json', result)
        raise ValueError('plantiSMASH output validation failed: ' + '; '.join(result['reasons']))
    return publish(args, original, result, root, retained=False)


def publish(args, original, result, root, retained):
    save(root / 'validation.json', result)
    receipt = root / 'native/native-completion.json'
    execution = root / 'execution.json'
    recorded_sif = json.loads(execution.read_text()).get('sif_sha256') if execution.is_file() else None
    row = {'genome_id':args.genome,'producer':PUBLIC_PRODUCER,'profile_id':PROFILE,'state':result['outcome'],'calls':len(result['calls']),'completion_path':receipt.relative_to(args.results.resolve()).as_posix(),'completion_sha256':digest(receipt),'source_sha256':original['source_file_sha256'],'sif_sha256':recorded_sif,'reuse':'retained' if retained else 'executed','shared_cache':'disabled_distinct_plant_producer','grouping_state':'pending' if result['calls'] else 'detector_zero'}
    row['not_evaluated_record_count'] = len(result['identity'].get('not_evaluated_records', []))
    row['not_evaluated_records'] = result['identity'].get('not_evaluated_records', [])
    save(root / 'outcome.json', row)
    native_root = args.results / 'native_bgc' / args.genome
    native_root.mkdir(parents=True, exist_ok=True)
    for call in result['calls']:
        source = root / 'native' / call['native_cluster_gbk']
        shutil.copyfile(source, native_root / source.name)
    from plantismash_assembly import publish_report
    print('PLANT_PHASE phase=exporting', flush=True)
    if not (root / 'provenance.json').is_file():
        publish_report(root)
    print(json.dumps(row))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check','admit','run','collect','mark-failed'])
    parser.add_argument('--input', type=Path)
    parser.add_argument('--fasta', type=Path)
    parser.add_argument('--genome', default='genome')
    parser.add_argument('--results', type=Path)
    parser.add_argument('--sif', type=Path, default=os.environ.get('PLANTISMASH_SIF') or str(Path(os.environ.get('CLUSTERWEAVE_SOFTWARE_ROOT', '/data/software')) / 'plantismash/plant.sif'))
    parser.add_argument('--engine', choices=['apptainer','singularity','/usr/bin/apptainer','/usr/bin/singularity'], default=os.environ.get('PLANTISMASH_ENGINE','apptainer'))
    parser.add_argument('--cpus', type=int, default=1)
    parser.add_argument('--record-parallelism', type=int, default=1)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--failure-receipt', type=Path)
    args = parser.parse_args()
    if args.cpus < 1 or args.record_parallelism < 1 or not __import__('re').fullmatch(r'[A-Za-z0-9_.-]{1,120}',args.genome):
        parser.error('Invalid CPU allocation or genome identity')
    if args.action == 'check':
        check_runtime(args.sif,args.engine)
    elif args.action == 'admit':
        try:
            print(json.dumps(original_inventory(args.input,args.genome,args.fasta)))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            receipt = getattr(exc, 'receipt', {'state': 'ANNOTATION_INCOMPATIBLE', 'reason': str(exc)})
            print(json.dumps(dict(receipt, admitted=False, detail=str(exc))))
            raise
    elif args.action == 'mark-failed':
        receipt = json.loads(args.failure_receipt.read_text()) if args.failure_receipt else None
        state = receipt['state'] if receipt else 'ANNOTATION_REQUIRED'
        if state not in {'ANNOTATION_REQUIRED', 'ANNOTATION_INCOMPATIBLE'}:
            raise ValueError('Invalid annotation failure state')
        mark_failed(args, state, receipt)
    elif args.action == 'collect':
        collect(args.results)
    else:
        return run(args)
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        print(str(exc),file=sys.stderr)
        sys.exit(2)
