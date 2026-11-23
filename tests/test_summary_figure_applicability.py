"""Execute the R renderer and inspect its real plotted matrix and labels."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('Rscript'), 'Rscript is required')
class SummaryFigureApplicabilityTests(unittest.TestCase):
    def test_only_observed_valid_tool_pairs_are_plotted(self):
        with tempfile.TemporaryDirectory() as tmp:
            script=Path(tmp)/'bin/check.R'
            script.parent.mkdir()
            (Path(tmp)/'config').mkdir()
            shutil.copy2(ROOT/'config/bgc-display-classes.tsv',Path(tmp)/'config/bgc-display-classes.tsv')
            source=(ROOT/'bin/render_summary_figures.R').read_text().rsplit('\nmain()',1)[0]
            script.write_text(source+'''
original_barplot <- barplot
barplot <- function(height, ...) {
  stopifnot(identical(colnames(height), c("Fungus__antismash", "Fungus__funbgcex", "Plant__plantismash", "Bacterium__antismash")))
  stopifnot(identical(as.numeric(colSums(height)), c(1, 2, 3, 0)))
  original_barplot(height, ...)
}
stopifnot(display_tool_label("plantismash") == "plantiSMASH")
d <- data.frame(entity_type="BGC", genome=c("Fungus","Fungus","Plant","Bacterium","Failed"),
                tool=c("antismash","funbgcex","plantismash","antismash","plantismash"),
                class_norm="terpene", total=c(1,2,3,0,NA))
stopifnot(plot_bgc_totals(d, "''' + str(Path(tmp)/'actual.svg') + '''"))
stopifnot(!plot_bgc_totals(d[5,,drop=FALSE], "''' + str(Path(tmp)/'unknown.svg') + '''"))
''')
            result=subprocess.run(['Rscript',str(script)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('Unknown BGC counts omitted',result.stderr)
            self.assertTrue((Path(tmp)/'actual.svg').is_file())
            self.assertFalse((Path(tmp)/'unknown.svg').exists())
if __name__=='__main__':unittest.main()
