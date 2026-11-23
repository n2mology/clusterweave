"""Publish an accepted cohort decision through normal worker admission."""
from pathlib import Path
import json

import cohort_gate



def resume_job(job_id, payload):
    import job_store as store
    if not isinstance(payload, dict) or set(payload) != {'decision_id', 'included', 'excluded'}:
        raise cohort_gate.GateError('Provide the exact decision ID and included/excluded genome IDs')
    with store.queue_admission_lock():
        job = store.read_job(job_id)
        if not job or store.job_delete_path(job_id).exists() or store.job_cancel_path(job_id).exists():
            raise cohort_gate.GateError('Job is unavailable for continuation')
        control = store.job_dir(job_id) / 'cohort/current.json'
        gate = cohort_gate.load_gate(control)
        identity = gate['identity']
        if identity.get('job_id') != job_id or identity.get('rerun_count') != int(job.get('rerun_count') or 0):
            raise cohort_gate.GateError('Decision belongs to a different attempt')
        if (payload['decision_id'] != gate['decision_id'] or payload['included'] != gate['included']
                or payload['excluded'] != gate['excluded']):
            raise cohort_gate.GateError('Stale decision or cohort mismatch')
        if job.get('continuation_id') == gate['decision_id']:
            return {'job_id': job_id, 'status': job['status'], 'duplicate': True}
        if job.get('status') != 'awaiting_decision':
            raise cohort_gate.GateError('Job is not waiting for a cohort decision')
        cohort_gate.accept(control, **payload, attempt_identity=identity)
        # Persist intent before publishing the queue entry. Startup recovery uses
        # the same path if either publication is interrupted.
        job['continuation_id'] = gate['decision_id']
        job['cohort_decision'] = cohort_gate.public_gate(gate)
        job['status'] = 'pending'
        job['stage'] = 'queued'
        job['error'] = None
        job['updated_at'] = store.now_iso()
        job.pop('worker_reservation', None)
        store.write_job(job)
        settings = dict(job.get('settings') or {})
        store.atomic_write_text(store.QUEUE_DIR / (job_id + '.json'), json.dumps({
            'job_id': job_id, 'cpus': job['cpus'], 'settings': settings,
            'enqueued_at': store.now_iso()}))
        store.append_log(job_id, 'Explicit cohort exclusions accepted; downstream continuation queued. Failed attempts are retained.')
        return {'job_id': job_id, 'status': 'pending', 'duplicate': False}


def recover_accepted_decision(job):
    import job_store as store
    if job.get('status') != 'awaiting_decision':
        return False
    try:
        gate = cohort_gate.load_gate(store.job_dir(job['id']) / 'cohort/current.json')
        acceptance = gate.get('acceptance')
        if acceptance:
            resume_job(job['id'], acceptance)
            return True
    except (OSError, ValueError, KeyError):
        # Changed evidence remains waiting for operator review, never re-executed.
        return False
    return False
