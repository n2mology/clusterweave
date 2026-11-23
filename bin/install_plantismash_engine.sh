#!/usr/bin/env bash
# Image-build preparation only. Jobs consume this engine without acquisition.
set -euo pipefail
version=1.5.5
sha256=25095d3711504b3e8657dbb2e172ef8db9db43c4503d940c9c36b105db8dce77
[[ "$(dpkg --print-architecture)" == amd64 ]] || { echo "The pinned plant engine package supports amd64" >&2; exit 2; }
package="$(mktemp --suffix=.deb)"
trap 'rm -f "$package"' EXIT
curl --fail --location --retry 3 "https://github.com/apptainer/apptainer/releases/download/v${version}/apptainer_${version}_amd64.deb" -o "$package"
echo "$sha256  $package" | sha256sum --check -
apt-get update
apt-get install -y --no-install-recommends "$package"
apptainer --version
# The non-setuid engine requires user namespaces permitted by the worker host.
test ! -e /usr/libexec/apptainer/bin/starter-suid
