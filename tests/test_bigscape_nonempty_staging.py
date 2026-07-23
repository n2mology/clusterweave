import csv
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class BigscapeNonemptyStagingTests(unittest.TestCase):
    def test_unique_count_and_canonical_labels_in_all_taxon_modes(self) -> None:
        cases = {
            "fungi": [("Fungus_alpha", "fungi", "existing_cds", 2)],
            "bacteria": [("bacteria_Bacillus_beta", "bacteria", "prodigal", 3)],
            "both": [
                ("Fungus_alpha", "fungi", "existing_cds", 2),
                ("bacteria_Bacillus_beta", "bacteria", "prodigal", 3),
            ],
        }
        for scope, genomes in cases.items():
            with self.subTest(scope=scope), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                results = root / "results"
                antismash = results / "antismash"
                stage = root / "work" / "stage"
                output = results / "big_scape"
                crosswalk = results / "summary_tables" / "bigscape_region_crosswalk.tsv"
                manifest = results / "summary_tables" / "genome_taxon_manifest.tsv"
                manifest.parent.mkdir(parents=True)
                manifest.write_text(
                    "genome_id\ttaxon_group\tprediction_method\ttaxon_source\n"
                    + "".join(
                        f"{genome}\t{taxon}\t{prediction}\t"
                        f"{'ncbi' if genome.startswith('bacteria_') else 'user_declaration'}\n"
                        for genome, taxon, prediction, _ in genomes
                    ),
                    encoding="utf-8",
                )
                expected_names: set[str] = set()
                for genome, _, _, region_count in genomes:
                    genome_root = antismash / genome
                    genome_root.mkdir(parents=True)
                    for ordinal in range(1, region_count + 1):
                        name = f"contig_{ordinal}.region001.gbk"
                        expected_names.add(f"{genome}__{name}")
                        (genome_root / name).write_text(
                            "LOCUS       fixture 4 bp DNA\n"
                            "SOURCE      stale label\n"
                            "  ORGANISM  stale label\n"
                            "ORIGIN\n        1 acgt\n//\n",
                            encoding="utf-8",
                        )

                runtime_bin = root / "bin"
                runtime_bin.mkdir()
                docker = runtime_bin / "docker"
                docker.write_text(
                    "#!/usr/bin/env bash\n"
                    "set -euo pipefail\n"
                    "if [[ ${1:-} == image && ${2:-} == inspect ]]; then exit 0; fi\n"
                    "if [[ ${1:-} == run ]]; then\n"
                    "  previous=''\n"
                    "  output=''\n"
                    "  for argument in \"$@\"; do\n"
                    "    if [[ $previous == -o ]]; then output=$argument; fi\n"
                    "    previous=$argument\n"
                    "  done\n"
                    "  if [[ -n $output ]]; then\n"
                    "    mkdir -p \"$output/output_files\"\n"
                    "    printf '<html>fixture</html>\\n' > \"$output/output_files/index.html\"\n"
                    "  fi\n"
                    "  exit 0\n"
                    "fi\n"
                    "exit 1\n",
                    encoding="utf-8",
                )
                docker.chmod(0o755)
                pfam = root / "resources" / "Pfam-A.hmm"
                pfam.parent.mkdir(parents=True)
                pfam.write_text("fixture\n", encoding="utf-8")
                fasttree = runtime_bin / "fasttree"
                fasttree.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
                fasttree.chmod(0o755)

                env = os.environ.copy()
                env.update(
                    {
                        "PATH": f"{runtime_bin}:{env.get('PATH', '')}",
                        "PROJECT_DIR": str(REPO_ROOT),
                        "PROJECT_NAME": f"fixture_{scope}",
                        "RESULTS_ROOT": str(results),
                        "ANTISMASH_ROOT": str(antismash),
                        "BIGSCAPE_OUT": str(output),
                        "STAGE_DIR": str(stage),
                        "GENOME_TAXON_MANIFEST": str(manifest),
                        "BIGSCAPE_REGION_CROSSWALK": str(crosswalk),
                        "LOGDIR": str(results / "logs"),
                        "ENGINE": "docker",
                        "FORCE": "1",
                        "THREADS": "1",
                        "PFAM_HMM": str(pfam),
                        "FASTTREE_HOST": str(fasttree),
                        "FASTTREE_SHA256": hashlib.sha256(fasttree.read_bytes()).hexdigest(),
                        "LOCAL_BIN": str(runtime_bin),
                        "MIBIG_CACHE": str(root / "mibig"),
                        "MIBIG_AUTO_DOWNLOAD": "0",
                        "AUTO_DOWNLOAD_PFAM": "0",
                        "AUTO_DOWNLOAD_FASTTREE": "0",
                        "AUTO_PULL_BIGSCAPE_SIF": "0",
                    }
                )
                completed = subprocess.run(
                    ["bash", str(REPO_ROOT / "run_bigscape.sh")],
                    cwd=REPO_ROOT,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                source_count = sum(region_count for _, _, _, region_count in genomes)
                self.assertIn(f"Staged region GBKs: {source_count}", completed.stdout)
                staged = sorted(stage.glob("*.gbk"))
                self.assertEqual(len(staged), source_count)
                self.assertEqual({path.name for path in staged}, expected_names)
                with crosswalk.open(newline="", encoding="utf-8") as handle:
                    rows = list(csv.DictReader(handle, delimiter="\t"))
                self.assertEqual(len(rows), source_count)
                self.assertEqual({row["staged_gbk"] for row in rows}, expected_names)
                self.assertEqual(
                    {row["genome_id"] for row in rows},
                    {item[0] for item in genomes},
                )
                for path in staged:
                    genome = path.name.split("__", 1)[0]
                    display = genome.removeprefix("bacteria_").replace("_", " ")
                    rendered = path.read_text(encoding="utf-8")
                    self.assertIn(f"SOURCE      {display}\n", rendered)
                    self.assertIn(f"  ORGANISM  {display}\n", rendered)


if __name__ == "__main__":
    unittest.main()
