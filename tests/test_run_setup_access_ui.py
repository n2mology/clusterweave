import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX = REPO_ROOT / "web" / "static" / "index.html"
CSS = REPO_ROOT / "web" / "static" / "assets" / "clusterweave.css"
JS = REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js"


def rule(text: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", text, re.DOTALL)
    if not match:
        raise AssertionError(f"missing CSS rule: {selector}")
    return match.group(1)


def function_body(text: str, name: str, next_name: str) -> str:
    start = text.index(f"function {name}")
    end = text.index(f"function {next_name}", start)
    return text[start:end]


class RunSetupAccessUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = INDEX.read_text(encoding="utf-8")
        cls.css = CSS.read_text(encoding="utf-8")
        cls.js = JS.read_text(encoding="utf-8")

    def test_accepted_input_list_uses_the_full_card_without_a_blank_bumper(self) -> None:
        card = rule(self.css, ".receipt-accession-card")
        receipt_list = rule(self.css, ".receipt-list")

        self.assertIn("display: grid", card)
        self.assertIn("grid-template-rows: auto minmax(0, 1fr)", card)
        self.assertIn("contain: size", card)
        self.assertIn("min-height: 0", receipt_list)
        self.assertIn("align-content: start", receipt_list)
        self.assertIn("max-height: none", receipt_list)
        self.assertIn("overflow-y: auto", receipt_list)
        self.assertNotIn("max-height: 182px", self.css)
        self.assertIn(".receipt-accession-card { grid-template-rows: auto auto; contain: none; }", self.css)
        self.assertIn(".receipt-list { max-height: min(52dvh, 32rem); }", self.css)

    def test_result_access_is_an_accessible_token_free_public_run_link(self) -> None:
        result_access_markup = re.search(
            r'<a id="run-setup-result-link"[^>]*>Pending</a>', self.index
        )
        self.assertIsNotNone(result_access_markup)
        self.assertIn('onclick="openRunSetupResultAccess(event)"', result_access_markup.group(0))

        configure = function_body(
            self.js, "configureRunSetupResultLink", "openRunSetupResultAccess"
        )
        self.assertNotIn("resultUrl", configure)
        self.assertIn("const runId = publicRunIdForJob(id)", configure)
        self.assertIn("runSetupJobHref(runId)", configure)
        self.assertNotIn("link.textContent = id", configure)
        self.assertRegex(configure, r"link\.textContent\s*=\s*href")
        self.assertRegex(configure, r"link\.href\s*=\s*href")
        self.assertIn("link.dataset.jobId = runId", configure)
        self.assertIn("Open results for run ${runId}", configure)
        self.assertNotIn("readToken", configure)
        self.assertNotIn("read_token", configure)
        self.assertIn("configureRunSetupResultLink(link, jobId)", self.js)

    def test_taxon_pill_sits_in_the_card_status_group_before_acceptance_dot(self) -> None:
        renderer = function_body(
            self.js, "renderRunSetupInputReceipt", "receiptListFromValue"
        )
        status_group = rule(self.css, ".receipt-row-status")
        taxon_pill = rule(self.css, ".receipt-row-status .receipt-taxon-chip")
        receipt_row = rule(self.css, ".receipt-row")

        self.assertIn('class="receipt-row-status"', renderer)
        self.assertIn('class="receipt-chip receipt-taxon-chip"', renderer)
        self.assertIn('class="receipt-dot" role="img" aria-label="Accepted input"', renderer)
        self.assertLess(renderer.index("receipt-taxon-chip"), renderer.index("receipt-dot"))
        self.assertNotIn(
            "chips.push(renderReceiptChip(analysisScopeLabel(item.taxonGroup)))",
            renderer,
        )
        self.assertIn(
            "${chips.length ? `<div class=\"receipt-eco\">${chips.join('')}</div>` : ''}",
            renderer,
        )
        self.assertIn("display: inline-flex", status_group)
        self.assertIn("justify-content: flex-end", status_group)
        self.assertIn("max-width:", taxon_pill)
        self.assertIn("white-space: nowrap", taxon_pill)
        self.assertIn("--receipt-genome-card-row-height: 2.75rem", self.css)
        self.assertIn("min-height: var(--receipt-genome-card-row-height)", receipt_row)

    def test_result_route_is_opaque_token_free_and_reloadable(self) -> None:
        href = function_body(self.js, "runSetupJobHref", "configureRunSetupResultLink")
        parser = function_body(self.js, "parseResultHash", "runtimeMetricText")
        navigation = function_body(self.js, "navigateToSection", "syncNavFromHash")

        self.assertIn("#/results/${encodeURIComponent(id)}", href)
        self.assertIn("defaultApiBaseUrl()", href)
        self.assertNotIn("token", href.lower())
        self.assertIn("readTokenForJob(jobId)", parser)
        self.assertIn("routeKind === 'results'", parser)
        self.assertIn("if (!token && !canUseAdminSurfaces()) return null", parser)
        self.assertIn("target === 'outputs' && outputRunId", navigation)
        self.assertIn(
            "const outputRunId = activePublicRunId || publicRunIdFromJob(activeJobMeta, '')",
            navigation,
        )
        self.assertNotIn("#/job/${encodeURIComponent(activeJobId)}", navigation)
        self.assertIn(
            "window.history.replaceState(null, '', `#/results/${encodeURIComponent(publicId)}`)",
            self.js,
        )


if __name__ == "__main__":
    unittest.main()
