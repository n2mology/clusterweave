# ClusterWeave v1.0.1 release checklist

Use this checklist when preparing and verifying a source release. Commit, tag,
push, and GitHub Release actions follow only after the applicable checks pass
and the release owner has reviewed the resulting source tree.

## Source and metadata

- [ ] `CITATION.cff`, `CHANGELOG.md`, `SECURITY.md`, BSD-3-Clause license,
      DOI, version, and preparation date are correct.
- [ ] README local commands work from a fresh clone at
      `http://127.0.0.1:8080`.
- [ ] `profiles/release_v1.0.0.env` is the only release profile.
- [ ] Fungi, bacteria, Both routing and applicability are documented.

## Public examples

- [ ] `examples/fungi_only` retains the 50-genome fungal bundle.
- [ ] `examples/mixed` contains the verified 20-bacteria/20-fungi input,
      both taxon maps, four canonical SVGs, and refreshed safe summaries.
- [ ] No example contains a job ID, token, private URL, raw genome, raw tool
      tree, log, database, cache, or absolute path.

## Validation

```bash
git diff --check
python3 -B bin/check_public_release.py
python3 -B -c 'from pathlib import Path; [compile(p.read_text(encoding="utf-8"), str(p), "exec") for root in ("bin", "tests", "web") for p in Path(root).glob("*.py")]'
while IFS= read -r -d '' file; do bash -n "$file"; done < <(find . -maxdepth 4 -type f -name '*.sh' -not -path './.git/*' -print0)
python3 -B -m unittest discover -s tests -p 'test_*.py'
for file in web/static/assets/clusterweave.js tests/browser/*.js; do node --check "$file"; done
npm run test:browser
docker compose config --quiet
docker compose -f clusterweave.yml config --quiet
```

- [ ] Shell, Python, JavaScript, compose, documentation-link, and public-safety
      checks pass.
- [ ] Web and worker build from a clean exported tree.
- [ ] Fresh-clone localhost smoke passes.
- [ ] Public/read-token/admin access tests pass; raw SQLite stays private and
      the sanitized viewer copy opens automatically.
- [ ] Fungal antiSMASH, bacterial antiSMASH, and FunBGCeX nested HTML navigation
      work in the opaque authenticated preview.
- [ ] 50 accessions are accepted and 51 are rejected.

Run the focused public/read-token/admin and result-package boundary suites:

```bash
python3 -B -m unittest discover -s tests -p 'test_web_api_auth.py'
python3 -B -m unittest discover -s tests -p 'test_opaque_public_results.py'
python3 -B -m unittest discover -s tests -p 'test_public_result_manifest.py'
python3 -B -m unittest discover -s tests -p 'test_bigscape_public_db.py'
python3 -B -m unittest discover -s tests -p 'test_result_attestation.py'
```

- [ ] Linux and WSL2 smokes pass.
- [ ] Physical Intel and Apple Silicon Docker Desktop smokes pass.

## Archive gate

Build the prospective source manifest from existing files reported by
`git ls-files -co --exclude-standard -z`; do not tar the raw worktree. Before
installing dependencies, run `bin/check_public_release.py` in both the working
tree and an extracted archive. Create the archive twice with the same prefix,
owner/group, modes, and modification time, then compare SHA-256 values. Verify
every member is a regular file under the release prefix and that the manifest
contains neither ignored runtime material nor deleted tracked paths.

Scan the extracted archive for credentials, private paths/IPs, production job
identifiers, oversized binaries, caches, databases, uploads, logs, raw genomes,
`clusterweave_ops`, and `local_only`. Then run the browser fixtures and
web/worker build from that extracted tree. A prospective export is not evidence
for the tagged-fresh-clone gate; that requires the real published tag on a
separate clean host.

Never run `docker compose down -v` during release validation.
