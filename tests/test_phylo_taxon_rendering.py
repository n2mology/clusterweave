import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[1]
RENDERER = REPO_ROOT / "bin" / "render_phylo_taxon_profile.py"


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


class PhyloTaxonRenderingTests(unittest.TestCase):
    def test_figure_wrapper_requires_exact_tree_bundle_contract(self) -> None:
        text = (REPO_ROOT / "run_figures.sh").read_text(encoding="utf-8")
        for filename in [
            "clusterweave_taxon_tree.svg",
            "clusterweave_taxon_tree.nwk",
            "clusterweave_taxon_tree_leaf_profiles.tsv",
            "clusterweave_gcf_network_edges.tsv",
            "clusterweave_taxon_tree.graphml",
            "clusterweave_tree_manifest.json",
            "clusterweave_tree_methods.json",
            "clusterweave_tree_bundle.zip",
        ]:
            self.assertIn(filename, text)
        self.assertIn("TAXON_TREE_REQUIRED", text)
        self.assertIn("PHYLOGENY_MAX_VISIBLE_ARCS", text)

    def render_fixture(self, fungi: int, bacteria: int, *, dense: bool = False, arc_cap: int = 80) -> tuple[Path, tempfile.TemporaryDirectory]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        manifest = root / "genome_taxon_manifest.tsv"
        exact = root / "antismash_product_types_exact.tsv"
        crosswalk = root / "candidate_bgc_gcf_crosswalk.tsv"
        output = root / "figures" / "phylogeny"
        rows = []
        exact_rows = []
        crosswalk_rows = []
        genomes: list[tuple[str, str]] = []
        for taxon, count in (("fungi", fungi), ("bacteria", bacteria)):
            for idx in range(1, count + 1):
                genome = f"{taxon}_{idx:02d}"
                genomes.append((genome, taxon))
                authoritative = idx % 5 != 1
                if taxon == "fungi":
                    lineage = (
                        "Eukaryota|Fungi|Ascomycota|Eurotiomycetes"
                        if idx % 2
                        else "Eukaryota|Fungi|Basidiomycota|Agaricomycetes"
                    )
                    lineage_ids = (
                        "2759|4751|4890|147545"
                        if idx % 2
                        else "2759|4751|5204|155619"
                    )
                else:
                    lineage = (
                        "Bacteria|Pseudomonadota|Gammaproteobacteria"
                        if idx % 2
                        else "Bacteria|Bacillota|Bacilli"
                    )
                    lineage_ids = (
                        "2|1224|1236" if idx % 2 else "2|1239|91061"
                    )
                rows.append(
                    {
                        "genome_id": genome,
                        "taxon_group": taxon,
                        "taxon_source": "ncbi" if authoritative else "user_declaration",
                        "taxid": str(1000 + idx) if authoritative else "",
                        "organism_name": f"Fixtureus {taxon} {idx}" if authoritative else "",
                        "lineage_names": lineage if authoritative else "",
                        "lineage_ids": lineage_ids if authoritative else "",
                        "prediction_method": "prodigal" if taxon == "bacteria" else "funannotate",
                        "detector_profile": "antismash" if taxon == "bacteria" else "antismash+funbgcex",
                    }
                )
                for bgc_index in range(1, idx + 1):
                    category = "NRPS" if bgc_index % 2 else "PKS"
                    exact_rows.append(
                        {
                            "genome": genome,
                            "bgc_id": f"{genome}.region{bgc_index:03d}",
                            "exact_product_type": category,
                            "broad_display_class": category,
                        }
                    )
        for idx, (genome, taxon) in enumerate(genomes):
            families = ["GCF_shared"]
            if dense:
                families.extend(f"GCF_pair_{pair}" for pair in range(idx + 1))
            else:
                families.append(f"GCF_private_{idx}")
            crosswalk_rows.append(
                {
                    "genome": genome,
                    "taxon_group": taxon,
                    "antismash_region": f"{genome}.region001",
                    "antismash_class": "NRPS",
                    "gcf_id": ";".join(families),
                }
            )
        write_tsv(
            manifest,
            ["genome_id", "taxon_group", "taxon_source", "taxid", "organism_name", "lineage_names", "lineage_ids", "prediction_method", "detector_profile"],
            rows,
        )
        write_tsv(exact, ["genome", "bgc_id", "exact_product_type", "broad_display_class"], exact_rows)
        write_tsv(crosswalk, ["genome", "taxon_group", "antismash_region", "antismash_class", "gcf_id"], crosswalk_rows)
        subprocess.run(
            [
                sys.executable,
                str(RENDERER),
                "--manifest", str(manifest),
                "--exact-products", str(exact),
                "--crosswalk", str(crosswalk),
                "--output-dir", str(output),
                "--max-visible-arcs", str(arc_cap),
            ],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        return output, temp

    def test_fungi_bacteria_both_one_and_layout_sizes_are_deterministic(self) -> None:
        namespace = "{http://www.w3.org/2000/svg}"
        for fungi, bacteria in [(1, 0), (0, 1), (2, 1), (8, 7), (13, 12), (25, 25)]:
            with self.subTest(fungi=fungi, bacteria=bacteria):
                output, temp = self.render_fixture(fungi, bacteria)
                self.addCleanup(temp.cleanup)
                svg = (output / "clusterweave_taxon_tree.svg").read_text(encoding="utf-8")
                newick = (output / "clusterweave_taxon_tree.nwk").read_text(encoding="utf-8")
                self.assertIn("Taxonomy + genome profiles", svg)
                self.assertIn("Pairwise GCF sharing", svg)
                self.assertIn("Rank-aligned; not a phylogram", svg)
                self.assertIn("lower-triangular Jaccard matrix", svg)
                self.assertIn('width="300mm"', svg)
                self.assertNotIn("GCF membership pie", svg)
                self.assertNotIn('class="gcf-arc"', svg)
                self.assertNotIn("HGT", svg)
                self.assertNotIn("horizontal transfer", svg.lower())
                if fungi:
                    self.assertIn("Fungi ·", svg)
                else:
                    self.assertNotIn("Fungi ·", svg)
                if bacteria:
                    self.assertIn("Bacteria ·", svg)
                else:
                    self.assertNotIn("Bacteria ·", svg)
                if fungi and bacteria:
                    self.assertIn("cross-domain", svg)
                self.assertIn("unresolved taxonomy", svg)
                self.assertNotIn("<script", svg.lower())
                self.assertNotIn(":0.", newick)
                self.assertTrue(newick.endswith(";\n"))

                root = ET.fromstring(svg)
                self.assertEqual(root.attrib["viewBox"].split()[2], "2200")
                leaf_labels = [
                    node
                    for node in root.iter(f"{namespace}text")
                    if node.attrib.get("class") == "leaf-label"
                ]
                self.assertEqual(len(leaf_labels), fungi + bacteria)
                self.assertTrue(
                    all(float(node.attrib["font-size"]) >= 13.2 for node in leaf_labels)
                )
                profiles = [
                    node
                    for node in root.iter(f"{namespace}g")
                    if node.attrib.get("class") == "bgc-profile"
                ]
                gcf_profiles = [
                    node
                    for node in root.iter(f"{namespace}g")
                    if node.attrib.get("class") == "gcf-profile"
                ]
                self.assertEqual(len(profiles), fungi + bacteria)
                self.assertEqual(len(gcf_profiles), fungi + bacteria)
                self.assertTrue(
                    all(float(node.attrib["data-width"]) == 230.0 for node in profiles)
                )
                self.assertTrue(
                    all(float(node.attrib["data-width"]) == 92.0 for node in gcf_profiles)
                )
                self.assertTrue(
                    all(
                        float(node.attrib["data-x"]) - float(profile.attrib["data-x"])
                        == 273.0
                        for node, profile in zip(gcf_profiles, profiles)
                    )
                )
                rank_titles = {
                    "".join(title.itertext())
                    for title in root.iter(f"{namespace}title")
                    if "".join(title.itertext()) in {
                        "Domain",
                        "Kingdom or clade",
                        "Phylum",
                        "Class",
                        "Order",
                        "Family",
                        "Genus",
                        "Species",
                    }
                }
                self.assertEqual(len(rank_titles), 8)
                y_values = sorted(float(node.attrib["y"]) for node in leaf_labels)
                minimum_step = 25.7 if fungi + bacteria >= 35 else 29.9
                self.assertTrue(
                    all(
                        right - left >= minimum_step
                        for left, right in zip(y_values, y_values[1:])
                    )
                )
                view_height = float(root.attrib["viewBox"].split()[3])
                self.assertGreaterEqual(view_height - y_values[-1], 100.0)

    def test_long_leaf_labels_are_bounded_with_lossless_titles(self) -> None:
        output, temp = self.render_fixture(1, 1)
        self.addCleanup(temp.cleanup)
        manifest = Path(temp.name) / "genome_taxon_manifest.tsv"
        with manifest.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        long_name = (
            "Extremely long authoritative organism name with strain and isolate "
            "context that must not overlap pies"
        )
        rows[0]["organism_name"] = long_name
        write_tsv(manifest, list(rows[0]), rows)
        subprocess.run(
            [
                sys.executable,
                str(RENDERER),
                "--manifest", str(manifest),
                "--exact-products", str(Path(temp.name) / "antismash_product_types_exact.tsv"),
                "--crosswalk", str(Path(temp.name) / "candidate_bgc_gcf_crosswalk.tsv"),
                "--output-dir", str(output),
            ],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        root = ET.parse(output / "clusterweave_taxon_tree.svg").getroot()
        labels = [
            node
            for node in root.iter("{http://www.w3.org/2000/svg}text")
            if node.attrib.get("class") == "leaf-label"
        ]
        self.assertEqual(len(labels), 2)
        title = labels[0].find("{http://www.w3.org/2000/svg}title")
        self.assertIsNotNone(title)
        assert title is not None
        title_text = "".join(title.itertext())
        tspans = labels[0].findall("{http://www.w3.org/2000/svg}tspan")
        visible = "".join("".join(node.itertext()) for node in tspans)
        self.assertLessEqual(len(visible), 48)
        self.assertIn("…", visible)
        self.assertEqual(tspans[0].attrib.get("font-style"), "italic")
        self.assertNotIn("[", visible)
        self.assertIn(long_name, title_text)
        self.assertIn("internal genome ID: fungi_01", title_text)

    def test_authoritative_leaf_italicizes_organism_not_strain_or_internal_id(self) -> None:
        output, temp = self.render_fixture(1, 0)
        self.addCleanup(temp.cleanup)
        manifest = Path(temp.name) / "genome_taxon_manifest.tsv"
        with manifest.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        rows[0]["organism_name"] = "Penicillium rubens Wisconsin 54-1255"
        rows[0]["taxid"] = "500485"
        rows[0]["lineage_names"] = "Eukaryota|Fungi|Ascomycota|Eurotiomycetes"
        rows[0]["lineage_ids"] = "2759|4751|4890|147545"
        rows[0]["taxon_source"] = "ncbi"
        write_tsv(manifest, list(rows[0]), rows)
        subprocess.run(
            [
                sys.executable,
                str(RENDERER),
                "--manifest", str(manifest),
                "--exact-products", str(Path(temp.name) / "antismash_product_types_exact.tsv"),
                "--crosswalk", str(Path(temp.name) / "candidate_bgc_gcf_crosswalk.tsv"),
                "--output-dir", str(output),
            ],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        root = ET.parse(output / "clusterweave_taxon_tree.svg").getroot()
        label = next(
            node
            for node in root.iter("{http://www.w3.org/2000/svg}text")
            if node.attrib.get("class") == "leaf-label"
        )
        tspans = label.findall("{http://www.w3.org/2000/svg}tspan")
        self.assertEqual(len(tspans), 2)
        self.assertEqual(tspans[0].attrib.get("font-style"), "italic")
        self.assertEqual("".join(tspans[0].itertext()), "Penicillium rubens")
        self.assertEqual("".join(tspans[1].itertext()), "\u00a0Wisconsin 54-1255")
        visible = "".join("".join(node.itertext()) for node in tspans)
        self.assertNotIn("[", visible)
        self.assertNotIn("fungi_01", visible)
        title = label.find("{http://www.w3.org/2000/svg}title")
        self.assertIsNotNone(title)
        assert title is not None
        self.assertIn("internal genome ID: fungi_01", "".join(title.itertext()))


    def test_dense_arc_cap_is_lossless_in_tsv_and_graphml(self) -> None:
        output, temp = self.render_fixture(3, 3, dense=True, arc_cap=4)
        self.addCleanup(temp.cleanup)
        with (output / "clusterweave_gcf_network_edges.tsv").open(newline="", encoding="utf-8") as handle:
            edges = list(csv.DictReader(handle, delimiter="\t"))
        self.assertGreater(len(edges), 4)
        self.assertEqual(sum(row["visible_in_svg"] == "True" for row in edges), 4)
        self.assertTrue(all(row["shared_gcf_classes"] for row in edges))
        self.assertTrue(all(row["gcf_class_counts"] for row in edges))
        graphml = (output / "clusterweave_taxon_tree.graphml").read_text(encoding="utf-8")
        self.assertEqual(graphml.count("<edge id="), len(edges))
        self.assertIn('id="shared_classes"', graphml)
        ET.fromstring(graphml)
        manifest = json.loads((output / "clusterweave_tree_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["edge_count"], len(edges))
        self.assertEqual(manifest["visible_arc_count"], 4)

    def test_repeated_exact_product_classes_make_one_hybrid_bgc(self) -> None:
        output, temp = self.render_fixture(1, 0)
        self.addCleanup(temp.cleanup)
        exact = Path(temp.name) / "antismash_product_types_exact.tsv"
        with exact.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        rows.append(
            {
                "genome": "fungi_01",
                "bgc_id": "fungi_01.region001",
                "exact_product_type": "T1PKS",
                "broad_display_class": "PKS",
            }
        )
        write_tsv(exact, list(rows[0]), rows)
        subprocess.run(
            [
                sys.executable,
                str(RENDERER),
                "--manifest", str(Path(temp.name) / "genome_taxon_manifest.tsv"),
                "--exact-products", str(exact),
                "--crosswalk", str(Path(temp.name) / "candidate_bgc_gcf_crosswalk.tsv"),
                "--output-dir", str(output),
            ],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        with (output / "clusterweave_taxon_tree_leaf_profiles.tsv").open(
            newline="", encoding="utf-8"
        ) as handle:
            profile = next(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(profile["bgc_total"], "1")
        self.assertEqual(profile["bgc_hybrid"], "1")
        self.assertEqual(profile["bgc_nrps"], "0")
        self.assertEqual(profile["bgc_pks"], "0")

    def test_class_colored_pair_matrix_and_table_preserve_gcf_semantics(self) -> None:
        output, temp = self.render_fixture(2, 0)
        self.addCleanup(temp.cleanup)
        svg = (output / "clusterweave_taxon_tree.svg").read_text(encoding="utf-8")
        root = ET.fromstring(svg)
        namespace = "{http://www.w3.org/2000/svg}"
        pair_cell = next(
            node
            for node in root.iter(f"{namespace}rect")
            if node.attrib.get("class") == "gcf-pair"
        )
        pair_title = pair_cell.find(f"{namespace}title")
        self.assertIsNotNone(pair_title)
        assert pair_title is not None
        pair_tooltip = "".join(pair_title.itertext())
        self.assertIn("GCF overlap 33.3% (Jaccard); 1 shared GCFs", pair_tooltip)
        self.assertIn(
            "Jaccard is shared GCFs divided by the nonredundant union of GCFs in either genome",
            pair_tooltip,
        )
        self.assertIn("NRPS 1 (100.0%)", pair_tooltip)

        gcf_profile = next(
            node
            for node in root.iter(f"{namespace}g")
            if node.attrib.get("class") == "gcf-profile"
        )
        bgc_profile = next(
            node
            for node in root.iter(f"{namespace}g")
            if node.attrib.get("class") == "bgc-profile"
        )
        self.assertEqual(float(gcf_profile.attrib["data-x"]), 1148.0)
        profile_title = gcf_profile.find(f"{namespace}title")
        self.assertIsNotNone(profile_title)
        assert profile_title is not None
        self.assertIn(
            "unique GCFs found in this genome and at least one other submitted genome, divided by all",
            "".join(profile_title.itertext()),
        )
        self.assertEqual(float(bgc_profile.attrib["data-x"]), 875.0)
        expected_palette = {
            "NRPS": "#56D8C1",
            "PKS": "#EC961C",
            "terpene": "#A743CC",
            "RiPP": "#5481E3",
            "hybrid": "#82775B",
            "other": "#A8BFFF",
        }
        for color in expected_palette.values():
            self.assertIn(color, svg)
        visible_text = [
            "".join(node.itertext())
            for node in root.iter(f"{namespace}text")
        ]
        self.assertTrue(any(text.endswith("GCF overlap · Jaccard %") for text in visible_text))
        self.assertTrue(any(text.endswith("Shared · % of genome GCFs.") for text in visible_text))
        self.assertIn("Shared GCFs by BGC class", visible_text)
        self.assertEqual(visible_text.count("Unique pairs below diagonal"), 1)
        self.assertEqual(svg.count('fill="#F6F6F6"'), 1)
        self.assertIn("0", visible_text)
        self.assertIn("50", visible_text)
        self.assertIn("100%", visible_text)
        segment_titles = [
            "".join(title.itertext())
            for node in root.iter(f"{namespace}rect")
            for title in node.findall(f"{namespace}title")
            if "each shared GCF is assigned its representative broad BGC class"
            in "".join(title.itertext())
        ]
        self.assertTrue(segment_titles)
        self.assertTrue(all("shared GCFs (" in title for title in segment_titles))
        with (output / "clusterweave_gcf_network_edges.tsv").open(
            newline="", encoding="utf-8"
        ) as handle:
            edge = next(csv.DictReader(handle, delimiter="\t"))
        self.assertIn("GCF_shared=NRPS", edge["shared_gcf_classes"])
        self.assertIn("NRPS:1", edge["gcf_class_counts"])
        methods = json.loads(
            (output / "clusterweave_tree_methods.json").read_text(encoding="utf-8")
        )
        self.assertIn("lower-triangular genome-pair Jaccard matrix", methods["gcf_arc_encoding"])
        self.assertIn("absolute BGC bars", methods["visual_layout"])

    def test_fungal_bacterial_and_cross_kingdom_pairwise_links_are_visible(self) -> None:
        output, temp = self.render_fixture(2, 2)
        self.addCleanup(temp.cleanup)
        root = ET.parse(output / "clusterweave_taxon_tree.svg").getroot()
        namespace = "{http://www.w3.org/2000/svg}"
        pair_titles = [
            "".join(title.itertext())
            for node in root.iter(f"{namespace}rect")
            if node.attrib.get("class") == "gcf-pair"
            for title in node.findall(f"{namespace}title")
        ]
        self.assertEqual(len(pair_titles), 6)
        self.assertTrue(all(" ↔ " in title for title in pair_titles))
        self.assertTrue(
            all("GCF overlap 33.3% (Jaccard); 1 shared GCFs" in title for title in pair_titles)
        )

        visible_text = [
            "".join(node.itertext())
            for node in root.iter(f"{namespace}text")
        ]
        self.assertEqual(sum(text.endswith("50.0%") for text in visible_text), 4)

        with (output / "clusterweave_gcf_network_edges.tsv").open(
            newline="", encoding="utf-8"
        ) as handle:
            edges = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(len(edges), 6)
        self.assertEqual(sum(row["cross_taxon"] == "yes" for row in edges), 4)
        self.assertEqual(sum(row["cross_taxon"] == "no" for row in edges), 2)

    def test_zero_shared_gcf_state_is_explicit_and_lossless(self) -> None:
        output, temp = self.render_fixture(2, 0)
        self.addCleanup(temp.cleanup)
        crosswalk = Path(temp.name) / "candidate_bgc_gcf_crosswalk.tsv"
        with crosswalk.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        for index, row in enumerate(rows):
            row["gcf_id"] = f"GCF_private_{index}"
        write_tsv(crosswalk, list(rows[0]), rows)
        subprocess.run(
            [
                sys.executable,
                str(RENDERER),
                "--manifest", str(Path(temp.name) / "genome_taxon_manifest.tsv"),
                "--exact-products", str(Path(temp.name) / "antismash_product_types_exact.tsv"),
                "--crosswalk", str(crosswalk),
                "--output-dir", str(output),
            ],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        svg = (output / "clusterweave_taxon_tree.svg").read_text(encoding="utf-8")
        self.assertIn("No shared GCF links", svg)
        with (output / "clusterweave_gcf_network_edges.tsv").open(
            newline="", encoding="utf-8"
        ) as handle:
            self.assertEqual(list(csv.DictReader(handle, delimiter="\t")), [])

    def test_zero_gcf_is_na_but_assigned_private_gcf_is_zero_percent(self) -> None:
        output, temp = self.render_fixture(2, 0)
        self.addCleanup(temp.cleanup)
        crosswalk = Path(temp.name) / "candidate_bgc_gcf_crosswalk.tsv"
        with crosswalk.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        rows[0]["gcf_id"] = ""
        rows[1]["gcf_id"] = "GCF_entirely_private"
        write_tsv(crosswalk, list(rows[0]), rows)
        subprocess.run(
            [
                sys.executable,
                str(RENDERER),
                "--manifest", str(Path(temp.name) / "genome_taxon_manifest.tsv"),
                "--exact-products", str(Path(temp.name) / "antismash_product_types_exact.tsv"),
                "--crosswalk", str(crosswalk),
                "--output-dir", str(output),
            ],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        root = ET.parse(output / "clusterweave_taxon_tree.svg").getroot()
        namespace = "{http://www.w3.org/2000/svg}"
        visible_text = [
            "".join(node.itertext())
            for node in root.iter(f"{namespace}text")
        ]
        self.assertEqual(sum(text.endswith("N/A") for text in visible_text), 1)
        self.assertEqual(sum(text.endswith("0.0%") for text in visible_text), 1)
        na_bar = next(
            node
            for node in root.iter(f"{namespace}rect")
            if node.attrib.get("class") == "gcf-status-na"
        )
        self.assertEqual(na_bar.attrib.get("stroke-dasharray"), "2 2")
        self.assertEqual(na_bar.attrib.get("fill"), "#FFFFFF")
        na_tooltip = na_bar.find(f"{namespace}title")
        self.assertIsNotNone(na_tooltip)
        assert na_tooltip is not None
        self.assertIn(
            "no GCFs are assigned in the selected view",
            "".join(na_tooltip.itertext()),
        )

    def test_mixed_arc_cap_reserves_cross_taxon_context(self) -> None:
        output, temp = self.render_fixture(3, 3, dense=True, arc_cap=1)
        self.addCleanup(temp.cleanup)
        with (output / "clusterweave_gcf_network_edges.tsv").open(newline="", encoding="utf-8") as handle:
            visible = [
                row
                for row in csv.DictReader(handle, delimiter="\t")
                if row["visible_in_svg"] == "True"
            ]
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0]["cross_taxon"], "yes")

    def test_repeated_render_is_byte_deterministic(self) -> None:
        output, temp = self.render_fixture(2, 2, dense=True, arc_cap=3)
        self.addCleanup(temp.cleanup)
        first = {
            path.name: path.read_bytes()
            for path in output.iterdir()
            if path.is_file()
        }
        subprocess.run(
            [
                sys.executable,
                str(RENDERER),
                "--manifest", str(Path(temp.name) / "genome_taxon_manifest.tsv"),
                "--exact-products", str(Path(temp.name) / "antismash_product_types_exact.tsv"),
                "--crosswalk", str(Path(temp.name) / "candidate_bgc_gcf_crosswalk.tsv"),
                "--output-dir", str(output),
                "--max-visible-arcs", "3",
            ],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        second = {
            path.name: path.read_bytes()
            for path in output.iterdir()
            if path.is_file()
        }
        self.assertEqual(second, first)

    def test_refresh_without_png_removes_stale_optional_png(self) -> None:
        output, temp = self.render_fixture(1, 1)
        self.addCleanup(temp.cleanup)
        stale_png = output / "clusterweave_taxon_tree.png"
        stale_png.write_bytes(b"stale png")
        subprocess.run(
            [
                sys.executable,
                str(RENDERER),
                "--manifest", str(Path(temp.name) / "genome_taxon_manifest.tsv"),
                "--exact-products", str(Path(temp.name) / "antismash_product_types_exact.tsv"),
                "--crosswalk", str(Path(temp.name) / "candidate_bgc_gcf_crosswalk.tsv"),
                "--output-dir", str(output),
            ],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        )
        self.assertFalse(stale_png.exists())
        with zipfile.ZipFile(output / "clusterweave_tree_bundle.zip") as archive:
            self.assertNotIn("clusterweave_taxon_tree.png", archive.namelist())

    def test_exact_bundle_contains_declared_tree_artifacts_only(self) -> None:
        output, temp = self.render_fixture(1, 2)
        self.addCleanup(temp.cleanup)
        bundle = output / "clusterweave_tree_bundle.zip"
        with zipfile.ZipFile(bundle) as archive:
            names = set(archive.namelist())
        self.assertEqual(
            names,
            {
                "clusterweave_taxon_tree.svg",
                "clusterweave_taxon_tree.nwk",
                "clusterweave_taxon_tree_leaf_profiles.tsv",
                "clusterweave_gcf_network_edges.tsv",
                "clusterweave_taxon_tree.graphml",
                "clusterweave_tree_manifest.json",
                "clusterweave_tree_methods.json",
            },
        )


if __name__ == "__main__":
    unittest.main()
