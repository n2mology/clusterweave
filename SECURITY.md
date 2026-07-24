# Security policy

## Supported version

ClusterWeave v1.0.1 is the current supported release. Security fixes target the
current v1.x release line, and the affected version, Git revision, or tag should
accompany every report.

Project-hosted access is **coming soon**. Until it launches, use the trusted
loopback-only local profile or a separately administered institutional
deployment.

## Report a vulnerability

Do not open a public issue containing a credential, private result link, genome,
internal job identifier, operator path, or exploit detail. Use GitHub's private
security-advisory workflow for this repository. Include the affected revision,
reproduction steps, impact, and the minimum evidence needed to verify the
report.

Remove unrelated sensitive data before attaching evidence. A bounded, synthetic
reproduction is preferable to a raw job directory or complete service log.

## Deployment boundary

The default `docker-compose.yml` profile mounts the host Docker socket. It is a
trusted single-user local-analysis profile and must remain bound to
`127.0.0.1`. Do not expose it directly to an untrusted network. Operators of a
public or institutional service must provide a socket-free external executor and
their own access control, HTTPS termination, network policy, monitoring, backup,
retention, and incident-response controls.

`clusterweave.yml` removes the Docker socket but is not a complete secure service
by itself; required stages remain unavailable until a configured external
executor and prepared runtimes pass preflight.

Treat job result links, read tokens, administrator and submit tokens, `.env`,
SMTP credentials, original genome uploads, raw tool databases, backups, and
logs as private. The authenticated full result package also contains staged
genome GenBank files and BGC GenBank files. Therefore, anyone who has a result
link can read the sequence-bearing evidence in that package; protect the link
when the submitted genomes are sensitive. Never publish operations directories
or runtime volumes. Do not run `docker compose down -v` during routine
operation or an upgrade, because it deletes named data volumes.
