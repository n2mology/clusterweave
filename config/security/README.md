# Confined SIF worker policy

These profiles adapt the Moby default AppArmor and seccomp policies. Exact
upstream source hashes are in `upstream-provenance.json`; retain `MOBY-LICENSE`.
They apply only to explicitly selected worker containers, not globally.

The worker runs as UID/GID 65534, drops every capability, enables
no-new-privileges, uses a read-only root, and receives only `/dev/fuse` with read
and write device access. Seccomp retains its default-deny policy and adds the
namespace/mount syscalls needed by non-setuid Apptainer. Kernel capability
checks still apply. AppArmor permits mount propagation at `/` and runtime
mounts/pivot only under `/var/lib/apptainer/mnt/session`.

Docker's default proc masks and read-only submounts prevent creation of the
nested proc filesystem. The one-shot operator adapter replaces those proc
submounts with AppArmor denials for the same sensitive files and writable
kernel controls, including their Apptainer session aliases. Sysfs masks and
other default denials remain. Never substitute `systempaths=unconfined`, an
unconfined security profile, host namespaces or an initial SYS_ADMIN capability.

Load the named profile only after checking that an existing profile with the
same name is not being replaced unintentionally:

```bash
sudo apparmor_parser -r config/security/apptainer-worker.apparmor
```

Record its previous state and the configuration hashes. To reverse a newly
installed profile after its containers are stopped:

```bash
sudo apparmor_parser -R config/security/apptainer-worker.apparmor
```

If the name existed before installation, retain and restore its prior policy
instead. The seccomp profile is supplied per container and needs no global
installation. Removing a stopped candidate does not alter other containers'
security settings. Keep runtime outputs and diagnostic records according to
the instance retention policy.
