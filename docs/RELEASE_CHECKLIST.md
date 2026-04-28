# GitHub Release Checklist

This checklist is meant for the first public `ClusterWeave` release and for future tagged releases.

## 1. Pre-Push Review

- confirm there are no plaintext secrets, private tokens, or institution-specific private paths in tracked files
- confirm `Data/Results/`, project genomes, large containers, and local caches are still ignored by `.gitignore`
- review `CITATION.cff` and fill in real authors, repository URL, and version metadata
- review `LICENSE`, `THIRD_PARTY.md`, and `DATA_SOURCES.md` for final redistribution language
- confirm the public docs still match the current workflow entrypoints and defaults
- for manuscript-linked runs, keep `Data/Results/<project-name>/reproducibility/external_artifacts.tsv` with the output bundle and compare it against any rerun artifacts
- update `profiles/release_v0.1.0.env` or add a new release profile when tool/resource versions change intentionally

## 2. Validate The Repo

Run these checks before the first public push:

```bash
python -m unittest discover -s tests -p "test_*.py"
bash -n run_clusterweave.sh
bash -n run_annotation_and_detection.sh
bash -n run_bigscape.sh
bash -n summarize_clusterweave.sh
bash -n run_clinker.sh
```

Recommended extra checks:

- verify that a dry run or small example run does not rewrite tracked helper files
- confirm `BEGINNER_SETUP.md` is accurate enough for a first-time user
- confirm `README.md` still reflects the intended public scope of the project
- confirm `external_artifacts.tsv` is written for the release/example run, or document why artifact capture was disabled

## 3. Prepare The Initial Commit

- make sure the branch is `main`
- stage only repo files intended for public release
- create the first commit with a clear message

Suggested command sequence:

```bash
git branch -M main
git add .
git status --short
git commit -m "Initial public scaffold for ClusterWeave"
```

Before committing, check that staged files do not include:

- local result folders under `Data/Results/<project-name>/`
- downloaded genome folders under `Data/Genomes/Fungi/<project-name>/`
- local `.sif` images or downloaded third-party resources under `Software/`

## 4. Create The GitHub Repository

- create an empty GitHub repository named `clusterweave`
- add the GitHub remote
- push `main`

Typical commands:

```bash
git remote add origin https://github.com/n2mology/clusterweave.git
git push -u origin main
```

If the remote repository already exists, verify the default branch and visibility settings before pushing.

## 5. Prepare The First GitHub Release

- choose a first version tag such as `v0.1.0`
- update `CITATION.cff` version fields if needed
- create an annotated tag
- push the tag
- draft a GitHub Release with short installation and scope notes

Typical commands:

```bash
git tag -a v0.1.0 -m "ClusterWeave v0.1.0"
git push origin v0.1.0
```

Suggested GitHub Release notes should include:

- what `ClusterWeave` does
- intended platform support: Linux / WSL
- the main entrypoints: `prepare_genomes_from_accessions.sh` and `run_clusterweave.sh`
- the fact that `PROJECT_NAME` separates multiple studies in one clone
- any known limitations for the first release

## 6. Nice-To-Have Release Extras

- upload a small public example dataset or example-output bundle
- archive the GitHub release with Zenodo if you want a DOI-backed software citation
- add one workflow figure and one representative output figure to the repository or release assets
- document the exact software versions used in the manuscript
- include or archive the release run's artifact checksum table

## 7. Manuscript-Facing Follow-Up

- finalize authorship and acknowledgements
- finalize the manuscript title, abstract, and availability statement
- add Application Note figures, methods text, and benchmark tables
- decide whether to include a public example dataset, a public example-output bundle, or both
