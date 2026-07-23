import importlib.util
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "bin" / "postprocess_clinker_html.py"


def load_module():
    spec = importlib.util.spec_from_file_location("postprocess_clinker_html", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ClinkerLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_target_genome_prettify_keeps_strain(self) -> None:
        result = self.module.prettify_genome_name("Aspergillus_nidulans_FGSC_A4")
        self.assertEqual(result, "Aspergillus nidulans FGSC A4")

    def test_bacterial_cluster_uses_canonical_organism_without_route_prefix(self) -> None:
        result = self.module.friendly_cluster_name({
            "role": "target",
            "genome": "bacteria_Bacillus_subtilis_168",
            "taxon_group": "bacteria",
            "organism_name": "Bacillus subtilis 168",
            "antismash_region": "NZ_CP010052.1.region001",
        })
        self.assertEqual(result, "Bacillus subtilis 168")
        self.assertNotIn("bacteria", result.lower())

    def test_bacterial_cluster_fallback_removes_only_route_prefix(self) -> None:
        result = self.module.friendly_cluster_name({
            "role": "target",
            "genome": "bacteria_Bacillus_demo",
            "taxon_group": "bacteria",
            "taxon_source": "ncbi",
            "antismash_region": "NZ_CP000001.1.region001",
        })
        self.assertEqual(result, "Bacillus demo")

    def test_user_bacterial_id_prefix_is_not_reinterpreted(self) -> None:
        result = self.module.friendly_cluster_name({
            "role": "target",
            "genome": "bacteria_isolate_7",
            "taxon_group": "bacteria",
            "taxon_source": "user_declaration",
            "antismash_region": "contig_1.region001",
        })
        self.assertEqual(result, "bacteria isolate 7")

    def test_scaffold_subtitle_is_region_free_and_has_no_underscore_separators(self) -> None:
        result = self.module.friendly_scaffold_name({
            "antismash_region": "NZ_CP010052.1.region001",
        })
        self.assertEqual(result, "NZ CP010052.1")

    def test_bacterial_scaffold_subtitle_prefers_original_record_id(self) -> None:
        result = self.module.friendly_scaffold_name({
            "antismash_region": (
                "bacteria_Streptomyces_griseus_NBRC_13350_"
                "NC_010572.1.region009"
            ),
            "scaffold_id": "NC_010572.1",
        })
        self.assertEqual(result, "NC 010572.1")
        self.assertNotIn("Streptomyces", result)

    def test_mibig_reference_taxon_compacts_to_genus_species(self) -> None:
        result = self.module.compact_reference_taxon("Aspergillus nidulans FGSC A4")
        self.assertEqual(result, "Aspergillus nidulans")

    def test_mibig_reference_taxon_preserves_sp_placeholder(self) -> None:
        result = self.module.compact_reference_taxon("Aspergillus sp. CBS 101")
        self.assertEqual(result, "Aspergillus sp.")

    def test_strip_display_artifacts_removes_eurofung_tag(self) -> None:
        result = self.module.strip_display_artifacts("Acyl-CoA dehydrogenase (Eurofung)")
        self.assertEqual(result, "Acyl-CoA dehydrogenase")

    def test_apply_html_defaults_sets_readable_panel_defaults(self) -> None:
        html = """
const data={};
function plot(data) {
  const chart = ClusterMap.ClusterMap()
    .config({
      scaleFactor: 30,
      cluster: {
        spacing: 50,
        alignLabels: true,
      },
      gene: {
        label: {
          show: false,
        }
      },
    })

  let plot = d3.select("#plot")
}
<input type="number" id="input-scale-factor" value="15" default="15" >
<input type="number" id="input-cluster-spacing" value="40" default="40">
<input id="input-cluster-hide-coords" type="checkbox">
<input type="checkbox" id="input-gene-labels">
<input type="checkbox" id="input-link-group-colour">
<input type="checkbox" id="input-link-label-show">
"""
        patched = self.module.apply_html_defaults(html)
        self.assertIn("scaleFactor: 12", patched)
        self.assertIn("spacing: 70", patched)
        self.assertIn("hideLocusCoordinates: true", patched)
        self.assertIn('id="input-gene-labels" checked', patched)
        self.assertIn('id="input-link-group-colour" checked', patched)
        self.assertIn('id="input-link-label-show" checked', patched)


if __name__ == "__main__":
    unittest.main()
