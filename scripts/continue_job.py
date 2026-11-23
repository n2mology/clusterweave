#!/usr/bin/env python3
"""Accept an exact hosted-job cohort decision and queue downstream continuation."""
import argparse
import getpass
import json
import os
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', required=True, help='ClusterWeave server base URL')
    parser.add_argument('--run', required=True, help='Public run ID')
    parser.add_argument('--decision', required=True, help='Current decision_id from authenticated job details')
    parser.add_argument('--include', action='append', required=True, help='Exact included genome ID; repeat for each genome')
    parser.add_argument('--exclude', action='append', required=True, help='Exact excluded genome ID; repeat for each genome')
    args = parser.parse_args()
    url = urlsplit(args.server)
    if url.scheme not in {'http', 'https'} or not url.netloc or url.username or url.password or url.query or url.fragment:
        parser.error('Use a server base URL without credentials, query or fragment')
    token = os.environ.get('CLUSTERWEAVE_JOB_ACCESS_CODE') or getpass.getpass('Result access code: ')
    request = Request(args.server.rstrip('/') + '/api/results/' + quote(args.run, safe='') + '/continue',
                      data=json.dumps({'decision_id': args.decision, 'included': sorted(args.include), 'excluded': sorted(args.exclude)}).encode(),
                      headers={'Content-Type': 'application/json', 'X-ClusterWeave-Read-Token': token}, method='POST')
    try:
        with urlopen(request, timeout=300) as response:
            value = json.load(response)
    except HTTPError as exc:
        print('Continuation refused (HTTP ' + str(exc.code) + '). Reload the authenticated decision; no replacement job was submitted.')
        return 1
    print(json.dumps({k: value.get(k) for k in ('job_id', 'status', 'duplicate')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
