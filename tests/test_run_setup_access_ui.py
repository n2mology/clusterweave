import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX = REPO_ROOT / "web" / "static" / "index.html"
CSS = REPO_ROOT / "web" / "static" / "assets" / "clusterweave.css"
JS = REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js"
INTAKE_JS = REPO_ROOT / "web" / "static" / "assets" / "intake-taxon-boundary.js"


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
        cls.intake_js = INTAKE_JS.read_text(encoding="utf-8")

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

    def test_result_access_is_a_compact_copy_all_credential_receipt(self) -> None:
        result_access_markup = re.search(
            r'<a id="run-setup-result-link"[^>]*>Pending</a>', self.index
        )
        self.assertIsNotNone(result_access_markup)
        self.assertIn('onclick="openRunSetupResultAccess(event)"', result_access_markup.group(0))
        self.assertIn('id="run-setup-access-code"', self.index)
        self.assertIn('id="run-setup-public-id"', self.index)
        self.assertIn(
            'SAVE/COPY YOUR JOB CREDENTIALS. ANYONE WITH THESE CAN READ THE RESULTS.',
            self.index,
        )
        self.assertNotIn("run-setup-copy-arrow", self.index)
        self.assertRegex(
            self.index,
            r'id="copy-run-setup-credentials"[^>]*onclick="copyRunSetupCredentials\(\)"[^>]*>COPY</button>',
        )
        self.assertNotRegex(
            self.index,
            r'id="copy-run-setup-credentials"[^>]*aria-label=',
        )

        configure = function_body(
            self.js, "configureRunSetupResultLink", "copyRunSetupCredentials"
        )
        self.assertIn("resultUrl", configure)
        self.assertIn("const runId = publicRunIdForJob(id)", configure)
        self.assertIn("privateResultLink(runId, token, resultUrl)", configure)
        self.assertRegex(configure, r"link\.textContent\s*=\s*href")
        self.assertRegex(configure, r"link\.href\s*=\s*href")
        self.assertIn("link.dataset.jobId = runId", configure)
        self.assertIn("link.dataset.privateLink = href", configure)
        self.assertIn("Open results for run ${runId}", configure)
        self.assertIn("readToken", configure)
        self.assertIn(
            "configureRunSetupResultLink(link, runId, readToken, resultUrl)",
            self.js,
        )

        copy_all = function_body(
            self.js, "copyRunSetupCredentials", "openRunSetupResultAccess"
        )
        self.assertIn("PRIVATE LINK:", copy_all)
        self.assertIn("ACCESS CODE:", copy_all)
        self.assertIn("RUN ID:", copy_all)
        self.assertIn("button.textContent = 'COPIED'", copy_all)
        self.assertIn("button.classList.add('is-copied')", copy_all)
        self.assertIn("copyButton.classList.remove('is-copied')", self.js)
        self.assertIn("const previousPrivateLink", self.js)
        self.assertIn("const keepCopied", self.js)
        self.assertIn("if (!keepCopied) copyButton.textContent = 'COPY'", self.js)

        copy_button = rule(self.css, ".run-setup-copy-button")
        copy_action = rule(self.css, ".run-setup-credential-copy")
        copy_head = rule(self.css, ".run-setup-credential-head")
        credential_row = rule(self.css, ".run-setup-credential-row")
        credential_list = rule(self.css, ".run-setup-credential-list")
        credential_label = rule(self.css, ".run-setup-credential-row dt")
        copied_button = rule(self.css, ".run-setup-copy-button.is-copied")
        credential_note = rule(self.css, ".run-setup-credential-note")
        self.assertIn("background: var(--orange)", copy_button)
        self.assertIn("font-family: var(--mono)", copy_button)
        self.assertIn("font-size: smaller", copy_button)
        self.assertIn("justify-content: flex-end", copy_action)
        self.assertIn("justify-content: space-between", copy_head)
        self.assertIn("border: 3px solid var(--line)", credential_list)
        self.assertIn("background: var(--orange-soft)", credential_list)
        self.assertIn("font-weight: 1000", credential_label)
        self.assertIn("background: var(--pink)", copied_button)
        self.assertNotIn("border:", credential_row)
        self.assertNotIn("background:", credential_row)
        self.assertIn("text-transform: uppercase", credential_note)
        self.assertIn("background: var(--acid)", credential_note)
        self.assertIn("white-space: nowrap", credential_note)

        clipboard = function_body(
            self.js, "legacyCopyTextToClipboard", "copyTextToClipboard"
        )
        self.assertIn("helper.setSelectionRange(0, helper.value.length)", clipboard)
        self.assertIn("event.clipboardData.setData('text/plain', text)", clipboard)
        self.assertIn("event.preventDefault()", clipboard)
        self.assertIn("commandAccepted || copyEventHandled", clipboard)
        self.assertIn("previousFocus?.focus", clipboard)

        receipt_preference = function_body(
            self.js, "runSetupReceiptHasSpecificInputs", "runSetupJobHref"
        )
        self.assertIn("runSetupReceiptMatchesJob", receipt_preference)
        self.assertIn("preferredRunSetupReceipt", receipt_preference)
        self.assertIn("!runSetupReceiptHasSpecificInputs(incomingReceipt)", receipt_preference)

    def test_run_stack_persists_and_restores_a_bounded_specific_receipt(self) -> None:
        remember = function_body(self.js, "rememberOpenedRun", "adoptPublicRunIdentity")
        adopt = function_body(self.js, "adoptPublicRunIdentity", "legacyCopyTextToClipboard")
        snapshot = function_body(
            self.js, "runSetupStoredReceiptSnapshot", "rememberedRunSetupReceipt"
        )
        remembered = function_body(
            self.js, "rememberedRunSetupReceipt", "runSetupReceiptMatchesJob"
        )
        active = function_body(
            self.js, "renderActiveRunAccessPanel", "dismissSubmissionConfirmation"
        )

        self.assertIn("const existingRun = openedRuns.find", remember)
        self.assertIn("meta.receipt || runSetupReceiptFromJob(meta)", remember)
        self.assertIn("preferredRunSetupReceipt(incomingReceipt, existingRun?.receipt)", remember)
        self.assertIn("...(receipt ? { receipt } : {})", remember)
        self.assertIn("const rememberedRun = openedRuns.find", adopt)
        self.assertIn("runSetupStoredReceiptSnapshot(rememberedRun?.receipt)", adopt)
        self.assertIn("...(receipt ? { receipt } : {})", adopt)

        self.assertIn("receiptAcceptedInputItems(receipt)", snapshot)
        self.assertIn(".filter(item => !item.summary)", snapshot)
        self.assertIn(".slice(0, 100)", snapshot)
        for field in [
            "label", "kind", "source", "isTarget", "organismName", "taxa",
            "taxonGroup", "taxId", "orderName", "familyName", "className",
            "orderFamily",
        ]:
            self.assertIn(f"{field}:", snapshot)
        self.assertNotIn("lineage", snapshot)
        self.assertNotIn("genome_id", snapshot)
        self.assertNotIn("inputSummary", snapshot)
        self.assertIn("loadOpenedRuns().find", remembered)

        self.assertIn("rememberedRunSetupReceipt(jobId, publicRunId)", active)
        self.assertIn("preferredRunSetupReceipt(incomingReceipt, rememberedReceipt)", active)
        self.assertIn("receipt: runSetupReceipt", self.intake_js)

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
