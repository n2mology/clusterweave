from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = REPO_ROOT / "web" / "static" / "index.html"
JS_PATH = REPO_ROOT / "web" / "static" / "assets" / "clusterweave.js"
CSS_PATH = REPO_ROOT / "web" / "static" / "assets" / "clusterweave.css"
NODE = shutil.which("node")


def function_source(source: str, name: str) -> str:
    """Return one top-level JS function without depending on its next neighbor."""

    start = source.index(f"function {name}")
    brace = source.index("{", start)
    depth = 0
    quote = ""
    escaped = False
    template_depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if escaped:
            escaped = False
            continue
        if quote:
            if char == "\\":
                escaped = True
            elif char == quote and template_depth == 0:
                quote = ""
            elif quote == "`" and char == "$" and source[index + 1 : index + 2] == "{":
                template_depth += 1
            elif quote == "`" and char == "}" and template_depth:
                template_depth -= 1
            continue
        if char in {"'", '"', "`"}:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unterminated function: {name}")


def run_node_json(source: str) -> object:
    if NODE is None:
        raise unittest.SkipTest("Node.js is required for frontend behavior tests")
    completed = subprocess.run(
        [NODE, "-e", source],
        cwd=REPO_ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "Input Station Node probe failed\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


class InputStationUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = INDEX_PATH.read_text(encoding="utf-8")
        cls.js = JS_PATH.read_text(encoding="utf-8")
        cls.css = CSS_PATH.read_text(encoding="utf-8")

    def test_ncbi_only_input_has_no_synthetic_upload_or_acknowledgment_gate(self) -> None:
        renderer = function_source(self.js, "renderFileList")
        acknowledgment = function_source(self.js, "uploadedInputRequiresAcknowledgment")

        self.assertNotIn("Manual entry", renderer)
        self.assertNotIn("MANUAL_ACCESSIONS_FILENAME", renderer)
        self.assertNotIn("acceptedManualAccessions", acknowledgment)
        self.assertNotIn("manualAccessionLines", acknowledgment)

        result = run_node_json(
            """
let selectedFiles = [];
let accessionFileSources = [];
let taxonAssignmentSidecar = null;
let admin = false;
function canUseAdminSurfaces() { return admin; }
"""
            + acknowledgment
            + """
const ncbiOnly = uploadedInputRequiresAcknowledgment();
selectedFiles = [{name: 'uploaded.gbk'}];
const uploaded = uploadedInputRequiresAcknowledgment();
selectedFiles = [];
accessionFileSources = [{name: 'accessions.txt'}];
const uploadedAccessionList = uploadedInputRequiresAcknowledgment();
accessionFileSources = [];
taxonAssignmentSidecar = {name: 'taxon_assignments.tsv'};
const uploadedSidecar = uploadedInputRequiresAcknowledgment();
admin = true;
const adminUpload = uploadedInputRequiresAcknowledgment();
process.stdout.write(JSON.stringify({
  ncbiOnly,
  uploaded,
  uploadedAccessionList,
  uploadedSidecar,
  adminUpload,
}));
"""
        )
        self.assertFalse(result["ncbiOnly"])
        self.assertTrue(result["uploaded"])
        self.assertTrue(result["uploadedAccessionList"])
        self.assertTrue(result["uploadedSidecar"])
        self.assertFalse(result["adminUpload"])

    def test_static_asset_versions_bypass_the_prior_day_cache(self) -> None:
        self.assertIn("clusterweave.css?v=20260723-timer-utc1", self.index)
        self.assertIn("clusterweave.js?v=20260723-timer-utc1", self.index)
        self.assertNotIn("clusterweave.css?v=20260713-workflow-bars4", self.index)
        self.assertNotIn("clusterweave.js?v=20260713-workflow-bars4", self.index)

    def test_accession_list_upload_tracks_its_source_and_removal_owns_rows(self) -> None:
        add_source = "async " + function_source(self.js, "addAccessionFileSource")
        remove_source = function_source(self.js, "removeAccessionFileSource")
        owned = function_source(self.js, "accessionFileOwnedAccessions")
        detach = function_source(self.js, "detachAccessionFromFileSources")
        acknowledgment = function_source(self.js, "uploadedInputRequiresAcknowledgment")

        result = run_node_json(
            """
let accessionFileSources = [];
let acceptedManualAccessions = [];
let brutalAccessionDrafts = Array.from({length: 50}, () => '');
let brutalAccessionCommitted = new Set();
let brutalEcoSelections = new Map();
let selectedFiles = [];
let taxonAssignmentSidecar = null;
function canUseAdminSurfaces() { return false; }
function normalizeAccessionDraft(value) { return String(value || '').trim().toUpperCase(); }
function parseAccessionText(text) {
  return {
    accessions: String(text || '').trim().split(/\\s+/).map(normalizeAccessionDraft).filter(Boolean),
    invalid: [],
    duplicateCount: 0,
  };
}
function manualAccessionLines() {
  const seen = new Set();
  const merged = [];
  [...acceptedManualAccessions, ...accessionFileSources.flatMap(source => source.accessions || [])].forEach((value) => {
    const normalized = normalizeAccessionDraft(value);
    if (!normalized || seen.has(normalized)) return;
    seen.add(normalized);
    merged.push(normalized);
  });
  return merged;
}
function importAccessionsToLoader(accessions) {
  const imported = accessions.map(normalizeAccessionDraft).filter(Boolean);
  acceptedManualAccessions.push(...imported);
  imported.forEach((accession, index) => { brutalAccessionDrafts[index] = accession; });
  return imported;
}
function acceptedDraftAccessions() { return brutalAccessionDrafts.map(normalizeAccessionDraft).filter(Boolean); }
function setBrutalInputNotice() {}
function renderBrutalAccessionRows() {}
function syncBrutalAcceptedFromDrafts() {
  const fileOwned = accessionFileOwnedAccessions();
  acceptedManualAccessions = acceptedDraftAccessions().filter(accession => !fileOwned.has(accession));
}
const uploadStatus = {textContent: ''};
const document = {getElementById(id) { return id === 'upload-status' ? uploadStatus : null; }};
"""
            + owned
            + "\n"
            + detach
            + "\n"
            + add_source
            + "\n"
            + remove_source
            + "\n"
            + acknowledgment
            + """
(async () => {
  const added = await addAccessionFileSource({
    name: 'assemblies.txt',
    async text() { return 'GCA_000011425.1\\n'; },
  });
  const afterAdd = {
    added,
    sourceCount: accessionFileSources.length,
    sourceName: accessionFileSources[0]?.name || '',
    accessions: manualAccessionLines(),
    manualOwned: acceptedManualAccessions.slice(),
    acknowledgment: uploadedInputRequiresAcknowledgment(),
  };
  removeAccessionFileSource(0);
  const afterRemove = {
    sourceCount: accessionFileSources.length,
    accessions: manualAccessionLines(),
    acknowledgment: uploadedInputRequiresAcknowledgment(),
  };
  await addAccessionFileSource({
    name: 'assemblies.txt',
    async text() { return 'GCA_000011425.1'; },
  });
  detachAccessionFromFileSources('GCA_000011425.1');
  const afterDetach = {
    sourceCount: accessionFileSources.length,
    acknowledgment: uploadedInputRequiresAcknowledgment(),
  };
  process.stdout.write(JSON.stringify({afterAdd, afterRemove, afterDetach}));
})().catch((error) => { console.error(error); process.exit(1); });
"""
        )
        self.assertTrue(result["afterAdd"]["added"])
        self.assertEqual(result["afterAdd"]["sourceCount"], 1)
        self.assertEqual(result["afterAdd"]["sourceName"], "assemblies.txt")
        self.assertEqual(result["afterAdd"]["accessions"], ["GCA_000011425.1"])
        self.assertEqual(result["afterAdd"]["manualOwned"], [])
        self.assertTrue(result["afterAdd"]["acknowledgment"])
        self.assertEqual(result["afterRemove"]["sourceCount"], 0)
        self.assertEqual(result["afterRemove"]["accessions"], [])
        self.assertFalse(result["afterRemove"]["acknowledgment"])
        self.assertEqual(result["afterDetach"]["sourceCount"], 0)
        self.assertFalse(result["afterDetach"]["acknowledgment"])

    def test_uploaded_input_reveals_acknowledgment_and_gates_submit(self) -> None:
        acknowledgment = function_source(self.js, "uploadedInputRequiresAcknowledgment")
        sync = function_source(self.js, "syncDataUseAcknowledgment")
        renderer = function_source(self.js, "renderFileList")

        self.assertIn("syncDataUseAcknowledgment()", renderer)
        self.assertIn("ackMissing", renderer)
        disabled_assignment = renderer.index("btn.disabled")
        self.assertIn("ackMissing", renderer[disabled_assignment : disabled_assignment + 500])

        result = run_node_json(
            """
function classList() {
  const values = new Set();
  return {
    toggle(name, force) {
      if (force) values.add(name); else values.delete(name);
      return force;
    },
    contains(name) { return values.has(name); },
  };
}
const panel = {
  hidden: false,
  inert: false,
  classList: classList(),
  setAttribute(name, value) { this[name] = value; },
  removeAttribute(name) { delete this[name]; },
  toggleAttribute(name, force) {
    if (force) this[name] = true; else delete this[name];
    if (name === 'inert') this.inert = !!force;
  },
};
const checkbox = {checked: false};
const document = {
  getElementById(id) {
    if (id === 'data-use-ack-panel') return panel;
    if (id === 'data-use-ack') return checkbox;
    return null;
  },
};
let selectedFiles = [];
let accessionFileSources = [];
let taxonAssignmentSidecar = null;
function canUseAdminSurfaces() { return false; }
"""
            + acknowledgment
            + "\n"
            + sync
            + """
const emptyMissing = syncDataUseAcknowledgment();
const empty = {hidden: panel.hidden, inert: panel.inert, missing: emptyMissing};
selectedFiles = [{name: 'uploaded.gbk'}];
const uploadMissing = syncDataUseAcknowledgment();
const upload = {hidden: panel.hidden, inert: panel.inert, missing: uploadMissing};
checkbox.checked = true;
const acceptedMissing = syncDataUseAcknowledgment();
const accepted = {hidden: panel.hidden, inert: panel.inert, missing: acceptedMissing};
process.stdout.write(JSON.stringify({empty, upload, accepted}));
"""
        )
        self.assertTrue(result["empty"]["hidden"])
        self.assertTrue(result["empty"]["inert"])
        self.assertFalse(result["empty"]["missing"])
        self.assertFalse(result["upload"]["hidden"])
        self.assertFalse(result["upload"]["inert"])
        self.assertTrue(result["upload"]["missing"])
        self.assertFalse(result["accepted"]["missing"])

    def test_project_name_input_immediately_removes_the_submit_lock(self) -> None:
        initializer = function_source(self.js, "initializeBrutalInputStation")
        renderer = function_source(self.js, "renderFileList")

        project_listener = initializer.index("document.getElementById('project-name')")
        project_listener_end = initializer.index("document.getElementById('target-genome')", project_listener)
        self.assertIn("renderFileList()", initializer[project_listener:project_listener_end])
        self.assertIn("submit-button-shell", self.index)
        self.assertIn("is-project-locked", self.index)
        self.assertIn("is-project-locked", self.css)
        self.assertIn("submit-button-shell", renderer)
        self.assertIn("classList.toggle('is-project-locked'", renderer)

    def test_uploaded_genome_row_toggles_target_and_exposes_ecology_without_a_target_badge(self) -> None:
        renderer = function_source(self.js, "renderFileList")
        click_handler = function_source(self.js, "handleUploadedGenomeTargetClick")
        remove = function_source(self.js, "removeFile")

        self.assertIn("data-target-genome", renderer)
        self.assertNotIn("data-target-select", renderer)
        self.assertNotIn('file-target-select', renderer)
        self.assertIn('class=\"eco-button file-eco-button\" type=\"button\"', renderer)
        self.assertIn("file-item", renderer)
        self.assertNotIn('role=\"button\"', renderer)
        self.assertNotIn('tabindex=\"0\"', renderer)
        self.assertIn("file-remove", click_handler)
        self.assertIn("data-target-genome", click_handler)
        self.assertIn("target-genome", remove)
        self.assertIn("genomeStemFromName", remove)
        self.assertIn("updateBrutalTargetButton", remove)
        self.assertNotIn(".file-target-select", self.css)
        self.assertIn(".file-eco-cell", self.css)
        self.assertIn("openUploadedGenomeEcoPicker", click_handler)

    def test_verification_log_is_relocated_and_collapses_to_zero_height_when_empty(self) -> None:
        accession_start = self.index.index('id="brutal-accession-card"')
        accession_end = self.index.index("</section>", accession_start)
        upload_start = self.index.index('id="genome-upload-card"')
        acknowledgment = self.index.index('id="data-use-ack-panel"')
        feedback = self.index.index('class="submit-feedback-rail"')
        log = self.index.index('id="input-log-drawer"')
        upload_status = self.index.index('id="upload-status"', log)

        self.assertNotIn("input-log-drawer", self.index[accession_start:accession_end])
        self.assertLess(upload_start, acknowledgment)
        self.assertLess(acknowledgment, feedback)
        self.assertLess(feedback, log)
        self.assertLess(log, upload_status)
        self.assertRegex(
            self.index,
            r'<div class="input-log-drawer" id="input-log-drawer" hidden>',
        )
        self.assertRegex(
            self.index,
            r'<div class="data-use-ack" id="data-use-ack-panel"[^>]*hidden[^>]*inert',
        )

        renderer = function_source(self.js, "renderBrutalInputLog")
        result = run_node_json(
            """
const drawer = {hidden: false};
const list = {innerHTML: 'stale'};
const document = {
  getElementById(id) {
    if (id === 'input-log-drawer') return drawer;
    if (id === 'input-log-list') return list;
    return null;
  },
  querySelectorAll() { return []; },
};
const brutalInputNotices = new Map();
function brutalAccessionDraftIssues() { return []; }
function conciseInputNotice(value) { return String(value || '').trim(); }
function escapeHtml(value) { return String(value); }
"""
            + renderer
            + """
renderBrutalInputLog();
process.stdout.write(JSON.stringify({hidden: drawer.hidden, html: list.innerHTML}));
"""
        )
        self.assertTrue(result["hidden"])
        self.assertEqual(result["html"], "")


if __name__ == "__main__":
    unittest.main()
