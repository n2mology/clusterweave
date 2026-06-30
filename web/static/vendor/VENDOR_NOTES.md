# ClusterWeave Static Vendor Notes

Vendored browser files are public, same-origin runtime dependencies for the zero-build static SPA.
Do not add CDNs, runtime package fetches, import maps, generated bundles, source maps, examples,
fonts, WebGPU builds, local reference media, or unused plugin files.

## Three.js 0.184.0

- Package: `three@0.184.0`
- Source package: npm registry tarball `three-0.184.0.tgz`
- Homepage: https://threejs.org/
- Repository: https://github.com/mrdoob/three.js
- License: MIT, copied to `web/static/vendor/three-0.184.0/LICENSE`
- npm shasum: `5bca0a3851eea5345e4c205567b40dfa49b791b5`
- npm integrity: `sha512-wtTRjG92pM5eUg/KuUnHsqSAlPM296brTOcLgMRqEeylYTh/CdtvKUvCyyCQTzFuStieWxvZb8mVTMvdPyUpxg==`
- Local browser files:
  - `web/static/vendor/three-0.184.0/three.module.min.js`
  - `web/static/vendor/three-0.184.0/three.core.min.js`
- Package files copied:
  - `build/three.module.min.js`
  - `build/three.core.min.js` because `three.module.min.js` imports this same-package core module
- Date checked: 2026-06-12
- Usage: optional Three.js WeaveMap depth layer only; the DOM/SVG WeaveMap remains the accessible
  source of truth and fallback.

## GSAP 3.15.0

- Package: `gsap@3.15.0`
- Source package: npm registry tarball `gsap-3.15.0.tgz`
- Source URL: https://registry.npmjs.org/gsap/-/gsap-3.15.0.tgz
- Homepage: https://gsap.com
- Repository: https://github.com/greensock/GSAP
- License: Standard "No Charge" GSAP License, documented in
  `web/static/vendor/gsap-3.15.0/STANDARD-LICENSE.md`
- npm shasum: `7851baaffc77642f2db3b1749d3634f9b5a19d14`
- npm integrity: `sha512-dMW4CWBTUK1AEEDeZc1g4xpPGIrSf9fJF960qbTZmN/QwZIWY5wgliS6JWl9/25fpTGJrMRtSjGtOmPnfjZB+A==`
- Local browser files:
  - `web/static/vendor/gsap-3.15.0/gsap.min.js`
  - `web/static/vendor/gsap-3.15.0/STANDARD-LICENSE.md`
- Package files copied:
  - `dist/gsap.min.js`
- Package metadata checked from `package.json`; official standard license page checked for dates.
- Date checked: 2026-06-12
- Usage: optional DOM transition polish only. No GSAP plugins, source maps, examples, package tree,
  or runtime package resolution are part of the browser load path.
