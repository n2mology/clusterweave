from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = REPO_ROOT / "web" / "static"
ASSET_DIR = STATIC_DIR / "assets"
NODE = shutil.which("node")


def run_node_json(source: str) -> dict[str, object]:
    if NODE is None:
        raise unittest.SkipTest("Node.js is required for Pixel Lab core tests")
    result = subprocess.run(
        [NODE, "-e", textwrap.dedent(source)],
        cwd=REPO_ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            "Pixel Lab Node probe failed\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Pixel Lab Node probe returned invalid JSON: {result.stdout!r}") from exc


class PixelLabStaticContractTests(unittest.TestCase):
    def test_page_loads_game_dependencies_in_order(self) -> None:
        index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        assets = [
            "clusterweave-game-content.js",
            "clusterweave-game-core.js",
            "clusterweave-game.js",
            "clusterweave.js",
        ]
        positions = []
        for asset in assets:
            self.assertTrue((ASSET_DIR / asset).is_file(), asset)
            self.assertEqual(index.count(asset), 1, asset)
            positions.append(index.index(asset))
        self.assertEqual(positions, sorted(positions), "content and core must load before the controller")
        self.assertIn("clusterweave-game.css", index)

    def test_shell_is_one_continuous_jump_game_with_an_architecture_rail(self) -> None:
        index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        game_position = index.index('id="clusterweave-game"')
        workflow_position = index.index('id="workflow-progress-panel"')
        self.assertLess(game_position, workflow_position)

        for element_id in [
            "clusterweave-game-canvas",
            "clusterweave-game-start",
            "clusterweave-game-jump",
            "clusterweave-game-pause",
            "clusterweave-game-close",
            "clusterweave-game-architecture",
            "clusterweave-game-architecture-slots",
            "clusterweave-game-health",
            "clusterweave-game-status",
            "clusterweave-game-screen-reader-card",
        ]:
            self.assertEqual(index.count(f'id="{element_id}"'), 1, element_id)

        launcher_start = index.index('id="clusterweave-game-launcher"')
        launcher_end = index.index("</section>", launcher_start)
        launcher = index[launcher_start:launcher_end]
        self.assertEqual(len(re.findall(r"<button\b", launcher)), 1, "the launcher has one game action")
        self.assertIn('id="clusterweave-game-start"', launcher)

        launcher_button = re.search(
            r'<button\b[^>]*id="clusterweave-game-start"[^>]*>(.*?)</button>',
            launcher,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(launcher_button)
        launcher_label = re.sub(r"<[^>]+>", "", launcher_button.group(1)).strip()
        self.assertEqual(launcher_label, "", "the launcher is icon-only")
        self.assertIn('aria-label="Play"', launcher_button.group(0))

        for removed_chrome in [
            'class="clusterweave-game-head"',
            'id="clusterweave-game-guide"',
        ]:
            self.assertNotIn(removed_chrome, index, removed_chrome)
        self.assertNotIn(">Back to workflow<", index)

        for obsolete_id in [
            "clusterweave-game-assisted",
            "clusterweave-game-study",
            "clusterweave-game-mine",
            "clusterweave-game-note",
            "clusterweave-game-note-source",
            "clusterweave-game-study-panel",
            "clusterweave-game-gate",
            "clusterweave-game-level-select",
        ]:
            self.assertNotIn(f'id="{obsolete_id}"', index, obsolete_id)

        self.assertNotIn('data-game-mode=', index)
        self.assertIn('aria-describedby="clusterweave-game-instructions clusterweave-game-screen-reader-card"', index)
        self.assertIn('role="status" aria-live="polite"', index)
        self.assertIn('id="workflow-progress-panel" tabindex="-1"', index)
        self.assertIn('id="clusterweave-game-handoff" role="status" aria-live="assertive"', index)

        instructions_start = index.index('id="clusterweave-game-instructions"')
        instructions = index[instructions_start:index.index("</", instructions_start)].lower()
        self.assertIn("jump", instructions)
        self.assertTrue("space" in instructions or "arrow up" in instructions)

    def test_styles_preserve_wide_workflow_and_mobile_full_screen_play(self) -> None:
        css = (ASSET_DIR / "clusterweave-game.css").read_text(encoding="utf-8")
        for contract in [
            "grid-area: game",
            '"game game"',
            '"workflow results"',
            'data-clusterweave-game-view="fullscreen"',
            "position: fixed",
            "width: 100dvw",
            "height: 100dvh",
            "env(safe-area-inset-top)",
            "env(safe-area-inset-bottom)",
            "prefers-reduced-motion: reduce",
            "touch-action: none",
        ]:
            self.assertIn(contract, css)
        self.assertNotRegex(
            css,
            r"image-rendering:\s*(?:pixelated|crisp-edges)",
            "the game canvas must stay sharp instead of scaling a low-resolution pixel buffer",
        )
        controller = (ASSET_DIR / "clusterweave-game.js").read_text(encoding="utf-8")
        self.assertIn("devicePixelRatio", controller)
        self.assertIn("setTransform(", controller)
        self.assertNotIn("Space or tap starts a fresh run", controller)
        touch_target_heights = [int(value) for value in re.findall(r"min-height:\s*(\d+)px", css)]
        self.assertTrue(any(value >= 44 for value in touch_target_heights))
        self.assertRegex(css, r"\.clusterweave-game-architecture(?:\s|\{|,)")

    def test_launcher_is_a_transparent_outline_outputs_icon_and_gene_arrows_remain_minimal(self) -> None:
        index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        css = (ASSET_DIR / "clusterweave-game.css").read_text(encoding="utf-8")
        controller = (ASSET_DIR / "clusterweave-game.js").read_text(encoding="utf-8")

        heading_start = index.index('class="clusterweave-results-heading"')
        heading_end = index.index('id="results-empty-state"', heading_start)
        heading_markup = index[heading_start:heading_end]
        self.assertLess(heading_markup.index('id="results-title"'), heading_markup.index('id="clusterweave-game-start"'))

        launcher_button = re.search(
            r'<button\b(?=[^>]*\bid="clusterweave-game-start")([^>]*)>(.*?)</button>',
            heading_markup,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(launcher_button)
        launcher_attributes = launcher_button.group(1)
        self.assertIn('aria-label="Play"', launcher_attributes)
        self.assertNotIn('title=', launcher_attributes)
        self.assertEqual(re.sub(r"<[^>]+>", "", launcher_button.group(2)).strip(), "")
        self.assertNotIn("dom.start.textContent = 'Play'", controller)
        self.assertIn("dom.start.textContent = ''", controller)
        for removed_class in ["output", "result-bubble", "result-lollipop", "result-folder-tab"]:
            self.assertNotIn(removed_class, launcher_attributes)

        heading_rule = re.search(
            r"\.clusterweave-results-heading\s*\{(.*?)\}",
            css,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(heading_rule)
        self.assertRegex(heading_rule.group(1), r"display:\s*flex")
        self.assertRegex(heading_rule.group(1), r"justify-content:\s*space-between")

        launcher_rule = re.search(
            r"#clusterweave-game-start\s*\{(.*?)\}",
            css,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(launcher_rule)
        for contract in [
            r"width:\s*1\.75rem",
            r"height:\s*1\.75rem",
            r"min-height:\s*0",
            r"border:\s*3px\s+solid\s+var\(--line\)",
            r"border-radius:\s*50%",
            r"background:\s*transparent",
            r"font-size:\s*0",
        ]:
            self.assertRegex(launcher_rule.group(1), contract)
        icon_rule = re.search(
            r"#clusterweave-game-start::before\s*\{(.*?)\}",
            css,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(icon_rule)
        self.assertIn('content: ""', icon_rule.group(1))
        self.assertRegex(icon_rule.group(1), r"width:\s*\.56rem")
        self.assertRegex(icon_rule.group(1), r"height:\s*\.72rem")
        self.assertIn("clip-path: polygon(0 0, 100% 50%, 0 100%)", icon_rule.group(1))
        self.assertNotIn("margin-left", icon_rule.group(1))
        self.assertRegex(icon_rule.group(1), r"transform:\s*translateX\(\.075rem\)")
        launcher_styles = css[css.index(".clusterweave-results-heading"):css.index(".clusterweave-game {")]
        self.assertNotIn("var(--lavender)", launcher_styles)

        self.assertNotIn("clusterweave-game-architecture-head", index)
        for removed_header in [
            "ILLUSTRATIVE CANDIDATE",
            "ILLUSTRATIVE GENE ARCHITECTURE",
        ]:
            self.assertFalse(
                removed_header in controller,
                f"visible game header copy remains: {removed_header}",
            )

        architecture_rule = re.search(
            r"\.clusterweave-game-architecture\s*\{(.*?)\}",
            css,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(architecture_rule)
        self.assertRegex(architecture_rule.group(1), r"grid-template-areas:\s*[\"']slots[\"']")
        self.assertRegex(architecture_rule.group(1), r"justify-content:\s*center")

        render_start = controller.index("function renderArchitecture()")
        render_end = controller.index("\n  function updateHud()", render_start)
        render_architecture = controller[render_start:render_end]
        self.assertNotIn("slot.textContent", render_architecture)
        self.assertNotIn("slot.innerText", render_architecture)

        draw_start = controller.index("function drawGene(entity)")
        draw_end = controller.index("\n  function drawObstacle", draw_start)
        draw_gene = controller[draw_start:draw_end]
        self.assertIn("polygon(points", draw_gene)
        self.assertIn("const shoulder", draw_gene)
        self.assertIn("const blunt", draw_gene)
        self.assertNotIn("fillText(", draw_gene)

        rail_start = css.index(".clusterweave-game-gene-slot.is-filled::before")
        rail_end = css.index('.clusterweave-game-gene-slot[data-role="core"]', rail_start)
        rail_arrows = css[rail_start:rail_end]
        self.assertIn('content: ""', rail_arrows)
        self.assertGreaterEqual(rail_arrows.count("clip-path: polygon("), 4)
        self.assertIn('[data-strand="left"]', rail_arrows)
        self.assertRegex(controller, r"silhouette:\s*['\"]blocky-blunted-arrow['\"]")
        self.assertRegex(controller, r"labels:\s*false")

    def test_five_heart_meter_and_bacterial_backdrop_are_visual_only(self) -> None:
        index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        css = (ASSET_DIR / "clusterweave-game.css").read_text(encoding="utf-8")
        controller = (ASSET_DIR / "clusterweave-game.js").read_text(encoding="utf-8")
        core = (ASSET_DIR / "clusterweave-game-core.js").read_text(encoding="utf-8")
        content = (ASSET_DIR / "clusterweave-game-content.js").read_text(encoding="utf-8")

        meter = re.search(
            r'<div class="clusterweave-game-health"[^>]*id="clusterweave-game-health"[^>]*>.*?</div>',
            index,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(meter)
        meter_markup = meter.group(0)
        self.assertIn('role="meter"', meter_markup)
        self.assertIn('aria-valuemax="5"', meter_markup)
        self.assertIn('aria-valuenow="5"', meter_markup)
        self.assertEqual(meter_markup.count("data-health-heart"), 5)

        instructions_start = index.index('id="clusterweave-game-instructions"')
        instructions = index[instructions_start:index.index("</", instructions_start)].lower()
        self.assertIn("five hearts", instructions)
        self.assertIn("orange barriers cost one heart", instructions)
        self.assertIn("dnase", instructions)
        self.assertIn("immediately", instructions)

        health_rule = re.search(
            r"\.clusterweave-game-health\s*\{(.*?)\}",
            css,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(health_rule)
        for contract in [
            r"position:\s*absolute",
            r"left:\s*50%",
            r"border:\s*0",
            r"outline:\s*0",
            r"background:\s*transparent",
            r"box-shadow:\s*none",
            r"transform:\s*translateX\(-50%\)",
            r"pointer-events:\s*none",
        ]:
            self.assertRegex(health_rule.group(1), contract)

        game_bundle = "\n".join([content, core, controller])
        for token in [
            "function renderHealth(",
            "function triggerObstacleDamage(",
            "Core.damage(",
            "damageApplied",
            "function drawSpiralFlagellate(",
            "spiral-flagellated-bacterium",
            "decorativeOnly: true",
            "collisionEnabled: false",
            "colorRole: 'biology'",
        ]:
            self.assertIn(token, game_bundle)
        for removed_shield in [
            "shieldAvailable",
            "bufferUnlockArchitecture",
            "BUFFER READY",
            "absorbed",
        ]:
            self.assertNotIn(removed_shield, game_bundle)

        backdrop_start = controller.index("function drawBackdrop()")
        backdrop_end = controller.index("\n  function ", backdrop_start + 1)
        draw_backdrop = controller[backdrop_start:backdrop_end]
        bacteria_position = draw_backdrop.index("drawSpiralFlagellates(")
        fungus_position = draw_backdrop.index("drawHyphae(")
        mushroom_position = draw_backdrop.index("for (let x =", fungus_position)
        terrain_position = draw_backdrop.index("pixelRect(0, ground")
        self.assertLess(bacteria_position, fungus_position)
        self.assertLess(fungus_position, mushroom_position)
        self.assertLess(mushroom_position, terrain_position)

    def test_controller_smoothly_ramps_each_tier_and_matches_live_motion(self) -> None:
        controller = (ASSET_DIR / "clusterweave-game.js").read_text(encoding="utf-8")
        motion_start = controller.index("function motionScaleForPace(paceValue)")
        motion_end = controller.index("\n  function setRuntimePace", motion_start)
        motion_scale = controller[motion_start:motion_end]
        self.assertIn("pace / basePace", motion_scale)
        self.assertNotIn("preFinalPace", motion_scale)
        self.assertNotIn("engageFinalStagePace", controller)

        update_start = controller.index("function updateSimulation()")
        update_end = controller.index("\n  function ", update_start + 1)
        update_simulation = controller[update_start:update_end]
        self.assertIn("if (player.onGround)", update_simulation)
        self.assertIn("difficulty.pacePermille - runtime.currentPacePermille", update_simulation)
        self.assertIn("Content.constants.paceRampTicks", update_simulation)
        self.assertIn("Math.sign(paceDifference)", update_simulation)
        self.assertNotIn("difficulty.isFinalStage", update_simulation)

    def test_game_bundle_is_local_session_only_and_has_no_lecture_modes(self) -> None:
        game_files = [
            ASSET_DIR / "clusterweave-game-content.js",
            ASSET_DIR / "clusterweave-game-core.js",
            ASSET_DIR / "clusterweave-game.js",
        ]
        game_text = "\n".join(path.read_text(encoding="utf-8") for path in game_files)
        for forbidden in [
            "fetch(",
            "XMLHttpRequest",
            "WebSocket",
            "localStorage",
            "sessionStorage",
            "indexedDB",
            "AudioContext",
            "new Audio(",
            "sendBeacon(",
            "/api/",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, game_text)

        content = (ASSET_DIR / "clusterweave-game-content.js").read_text(encoding="utf-8")
        core = (ASSET_DIR / "clusterweave-game-core.js").read_text(encoding="utf-8")
        controller = (ASSET_DIR / "clusterweave-game.js").read_text(encoding="utf-8")
        for obsolete_symbol in [
            "content.levels",
            "content.lessons",
            "beginGate",
            "gateQualification",
            "startGateAttempt",
            "submitGateAction",
            "restartAfterFailure",
        ]:
            self.assertNotIn(obsolete_symbol, core)
        for obsolete_dom_hook in [
            "clusterweave-game-assisted",
            "clusterweave-game-study",
            "clusterweave-game-mine",
            "clusterweave-game-note-continue",
            "clusterweave-game-study-next",
        ]:
            self.assertNotIn(obsolete_dom_hook, controller)
        particles_start = controller.index("function addParticles(")
        particles_end = controller.index("\n  function ", particles_start + 1)
        particles_body = controller[particles_start:particles_end]
        self.assertIn("runtime.visualRng", particles_body)
        self.assertNotIn("runtime.run.rng", particles_body)
        self.assertNotRegex(content, r"\b(?:levels|lessons|gates)\s*:")
        self.assertIn("noUserJobData: true", game_text)

    def test_polling_handoffs_and_mobile_dna_suspension_remain_integrated(self) -> None:
        main = (ASSET_DIR / "clusterweave.js").read_text(encoding="utf-8")
        controller = (ASSET_DIR / "clusterweave-game.js").read_text(encoding="utf-8")
        dna = (ASSET_DIR / "workflow-dna-progress.js").read_text(encoding="utf-8")

        for token in [
            "const TRANSIENT_JOB_POLL",
            "JOB_POLL_TIMEOUT_MS",
            "AbortController",
            "function scheduleJobPoll(",
            "pollTimerId = null",
            "job === TRANSIENT_JOB_POLL",
            "clusterweaveGameEpoch",
            "CLUSTERWEAVE_GAME_PHASE_BY_STAGE",
            "controller.setHostState({",
            "if (lifecycle === 'complete') lifecycle = 'success'",
            "if (lifecycle === 'launched') lifecycle = 'pending'",
            "clusterweave:game-workflow-focus",
            "Results ready.",
        ]:
            self.assertIn(token, main)

        schedule_start = main.index("function scheduleJobPoll(")
        schedule_end = main.index("function stopPolling(", schedule_start)
        schedule_body = main[schedule_start:schedule_end]
        self.assertIn("scheduleJobPoll(", schedule_body[schedule_body.index("{") :])
        self.assertNotIn("setInterval(", schedule_body)

        self.assertIn("const JOB_POLL_TIMEOUT_MS = 12000;", main)
        self.assertIn("const JOB_INITIAL_LOAD_TIMEOUT_MS = 45000;", main)
        load_start = main.index("async function loadJob(")
        load_end = main.index("async function pollJobFinal(", load_start)
        load_body = main[load_start:load_end]
        self.assertIn(
            "pollJobFinal(jobId, autoScroll, seq, JOB_INITIAL_LOAD_TIMEOUT_MS)",
            load_body,
        )
        poll_start = load_end
        poll_end = main.index("function jobPollDelay(", poll_start)
        poll_body = main[poll_start:poll_end]
        self.assertIn("timeoutMs = JOB_POLL_TIMEOUT_MS", poll_body)
        self.assertIn("setTimeout(() => abortController.abort(), timeoutMs)", poll_body)
        self.assertNotIn("JOB_INITIAL_LOAD_TIMEOUT_MS", poll_body)
        self.assertIn("pollJobFinal(jobId, autoScroll, seq);", schedule_body)
        self.assertNotIn("JOB_INITIAL_LOAD_TIMEOUT_MS", schedule_body)

        self.assertIn("clusterweave:game-animation", controller)
        animation_start = controller.index("function dispatchAnimationOwnership(")
        animation_end = controller.index("\n  function ", animation_start + 1)
        animation_body = controller[animation_start:animation_end]
        self.assertIn("presentation.open", animation_body)
        self.assertIn("COMPACT_QUERY.matches", animation_body, "only mobile play may suspend workflow DNA")
        self.assertNotIn("presentation.fromBootstrap", animation_body)
        self.assertIn("clusterweave:game-animation", main)
        self.assertIn("bgcWorkflowDna.suspend?.()", main)
        self.assertIn("bgcWorkflowDna.resume?.()", main)
        self.assertIn("window.addEventListener('online'", main)
        status_start = main.index("async function fetchSystemStatus(")
        status_end = main.index("\nfunction updateBootstrapSteps(", status_start)
        status_body = main[status_start:status_end]
        connected = "window.ClusterWeaveGame?.setConnectionState?.('connected');"
        self.assertIn(connected, status_body)
        success_path = status_body[status_body.index("const payload = await resp.json();") :]
        self.assertLess(
            success_path.index(connected),
            success_path.index("if (!bootstrapComplete)"),
            "successful health responses must reconnect resident tabs after bootstrap",
        )
        self.assertIn("suspend()", dna)
        self.assertIn("resume()", dna)
        self.assertIn("this.suspended", dna)


class PixelLabCoreContractTests(unittest.TestCase):
    def test_content_validation_and_scientific_guardrails(self) -> None:
        report = run_node_json(
            """
            const content = require('./web/static/assets/clusterweave-game-content.js');
            const core = require('./web/static/assets/clusterweave-game-core.js');
            const roleEntries = Object.entries(content.roles || {});
            const roles = roleEntries.map(([, role]) => role);
            const roleIds = roleEntries.map(([roleId]) => roleId);
            const sources = Array.isArray(content.sources) ? content.sources : Object.values(content.sources || {});
            const frozenCollections = [
              content.roles,
              content.roleOrder,
              content.upgrades,
              content.palettes,
              content.phraseTemplates,
              content.sources,
              content.geometry,
              content.constants,
              content.guardrails,
            ].every(Object.isFrozen);
            const phraseKinds = [...new Set(content.phraseTemplates.flatMap((phrase) => (
              phrase.placements.map((placement) => placement.kind)
            )))].sort();
            const routeMetadataComplete = content.phraseTemplates.every((phrase) => (
              Number.isFinite(phrase.span) && phrase.span > 0
              && Number.isFinite(phrase.recoveryDistance) && phrase.recoveryDistance > 0
              && Array.isArray(phrase.jumpWindows)
              && phrase.jumpWindows.every((window) => window.start >= 0 && window.end > window.start)
            ));
            console.log(JSON.stringify({
              validation: core.validationReport,
              rootFrozen: Object.isFrozen(content),
              frozenCollections,
              roleCount: roles.length,
              roleIds,
              roleOrder: content.roleOrder,
              roleRecordsComplete: roles.every((role) => role.label && role.color && role.glyph && role.predicted),
              upgradeCount: content.upgrades.length,
              paletteCount: content.palettes.length,
              biologyColors: content.palettes.map((palette) => palette.biology),
              phraseTemplateCount: content.phraseTemplates.length,
              geometry: content.geometry,
              constants: content.constants,
              phraseKinds,
              routeMetadataComplete,
              guideText: (content.guide?.points || []).join(' ').toLowerCase(),
              sourcesAreHttps: sources.length > 0 && sources.every((source) => source.url.startsWith('https://')),
              guardrails: content.guardrails,
              legacyExportsAbsent: ['levels', 'lessons', 'gates', 'outcomes', 'pointBuckets']
                .every((key) => !(key in content)),
            }));
            """
        )
        validation = report["validation"]
        self.assertTrue(validation["valid"])
        self.assertTrue(validation["oneContinuousGame"])
        self.assertTrue(report["rootFrozen"])
        self.assertTrue(report["frozenCollections"])
        self.assertGreaterEqual(report["roleCount"], 6)
        self.assertEqual(len(report["roleOrder"]), report["roleCount"])
        self.assertEqual(set(report["roleOrder"]), set(report["roleIds"]))
        self.assertTrue(report["roleRecordsComplete"])
        self.assertGreaterEqual(report["upgradeCount"], 3)
        self.assertGreaterEqual(report["paletteCount"], 3)
        self.assertEqual(len(report["biologyColors"]), report["paletteCount"])
        self.assertTrue(all(report["biologyColors"]))
        self.assertTrue(set(report["biologyColors"]).isdisjoint({"#ff9a36", "#ff7a18"}))
        self.assertGreaterEqual(
            report["phraseTemplateCount"],
            10,
            "terrain phrases should stay varied over a long continuous run",
        )
        self.assertEqual(set(report["phraseKinds"]), {"gene", "obstacle", "pit", "platform", "warning"})
        self.assertTrue(report["routeMetadataComplete"])
        self.assertEqual(report["constants"]["maxHealth"], 5)
        self.assertGreater(report["constants"]["maxJumpDistance"], 0)
        self.assertGreater(report["constants"]["minimumLandingRun"], 0)
        geometry = report["geometry"]
        self.assertGreater(geometry["minimumJumpRise"], 0)
        self.assertTrue(all(
            shape["height"] <= geometry["minimumJumpRise"]
            for shape in geometry["obstacles"].values()
        ))
        self.assertTrue(all(
            offset < geometry["playerHeight"] + geometry["minimumJumpRise"]
            for offset in geometry["laneOffsets"].values()
        ))
        self.assertTrue(report["sourcesAreHttps"])
        self.assertTrue(report["legacyExportsAbsent"])
        self.assertIn("dnase", report["guideText"])
        self.assertIn("arcade metaphor", report["guideText"])
        self.assertIn("degradation", report["guideText"])
        self.assertIn("bacterial", report["guideText"])
        self.assertIn("decorative", report["guideText"])

        guardrails = report["guardrails"]
        for guardrail in [
            "architectureIsIllustrative",
            "rolesArePredicted",
            "pointsAreNotScientificEvidence",
            "equalRolePointValue",
            "biologyIsNeverAHazard",
            "genesAndOrganismsAreNeverHazards",
            "dnasePitsAreArcadeMetaphor",
            "microbialSceneryIsDecorative",
            "noUserJobData",
            "coLocationDoesNotProveCoTranscription",
            "candidateDoesNotProveProduct",
        ]:
            self.assertIs(guardrails[guardrail], True, guardrail)

    def test_seeded_play_is_reproducible_and_gene_ids_are_idempotent(self) -> None:
        report = run_node_json(
            """
            const content = require('./web/static/assets/clusterweave-game-content.js');
            const core = require('./web/static/assets/clusterweave-game-core.js');
            const draw = (seed) => {
              const rng = core.createSeededRng(seed);
              return Array.from({ length: 12 }, () => core.randomInt(rng, 100000));
            };

            const session = core.createSessionState({ seed: 'session-seed' });
            const run = core.createRun({ session, seed: 'run-seed' });
            core.startRun(run);
            const before = core.snapshot(run);
            const firstResult = core.collectGene(run, {
              id: 'gene-1', roleId: content.roleOrder[0], strand: 1,
            });
            const afterFirst = core.snapshot(run);
            const duplicateResult = core.collectGene(run, {
              id: 'gene-1', roleId: content.roleOrder[1], strand: -1,
            });
            const afterDuplicate = core.snapshot(run);
            core.collectGene(run, { id: 'gene-2', roleId: content.roleOrder[1], strand: -1 });
            const afterSecond = core.snapshot(run);
            console.log(JSON.stringify({
              sameA: draw('same-seed'),
              sameB: draw('same-seed'),
              different: draw('different-seed'),
              firstResult,
              duplicateResult,
              deltas: [
                afterFirst.score - before.score,
                afterDuplicate.score - afterFirst.score,
                afterSecond.score - afterDuplicate.score,
              ],
              geneCounts: [
                before.architecture.genes.length,
                afterFirst.architecture.genes.length,
                afterDuplicate.architecture.genes.length,
                afterSecond.architecture.genes.length,
              ],
              state: afterSecond.state,
            }));
            """
        )
        self.assertEqual(report["sameA"], report["sameB"])
        self.assertNotEqual(report["sameA"], report["different"])
        self.assertGreater(report["deltas"][0], 0)
        self.assertEqual(report["deltas"], [report["deltas"][0], 0, report["deltas"][0]])
        self.assertEqual(report["geneCounts"], [0, 1, 1, 2])
        self.assertEqual(report["state"], "playing")
        self.assertNotEqual(report["firstResult"], report["duplicateResult"])

    def test_six_equal_pickups_complete_architectures_without_a_gate(self) -> None:
        report = run_node_json(
            """
            const content = require('./web/static/assets/clusterweave-game-content.js');
            const core = require('./web/static/assets/clusterweave-game-core.js');
            const run = core.createRun({ seed: 'continuous-run' });
            core.startRun(run);
            const scoreDeltas = [];
            const basePoints = [];
            let prior = core.snapshot(run);
            for (let index = 0; index < 6; index += 1) {
              const result = core.collectGene(run, {
                id: `architecture-a-${index}`,
                roleId: content.roleOrder[index % content.roleOrder.length],
                strand: index % 2 ? -1 : 1,
              });
              basePoints.push(result.basePoints);
              const next = core.snapshot(run);
              scoreDeltas.push(next.score - prior.score);
              prior = next;
            }
            const firstComplete = core.snapshot(run);
            const firstUpgrade = core.currentUpgrade(run);
            for (let index = 0; index < 6; index += 1) {
              core.collectGene(run, {
                id: `architecture-b-${index}`,
                roleId: content.roleOrder[(index + 2) % content.roleOrder.length],
                strand: index % 2 ? 1 : -1,
              });
            }
            const secondComplete = core.snapshot(run);
            console.log(JSON.stringify({
              scoreDeltas,
              basePoints,
              firstComplete,
              secondComplete,
              firstUpgrade,
              secondUpgrade: core.currentUpgrade(run),
              hasLegacyProgression: ['levelIndex', 'gate', 'mode'].some((key) => key in secondComplete),
            }));
            """
        )
        pickup_value = report["scoreDeltas"][0]
        self.assertGreater(pickup_value, 0)
        self.assertEqual(report["basePoints"], [pickup_value] * 6)
        self.assertEqual(report["scoreDeltas"][:5], [pickup_value] * 5)
        self.assertGreater(report["scoreDeltas"][5], pickup_value, "the sixth pickup adds a fixed weave bonus")

        first = report["firstComplete"]
        second = report["secondComplete"]
        self.assertEqual(first["state"], "playing")
        self.assertEqual(first["completedArchitectures"], 1)
        self.assertEqual(first["tier"], 2)
        self.assertEqual(first["architecture"]["genes"], [])
        self.assertEqual(first["architecture"]["required"], 6)
        self.assertEqual(first["architecture"]["completed"], 0)
        self.assertEqual(second["state"], "playing")
        self.assertEqual(second["completedArchitectures"], 2)
        self.assertEqual(second["tier"], 3)
        self.assertEqual(second["architecture"]["genes"], [])
        self.assertGreater(second["score"], first["score"])
        self.assertGreaterEqual(second["lastArchitecture"]["bonus"], first["lastArchitecture"]["bonus"])
        self.assertFalse(report["hasLegacyProgression"])
        self.assertIn("id", report["firstUpgrade"])
        self.assertIn("id", report["secondUpgrade"])

    def test_run_states_pause_ticks_and_resume_without_a_learning_stop(self) -> None:
        report = run_node_json(
            """
            const core = require('./web/static/assets/clusterweave-game-core.js');
            const tick = (run) => {
              const view = core.snapshot(run);
              return view.ticks ?? view.elapsedTicks;
            };
            const run = core.createRun({ seed: 321 });
            const states = [core.snapshot(run).state];
            core.startRun(run);
            states.push(core.snapshot(run).state);
            const startTick = tick(run);
            core.advanceTicks(run, 24);
            const playingTick = tick(run);
            core.pauseRun(run);
            states.push(core.snapshot(run).state);
            core.advanceTicks(run, 24);
            const pausedTick = tick(run);
            core.resumeRun(run);
            states.push(core.snapshot(run).state);
            core.advanceTicks(run, 6);
            const resumedTick = tick(run);
            console.log(JSON.stringify({ states, startTick, playingTick, pausedTick, resumedTick }));
            """
        )
        self.assertEqual(report["states"], ["ready", "playing", "paused", "playing"])
        self.assertGreater(report["playingTick"], report["startTick"])
        self.assertEqual(report["pausedTick"], report["playingTick"])
        self.assertGreater(report["resumedTick"], report["pausedTick"])

    def test_seven_tier_pace_ladder_reaches_three_times_speed_with_matched_motion(self) -> None:
        report = run_node_json(
            """
            const content = require('./web/static/assets/clusterweave-game-content.js');
            const core = require('./web/static/assets/clusterweave-game-core.js');
            const tiers = [1, 2, 3, 4, 5, 6, 7, 8, 16, 64, 1024];
            const curves = tiers.map((tier) => core.difficultyForTier(tier));
            const pick = (record, names, matcher) => {
              for (const name of names) {
                if (Number.isFinite(record[name])) return record[name];
              }
              const entry = Object.entries(record).find(([key, value]) => Number.isFinite(value) && matcher.test(key));
              return entry ? entry[1] : null;
            };
            const speed = curves.map((item) => pick(
              item,
              ['pacePermille', 'speedPermille', 'speedMultiplier', 'speed'],
              /(?:speed|pace)/i,
            ));
            const reaction = curves.map((item) => pick(
              item,
              ['reactionTicks', 'minimumReactionTicks', 'reactionWindowTicks'],
              /reaction/i,
            ));
            const floorEntry = Object.entries(content.constants).find(([key, value]) => (
              Number.isFinite(value)
              && (/(?:reaction.*(?:floor|min)|min.*reaction)/i).test(key)
            ));
            console.log(JSON.stringify({
              tiers,
              curves,
              speed,
              reaction,
              reactionFloor: floorEntry?.[1] ?? null,
              baseSpeed: content.constants.baseSpeed,
              basePace: content.constants.basePacePermille,
              paceCap: content.constants.paceCapPermille,
              paceRungs: content.constants.paceRungsPermille,
              hasUniformPaceStep: Object.prototype.hasOwnProperty.call(content.constants, 'paceStepPermille'),
              finalStageTier: content.constants.finalStageTier,
              finalMotionScale: content.constants.finalStageMotionScalePermille,
              paceRampTicks: content.constants.paceRampTicks,
            }));
            """
        )
        speed = report["speed"]
        reaction = report["reaction"]
        reaction_floor = report["reactionFloor"]
        curves = report["curves"]
        tiers = report["tiers"]
        ladder = [1000, 1500, 1750, 2000, 2500, 2750, 3000]
        self.assertTrue(all(value is not None for value in speed))
        self.assertTrue(all(value is not None for value in reaction))
        self.assertIsNotNone(reaction_floor, "content constants must publish the reaction-time floor")
        self.assertEqual(report["finalStageTier"], 7)
        self.assertEqual(report["paceRungs"], ladder)
        self.assertFalse(report["hasUniformPaceStep"])
        self.assertGreater(report["paceRampTicks"], 1)
        self.assertEqual(speed[:7], ladder)
        self.assertEqual(
            [right - left for left, right in zip(speed[:6], speed[1:7])],
            [500, 250, 250, 500, 250, 250],
        )
        final_stage_index = tiers.index(7)
        self.assertEqual(speed[final_stage_index], report["basePace"] * 3)
        self.assertTrue(
            all(value == speed[final_stage_index] for value in speed[final_stage_index:]),
            "tier seven and later must stay at the finite three-times cap",
        )
        self.assertEqual(speed[-1], report["paceCap"])
        self.assertEqual(report["paceCap"], report["basePace"] * 3)
        self.assertEqual(report["finalMotionScale"], 3000)
        self.assertEqual(curves[final_stage_index]["speed"], report["baseSpeed"] * 3)
        for index, curve in enumerate(curves[:7]):
            with self.subTest(tier=tiers[index]):
                expected_motion = round(speed[index] * 1000 / report["basePace"])
                self.assertEqual(curve["motionScalePermille"], expected_motion)
                self.assertAlmostEqual(curve["jumpRise"], curves[0]["jumpRise"])
                self.assertAlmostEqual(curve["jumpDistance"], curves[0]["jumpDistance"])
        self.assertTrue(all(left > right for left, right in zip(
            [curve["airtimeSeconds"] for curve in curves[:6]],
            [curve["airtimeSeconds"] for curve in curves[1:7]],
        )))
        self.assertTrue(all(value >= reaction_floor for value in reaction))
        self.assertEqual(reaction[-1], reaction_floor)

    def test_phrase_routes_are_seeded_varied_and_geometrically_survivable(self) -> None:
        report = run_node_json(
            """
            const content = require('./web/static/assets/clusterweave-game-content.js');
            const core = require('./web/static/assets/clusterweave-game-core.js');
            const placementWidth = (placement) => {
              if (placement.kind === 'pit') {
                return Number(placement.width)
                  || Number(content.geometry.pits?.[placement.shape]?.width) || 0;
              }
              if (placement.kind === 'obstacle') {
                return Number(content.geometry.obstacles?.[placement.shape]?.width) || 0;
              }
              if (placement.kind === 'platform') {
                return Number(placement.width)
                  || Number(content.geometry.platforms?.[placement.shape]?.width) || 0;
              }
              return 0;
            };
            const auditRoute = (phrase) => {
              const windows = [...phrase.jumpWindows].sort((left, right) => left.start - right.start);
              const hazards = phrase.placements.filter((placement) => (
                placement.kind === 'pit' || placement.kind === 'obstacle'
              ));
              const placementEnds = phrase.placements.map((placement) => (
                placement.at + Math.max(0, placementWidth(placement))
              ));
              return {
                id: phrase.templateId || phrase.id,
                safe: core.isPhraseSurvivable(phrase),
                metadata: Number.isFinite(phrase.span) && phrase.span > 0
                  && Number.isFinite(phrase.recoveryDistance)
                  && phrase.recoveryDistance >= content.constants.minimumLandingRun,
                windowBounds: windows.every((window) => (
                  window.start >= 0
                  && window.end <= phrase.span
                  && window.end > window.start
                  && window.end - window.start <= content.constants.maxJumpDistance
                )),
                landingRuns: windows.every((window, index) => (
                  index === 0
                  || window.start - windows[index - 1].end >= content.constants.minimumLandingRun
                )),
                hazardsCovered: hazards.every((placement) => {
                  const start = placement.at;
                  const end = start + placementWidth(placement);
                  return end > start && windows.some((window) => (
                    window.start <= start && window.end >= end
                  ));
                }),
                placementsWithinSpan: placementEnds.every((end) => end <= phrase.span),
              };
            };
            const generate = (seed) => {
              const run = core.createRun({ seed });
              core.startRun(run);
              run.tier = 64;
              return Array.from({ length: 72 }, () => core.generatePhrase(run));
            };
            const maxRepeat = (phrases) => phrases.reduce((state, phrase) => {
              const repeats = phrase.templateId === state.last ? state.repeats + 1 : 1;
              return { last: phrase.templateId, repeats, max: Math.max(state.max, repeats) };
            }, { last: '', repeats: 0, max: 0 }).max;
            const forceRun = core.createRun({ seed: 'force-every-template' });
            core.startRun(forceRun);
            forceRun.tier = 64;
            const forced = content.phraseTemplates.map((template) => (
              core.generatePhrase(forceRun, { templateId: template.id })
            ));
            const generatedA = generate('phrase-seed');
            const generatedB = generate('phrase-seed');
            const generatedC = generate('other-phrase-seed');
            console.log(JSON.stringify({
              generatedA,
              generatedB,
              generatedC,
              templateRoutes: content.phraseTemplates.map(auditRoute),
              forcedRoutes: forced.map(auditRoute),
              uniqueTemplates: new Set(generatedA.map((phrase) => phrase.templateId)).size,
              maxRepeat: maxRepeat(generatedA),
            }));
            """
        )
        self.assertEqual(report["generatedA"], report["generatedB"])
        self.assertNotEqual(report["generatedA"], report["generatedC"])
        self.assertGreaterEqual(report["uniqueTemplates"], 6)
        self.assertLessEqual(report["maxRepeat"], 2)
        for route_group in [report["templateRoutes"], report["forcedRoutes"]]:
            for route in route_group:
                with self.subTest(route=route["id"]):
                    self.assertTrue(route["safe"])
                    self.assertTrue(route["metadata"])
                    self.assertTrue(route["windowBounds"])
                    self.assertTrue(route["landingRuns"])
                    self.assertTrue(route["hazardsCovered"])
                    self.assertTrue(route["placementsWithinSpan"])

    def test_each_milestone_spawns_one_boundary_then_a_respite(self) -> None:
        report = run_node_json(
            """
            const content = require('./web/static/assets/clusterweave-game-content.js');
            const core = require('./web/static/assets/clusterweave-game-core.js');
            const run = core.createRun({ seed: 'boundary-sequence' });
            core.startRun(run);
            const addArchitecture = (serial) => {
              for (let index = 0; index < content.constants.genesPerArchitecture; index += 1) {
                core.collectGene(run, {
                  id: `boundary-${serial}-${index}`,
                  roleId: content.roleOrder[index % content.roleOrder.length],
                  strand: index % 2 ? -1 : 1,
                });
              }
            };
            for (let serial = 0; serial < content.constants.boundaryEveryArchitectures; serial += 1) {
              addArchitecture(serial);
            }
            const pending = core.snapshot(run);
            const first = core.generatePhrase(run);
            const afterBoundary = core.snapshot(run);
            const second = core.generatePhrase(run);
            const afterRespite = core.snapshot(run);
            const third = core.generatePhrase(run);
            const final = core.snapshot(run);
            console.log(JSON.stringify({ pending, first, afterBoundary, second, afterRespite, third, final }));
            """
        )
        self.assertTrue(report["pending"]["boundaryPending"])
        self.assertTrue(report["first"]["boundary"])
        self.assertFalse(report["afterBoundary"]["boundaryPending"])
        self.assertEqual(report["afterBoundary"]["respitePhrasesRemaining"], 1)
        self.assertTrue(report["second"]["respite"])
        self.assertFalse(report["second"]["boundary"])
        self.assertEqual(report["afterRespite"]["respitePhrasesRemaining"], 0)
        self.assertFalse(report["third"]["boundary"])
        self.assertLessEqual(report["final"]["consecutiveTemplateRepeats"], 2)
        self.assertEqual(report["final"]["lastTemplateId"], report["third"]["templateId"])

    def test_five_damage_hits_dnase_fatality_and_restart_keep_session_best(self) -> None:
        report = run_node_json(
            """
            const content = require('./web/static/assets/clusterweave-game-content.js');
            const core = require('./web/static/assets/clusterweave-game-core.js');
            const addArchitecture = (run, serial) => {
              for (let index = 0; index < content.constants.genesPerArchitecture; index += 1) {
                core.collectGene(run, {
                  id: `health-${serial}-${index}`,
                  roleId: content.roleOrder[index % content.roleOrder.length],
                  strand: index % 2 ? -1 : 1,
                });
              }
            };

            const session = core.createSessionState({ seed: 'health-session' });
            const run = core.createRun({ session, seed: 'health-run' });
            core.startRun(run);
            for (let architecture = 0; architecture < 3; architecture += 1) {
              addArchitecture(run, architecture);
            }
            const beforeDamage = core.snapshot(run);
            const hits = [];
            const states = [];
            for (let hit = 0; hit < content.constants.maxHealth; hit += 1) {
              hits.push(core.damage(run, 'orange-obstacle'));
              states.push(core.snapshot(run));
            }
            const afterTerminal = core.damage(run, 'orange-obstacle');

            const pitRun = core.createRun({ seed: 'pit-run' });
            core.startRun(pitRun);
            const prePitDamage = core.damage(pitRun, 'orange-obstacle');
            const beforePit = core.snapshot(pitRun);
            const pitCrash = core.crash(pitRun, 'dnase-pit');
            const afterPit = core.snapshot(pitRun);
            const afterPitDamage = core.damage(pitRun, 'orange-obstacle');

            const restarted = core.restartRun(run, { seed: 'restart-seed' }) || run;
            const afterRestart = core.snapshot(restarted);
            console.log(JSON.stringify({
              beforeDamage,
              hits,
              states,
              afterTerminal,
              prePitDamage,
              beforePit,
              pitCrash,
              afterPit,
              afterPitDamage,
              afterRestart,
            }));
            """
        )
        before = report["beforeDamage"]
        self.assertEqual(before["health"], 5)
        self.assertEqual(before["maxHealth"], 5)
        self.assertEqual(before["upgrade"]["id"], "buffer_pack")

        hits = report["hits"]
        states = report["states"]
        self.assertEqual([hit["health"] for hit in hits], [4, 3, 2, 1, 0])
        self.assertTrue(all(hit["damaged"] and hit["healthLost"] == 1 for hit in hits))
        self.assertEqual([state["state"] for state in states], ["playing"] * 4 + ["game_over"])
        self.assertEqual([state["health"] for state in states], [4, 3, 2, 1, 0])
        self.assertEqual(states[-1]["lastFailureReason"], "orange-obstacle")
        self.assertFalse(report["afterTerminal"]["damaged"])
        self.assertEqual(report["afterTerminal"]["reason"], "not-playing")

        self.assertEqual(report["prePitDamage"]["health"], 4)
        self.assertEqual(report["beforePit"]["health"], 4)
        self.assertTrue(report["pitCrash"]["crashed"])
        self.assertTrue(report["pitCrash"]["fatal"])
        self.assertEqual(report["afterPit"]["health"], 0)
        self.assertEqual(report["afterPit"]["state"], "game_over")
        self.assertEqual(report["afterPit"]["lastFailureReason"], "dnase-pit")
        self.assertFalse(report["afterPitDamage"]["damaged"])

        restarted = report["afterRestart"]
        self.assertEqual(restarted["state"], "playing")
        self.assertEqual(restarted["health"], 5)
        self.assertEqual(restarted["maxHealth"], 5)
        self.assertEqual(restarted["score"], 0)
        self.assertEqual(restarted["tier"], 1)
        self.assertEqual(restarted["completedArchitectures"], 0)
        self.assertEqual(restarted["architecture"]["genes"], [])
        self.assertGreaterEqual(restarted["best"]["score"], before["score"])


if __name__ == "__main__":
    unittest.main()
