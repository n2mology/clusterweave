(function attachClusterWeaveGameCore(root, factory) {
  const content = root?.ClusterWeaveGameContent
    || (typeof module === 'object' && module.exports ? require('./clusterweave-game-content.js') : null);
  const api = factory(content);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ClusterWeaveGameCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function createClusterWeaveGameCore(content) {
  'use strict';

  if (!content) throw new Error('ClusterWeave game content must load before the core');

  const RUN_STATES = new Set(['ready', 'playing', 'paused', 'game_over']);

  function assert(condition, message) {
    if (!condition) throw new Error(`Invalid ClusterWeave game content: ${message}`);
  }

  function normalizeSeed(seed) {
    if (Number.isFinite(Number(seed))) {
      const numeric = Number(seed) >>> 0;
      return numeric || 0x6d2b79f5;
    }
    const text = String(seed || 'clusterweave-candidate-weave');
    let hash = 2166136261;
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0) || 0x6d2b79f5;
  }

  function createSeededRng(seed) {
    const normalized = normalizeSeed(seed);
    return { seed: normalized, state: normalized, draws: 0 };
  }

  function nextRandomUint(rng) {
    let value = (rng?.state >>> 0) || 0x6d2b79f5;
    value ^= value << 13;
    value ^= value >>> 17;
    value ^= value << 5;
    rng.state = value >>> 0;
    rng.draws = (rng.draws || 0) + 1;
    return rng.state;
  }

  function randomInt(rng, exclusiveMax) {
    const max = Math.max(1, Math.floor(Number(exclusiveMax) || 1));
    return nextRandomUint(rng) % max;
  }

  const PLACEMENT_KINDS = new Set(['gene', 'obstacle', 'warning', 'pit', 'platform']);
  const HAZARD_KINDS = new Set(['obstacle', 'pit']);

  function dimensionsForPlacement(placement, value = content) {
    if (placement.kind === 'obstacle') {
      return value.geometry?.obstacles?.[placement.shape || 'pylon'] || null;
    }
    if (placement.kind === 'pit') {
      const shape = value.geometry?.pits?.[placement.shape || 'hop'];
      if (!shape) return null;
      return { width: Number(placement.width) || shape.width, height: 0 };
    }
    if (placement.kind === 'platform') {
      const shape = value.geometry?.platforms?.[placement.shape || 'step'];
      if (!shape) return null;
      return {
        width: Number(placement.width) || shape.width,
        height: Number(placement.height) || shape.height,
      };
    }
    return { width: 0, height: 0 };
  }

  function phraseSurvivalIssue(phrase, value = content) {
    const constants = value.constants || {};
    const geometry = value.geometry || {};
    if (!phrase || !phrase.id || !phrase.safeRoute) return 'a phrase is missing its id or safe route';
    if (!Number.isFinite(phrase.span) || phrase.span <= 0) return phrase.id + ' has no positive span';
    if (!Number.isFinite(phrase.recoveryDistance)) return phrase.id + ' has no recovery distance';
    const requiredRecovery = phrase.boundary
      ? constants.boundaryRecoveryDistance
      : constants.minimumRecoveryDistance;
    if (phrase.recoveryDistance < requiredRecovery) return phrase.id + ' has too little recovery distance';
    if (phrase.telegraphTicks < constants.minReactionTicks) return phrase.id + ' violates the reaction floor';
    if (!Array.isArray(phrase.jumpWindows)) return phrase.id + ' has no jump-window declaration';
    if (!Array.isArray(phrase.placements) || !phrase.placements.length) return phrase.id + ' has no placements';
    if (!phrase.placements.some((placement) => placement.kind === 'gene')) {
      return phrase.id + ' needs a collectible gene region';
    }

    let previousEnd = null;
    for (const window of phrase.jumpWindows) {
      if (
        !window
        || !Number.isFinite(window.start)
        || !Number.isFinite(window.end)
        || window.start < 0
        || window.end <= window.start
        || window.end > phrase.span
      ) return phrase.id + ' has an invalid jump window';
      if (window.end - window.start > constants.maxJumpDistance) {
        return phrase.id + ' exceeds the maximum authored jump distance';
      }
      if (previousEnd !== null && window.start - previousEnd < constants.minimumLandingRun) {
        return phrase.id + ' has no grounded recovery between jumps';
      }
      previousEnd = window.end;
    }

    const hazards = [];
    for (const placement of phrase.placements) {
      if (!PLACEMENT_KINDS.has(placement.kind)) return phrase.id + ' has an unsupported placement';
      if (!Number.isFinite(placement.at) || placement.at < 0 || placement.at > phrase.span) {
        return phrase.id + ' has a placement outside its span';
      }
      const dimensions = dimensionsForPlacement(placement, value);
      if (!dimensions) return phrase.id + ' has an unknown ' + placement.kind + ' shape';
      const placementEnd = placement.at + Math.max(0, dimensions.width || 0);
      if (placementEnd > phrase.span) return phrase.id + ' has geometry outside its span';

      if (placement.kind === 'gene') {
        const laneOffset = geometry.laneOffsets?.[placement.lane];
        if (
          placement.hazard === true
          || !Number.isFinite(laneOffset)
          || laneOffset >= geometry.playerHeight + geometry.minimumJumpRise
        ) return phrase.id + ' has an unreachable or hazardous gene region';
      }
      if (
        placement.kind === 'obstacle'
        && (!dimensions.height || dimensions.height > geometry.minimumJumpRise)
      ) return phrase.id + ' has an unclearable obstacle';
      if (
        placement.kind === 'pit'
        && (!dimensions.width || dimensions.width > geometry.maximumPitWidth)
      ) return phrase.id + ' has an unclearable DNase pit';
      if (
        placement.kind === 'platform'
        && (
          !dimensions.width
          || !dimensions.height
          || dimensions.height > geometry.maximumPlatformHeight
        )
      ) return phrase.id + ' has an unsupported platform';

      if (HAZARD_KINDS.has(placement.kind)) {
        hazards.push({ start: placement.at, end: placementEnd });
      }
    }

    if (phrase.respite && hazards.length) return phrase.id + ' marks a hazardous phrase as respite';
    if (phrase.boundary && !hazards.length) return phrase.id + ' boundary has no terrain challenge';
    for (const hazard of hazards) {
      const covered = phrase.jumpWindows.some((window) => (
        window.start <= hazard.start && window.end >= hazard.end
      ));
      if (!covered) return phrase.id + ' has a hazard outside every declared jump window';
    }
    return '';
  }

  function validateContent(value = content) {
    assert(value && typeof value === 'object', 'top-level content is missing');
    assert(Object.isFrozen(value), 'top-level content must be frozen');
    assert(value.version === '20260714-runner6', 'unexpected content version');

    const roleIds = Object.keys(value.roles || {});
    assert(roleIds.length >= 5, 'at least five predicted-role buckets are required');
    assert(Array.isArray(value.roleOrder), 'role order is missing');
    assert(value.roleOrder.length === roleIds.length, 'role order must contain every role exactly once');
    assert(new Set(value.roleOrder).size === value.roleOrder.length, 'role order contains duplicates');
    value.roleOrder.forEach((roleId) => {
      const role = value.roles[roleId];
      assert(role, 'unknown role ' + roleId);
      assert(role.predicted === true, roleId + ' must remain explicitly predicted');
      assert(role.label && role.color && role.glyph, roleId + ' needs label, color, and non-color glyph');
    });

    assert(Array.isArray(value.upgrades) && value.upgrades.length >= 3, 'progressive field-kit upgrades are missing');
    let previousThreshold = -1;
    value.upgrades.forEach((upgrade) => {
      assert(upgrade.threshold > previousThreshold, 'upgrade thresholds must be strictly increasing');
      previousThreshold = upgrade.threshold;
    });
    assert(value.upgrades[0].threshold === 0, 'base field kit must unlock at zero architectures');

    const constants = value.constants || {};
    const expectedPaceRungsPermille = [1000, 1500, 1750, 2000, 2500, 2750, 3000];
    assert(Array.isArray(constants.paceRungsPermille), 'pace rungs are missing');
    assert(
      constants.paceRungsPermille.length === expectedPaceRungsPermille.length
        && constants.paceRungsPermille.every((pace, index) => (
          pace === expectedPaceRungsPermille[index]
        )),
      'pace rungs must match the seven-stage progression',
    );
    assert(constants.ticksPerSecond > 0, 'simulation tick rate is missing');
    assert(constants.maxHealth === 5, 'runs must start with exactly five health hearts');
    assert(constants.genesPerArchitecture >= 4, 'architecture needs multiple gene regions');
    assert(constants.genePoints > 0, 'gene regions need a positive arcade value');
    assert(constants.baseSpeed > 0, 'fixed world speed is missing');
    assert(constants.jumpVelocity < 0, 'jump velocity must launch upward');
    assert(constants.gravity > 0 && constants.terminalVelocity > 0, 'fixed gravity is missing');
    assert(constants.coyoteTicks > 0 && constants.jumpBufferTicks > 0, 'forgiving input windows are missing');
    assert(constants.paceCapPermille >= constants.basePacePermille, 'pace cap is below base pace');
    assert(
      Number.isInteger(constants.finalStageTier) && constants.finalStageTier >= 2,
      'final-stage tier is missing',
    );
    assert(
      value.palettes?.[value.palettes.length - 1]?.id === 'deep-weave',
      'the final palette must remain deep-weave',
    );
    const orangeColors = new Set(['#ff7a18', '#ff9a36']);
    assert(value.palettes.every((palette) => (
      typeof palette.biology === 'string'
      && /^#[0-9a-f]{6}$/i.test(palette.biology)
      && !orangeColors.has(palette.biology.toLowerCase())
    )), 'every palette needs a non-orange biology color');
    assert(
      constants.finalStageTier === constants.paceRungsPermille.length,
      'every pace rung must map to exactly one stage',
    );
    assert(
      constants.basePacePermille === constants.paceRungsPermille[0],
      'the first pace rung must match the base pace',
    );
    assert(
      constants.finalStagePacePermille
        === constants.paceRungsPermille[constants.paceRungsPermille.length - 1],
      'the last pace rung must match the final-stage pace',
    );
    assert(
      constants.paceCapPermille === constants.finalStagePacePermille,
      'pace cap must match the final-stage pace',
    );
    assert(
      constants.finalStageMotionScalePermille
        === constants.finalStagePacePermille * 1000 / constants.basePacePermille,
      'final-stage motion scale must match the final-stage pace',
    );
    assert(constants.minSpawnGapTicks > 0, 'spawn-gap compatibility floor is missing');
    assert(constants.minReactionTicks >= constants.ticksPerSecond, 'reaction floor must be at least one second');
    assert(constants.minimumLandingRun > 0, 'grounded recovery distance is missing');
    assert(constants.maxJumpDistance > constants.minimumLandingRun, 'jump distance budget is invalid');

    const geometry = value.geometry || {};
    assert(geometry.playerWidth > 0 && geometry.playerHeight > 0, 'player geometry is missing');
    assert(geometry.playerVisualWidth >= geometry.playerWidth, 'visual scout must cover its forgiving collider');
    assert(geometry.playerVisualHeight >= geometry.playerHeight, 'visual scout must cover its forgiving collider');
    assert(geometry.geneHeight > 0 && geometry.minimumJumpRise > 0, 'gene and jump geometry are missing');
    const physicalJumpRise = (constants.jumpVelocity * constants.jumpVelocity) / (2 * constants.gravity);
    assert(physicalJumpRise >= geometry.minimumJumpRise, 'fixed jump cannot clear the authored terrain');
    assert(Object.values(geometry.obstacles || {}).every((shape) => (
      shape.width > 0 && shape.height > 0 && shape.height <= geometry.minimumJumpRise
    )), 'an obstacle is taller than the supported jump');
    assert(Object.values(geometry.pits || {}).every((shape) => (
      shape.width > 0 && shape.width <= geometry.maximumPitWidth
    )), 'a DNase pit is wider than the supported jump');
    assert(Object.values(geometry.platforms || {}).every((shape) => (
      shape.width > 0 && shape.height > 0 && shape.height <= geometry.maximumPlatformHeight
    )), 'a platform exceeds the supported terrain envelope');
    assert(Object.values(geometry.laneOffsets || {}).every((offset) => (
      offset < geometry.playerHeight + geometry.minimumJumpRise
    )), 'a gene lane is outside the supported jump envelope');

    assert(Array.isArray(value.phraseTemplates) && value.phraseTemplates.length >= 8, 'terrain phrase templates are missing');
    assert(new Set(value.phraseTemplates.map((phrase) => phrase.id)).size === value.phraseTemplates.length, 'phrase ids must be unique');
    value.phraseTemplates.forEach((phrase) => {
      assert(Number.isInteger(phrase.minTier) && phrase.minTier >= 1, phrase.id + ' has no minimum tier');
      assert(typeof phrase.boundary === 'boolean' && typeof phrase.respite === 'boolean', phrase.id + ' needs progression flags');
      const issue = phraseSurvivalIssue(phrase, value);
      assert(!issue, issue);
    });
    assert(value.phraseTemplates.some((phrase) => phrase.respite), 'a recovery phrase is required');
    assert(value.phraseTemplates.some((phrase) => phrase.boundary), 'a boundary phrase is required');
    assert(value.phraseTemplates.some((phrase) => phrase.placements.some((item) => item.kind === 'pit')), 'DNase terrain is missing');
    assert(value.phraseTemplates.some((phrase) => phrase.placements.some((item) => item.kind === 'platform')), 'platform terrain is missing');

    const guardrails = value.guardrails || {};
    [
      'architectureIsIllustrative',
      'rolesArePredicted',
      'coLocationDoesNotProveCoTranscription',
      'candidateDoesNotProveProduct',
      'pointsAreNotScientificEvidence',
      'equalRolePointValue',
      'biologyIsNeverAHazard',
      'genesAndOrganismsAreNeverHazards',
      'dnasePitsAreArcadeMetaphor',
      'microbialSceneryIsDecorative',
      'noUserJobData',
    ].forEach((key) => assert(guardrails[key] === true, 'guardrail ' + key + ' must remain enabled'));

    return Object.freeze({
      valid: true,
      releaseReady: value.guide?.reviewStatus === 'reviewed',
      version: value.version,
      roleCount: roleIds.length,
      phraseCount: value.phraseTemplates.length,
      oneContinuousGame: true,
      routeValidated: true,
      scientificReviewStatus: value.guide?.reviewStatus || 'unspecified',
      guardrails: { ...guardrails },
    });
  }

  const validationReport = validateContent(content);

  function createSessionState(options = {}) {
    return {
      seedBase: normalizeSeed(options.seed || 'clusterweave-resident-tab'),
      runOrdinal: 0,
      bestScore: Math.max(0, Math.floor(Number(options.bestScore) || 0)),
      bestDistance: Math.max(0, Math.floor(Number(options.bestDistance) || 0)),
      bestArchitectures: Math.max(0, Math.floor(Number(options.bestArchitectures) || 0)),
    };
  }

  function difficultyForTier(tierValue) {
    const tier = Math.max(1, Math.floor(Number(tierValue) || 1));
    const steps = tier - 1;
    const isFinalStage = tier >= content.constants.finalStageTier;
    const pacePermille = content.constants.paceRungsPermille[
      Math.min(steps, content.constants.paceRungsPermille.length - 1)
    ];
    const motionScalePermille = Math.round(
      pacePermille * 1000 / content.constants.basePacePermille,
    );
    const motionScale = motionScalePermille / 1000;
    const speed = content.constants.baseSpeed * pacePermille / 1000;
    const jumpVelocity = content.constants.jumpVelocity * motionScale;
    const gravity = content.constants.gravity * motionScale * motionScale;
    const terminalVelocity = content.constants.terminalVelocity * motionScale;
    const jumpRise = (jumpVelocity * jumpVelocity) / (2 * gravity);
    const airtimeSeconds = Math.abs(jumpVelocity) * 2 / gravity;
    return Object.freeze({
      tier,
      isFinalStage,
      pacePermille,
      speed,
      motionScalePermille,
      jumpVelocity,
      gravity,
      terminalVelocity,
      jumpRise,
      airtimeSeconds,
      jumpDistance: speed * airtimeSeconds,
      spawnGapTicks: Math.max(
        content.constants.minSpawnGapTicks,
        content.constants.baseSpawnGapTicks - steps * content.constants.spawnGapStepTicks,
      ),
      reactionTicks: Math.max(
        content.constants.minReactionTicks,
        content.constants.baseReactionTicks - steps * content.constants.reactionStepTicks,
      ),
      obstacleDensityPermille: Math.min(
        content.constants.obstacleDensityCapPermille,
        content.constants.baseObstacleDensityPermille + steps * content.constants.obstacleDensityStepPermille,
      ),
    });
  }

  function currentUpgrade(runOrCompleted) {
    const completed = typeof runOrCompleted === 'object'
      ? Math.max(0, runOrCompleted?.completedArchitectures || 0)
      : Math.max(0, Math.floor(Number(runOrCompleted) || 0));
    return content.upgrades.reduce(
      (selected, upgrade) => (completed >= upgrade.threshold ? upgrade : selected),
      content.upgrades[0],
    );
  }

  function paletteForTier(tierValue) {
    const tier = Math.max(1, Math.floor(Number(tierValue) || 1));
    return content.palettes[Math.min(content.palettes.length - 1, tier - 1)];
  }

  function createRun(options = {}) {
    const session = options.session || createSessionState();
    session.runOrdinal += 1;
    const seed = normalizeSeed(options.seed ?? (session.seedBase + Math.imul(session.runOrdinal, 0x9e3779b9)));
    return {
      version: content.version,
      state: 'ready',
      session,
      seed,
      rng: createSeededRng(seed),
      ticks: 0,
      distanceUnits: 0,
      distanceRemainder: 0,
      score: 0,
      tier: 1,
      completedArchitectures: 0,
      architecture: { id: 1, genes: [] },
      lastArchitecture: null,
      collectedIds: Object.create(null),
      seenRoles: Object.create(null),
      phraseSerial: 0,
      phraseBags: Object.create(null),
      lastTemplateId: '',
      consecutiveTemplateRepeats: 0,
      safeRunwayTicks: content.constants.safeRunwayTicks,
      boundaryPending: false,
      respitePhrasesRemaining: 0,
      health: content.constants.maxHealth,
      lastEvent: 'ready',
      lastFailureReason: '',
    };
  }

  function startRun(run) {
    if (!run || run.state === 'game_over') return false;
    run.state = 'playing';
    run.lastEvent = 'run-started';
    return true;
  }

  function pauseRun(run) {
    if (!run || run.state !== 'playing') return false;
    run.state = 'paused';
    run.lastEvent = 'paused';
    return true;
  }

  function resumeRun(run) {
    if (!run || run.state !== 'paused') return false;
    run.state = 'playing';
    run.safeRunwayTicks = Math.max(run.safeRunwayTicks, content.constants.safeRunwayTicks);
    run.lastEvent = 'resumed';
    return true;
  }

  function updateSessionBests(run) {
    run.session.bestScore = Math.max(run.session.bestScore, run.score);
    run.session.bestDistance = Math.max(run.session.bestDistance, run.distanceUnits);
    run.session.bestArchitectures = Math.max(run.session.bestArchitectures, run.completedArchitectures);
  }

  function advanceTicks(run, count = 1) {
    if (!run || run.state !== 'playing') return run;
    const ticks = Math.max(0, Math.floor(Number(count) || 0));
    if (!ticks) return run;
    run.ticks += ticks;
    run.safeRunwayTicks = Math.max(0, run.safeRunwayTicks - ticks);
    const pace = difficultyForTier(run.tier).pacePermille;
    const totalDistance = run.distanceRemainder + content.constants.baseSpeed * pace * ticks;
    run.distanceUnits += Math.floor(totalDistance / (content.constants.ticksPerSecond * 1000));
    run.distanceRemainder = totalDistance % (content.constants.ticksPerSecond * 1000);
    updateSessionBests(run);
    return run;
  }

  function normalizeGene(gene = {}) {
    const roleId = content.roles[gene.roleId] ? gene.roleId : 'unassigned';
    const strand = gene.strand === -1 || gene.strand === 'left' || gene.strand === '<-' ? -1 : 1;
    return {
      id: String(gene.id || ''),
      roleId,
      strand,
      predicted: true,
      points: content.constants.genePoints,
    };
  }

  function collectGene(run, geneInput = {}) {
    if (!run || run.state !== 'playing') return { collected: false, reason: 'not-playing' };
    const gene = normalizeGene(geneInput);
    if (!gene.id) return { collected: false, reason: 'missing-id' };
    if (run.collectedIds[gene.id]) return { collected: false, reason: 'duplicate', score: run.score };

    run.collectedIds[gene.id] = true;
    run.seenRoles[gene.roleId] = true;
    run.architecture.genes.push(gene);
    run.score += content.constants.genePoints;
    run.lastEvent = 'gene-collected';

    let architectureComplete = false;
    let architectureBonus = 0;
    let upgradeUnlocked = null;
    if (run.architecture.genes.length >= content.constants.genesPerArchitecture) {
      architectureComplete = true;
      const beforeUpgrade = currentUpgrade(run).id;
      architectureBonus = content.constants.architectureBaseBonus
        + run.completedArchitectures * content.constants.architectureBonusStep;
      run.score += architectureBonus;
      run.completedArchitectures += 1;
      run.tier = run.completedArchitectures + 1;
      run.lastArchitecture = {
        id: run.architecture.id,
        genes: run.architecture.genes.map((item) => ({ ...item })),
        bonus: architectureBonus,
      };
      run.architecture = { id: run.architecture.id + 1, genes: [] };
      const afterUpgrade = currentUpgrade(run).id;
      if (afterUpgrade !== beforeUpgrade) upgradeUnlocked = afterUpgrade;
      if (run.completedArchitectures % content.constants.boundaryEveryArchitectures === 0) {
        run.boundaryPending = true;
      }
      run.lastEvent = 'architecture-complete';
    }

    updateSessionBests(run);
    return {
      collected: true,
      gene,
      basePoints: content.constants.genePoints,
      score: run.score,
      architectureComplete,
      architectureBonus,
      completedArchitectures: run.completedArchitectures,
      tier: run.tier,
      upgradeUnlocked,
      boundaryActive: run.boundaryPending,
      boundaryPending: run.boundaryPending,
    };
  }

  function shuffleTemplateIds(run, templates) {
    const ids = templates.map((template) => template.id);
    for (let index = ids.length - 1; index > 0; index -= 1) {
      const swapIndex = randomInt(run.rng, index + 1);
      [ids[index], ids[swapIndex]] = [ids[swapIndex], ids[index]];
    }
    return ids;
  }

  function selectFromTemplateBag(run, templates, mode) {
    if (!templates.length) return null;
    if (!run.phraseBags) run.phraseBags = Object.create(null);
    const signature = templates.map((template) => template.id).sort().join('|');
    const bagKey = mode + ':' + signature;
    let bag = run.phraseBags[bagKey];
    if (!Array.isArray(bag) || !bag.length) {
      bag = shuffleTemplateIds(run, templates);
      run.phraseBags[bagKey] = bag;
    }
    if (bag.length > 1 && bag[bag.length - 1] === run.lastTemplateId) {
      const alternateIndex = bag.findIndex((id) => id !== run.lastTemplateId);
      if (alternateIndex >= 0) {
        [bag[alternateIndex], bag[bag.length - 1]] = [bag[bag.length - 1], bag[alternateIndex]];
      }
    }
    if (
      bag.length > 1
      && run.consecutiveTemplateRepeats >= 2
      && bag[bag.length - 1] === run.lastTemplateId
    ) {
      const alternateIndex = bag.findIndex((id) => id !== run.lastTemplateId);
      if (alternateIndex >= 0) {
        [bag[alternateIndex], bag[bag.length - 1]] = [bag[bag.length - 1], bag[alternateIndex]];
      }
    }
    const id = bag.pop();
    return templates.find((template) => template.id === id) || templates[0];
  }

  function templatesFor(run, mode) {
    let templates = content.phraseTemplates.filter((template) => template.minTier <= run.tier);
    if (mode === 'boundary') templates = templates.filter((template) => template.boundary);
    else if (mode === 'respite') templates = templates.filter((template) => !template.boundary && template.respite);
    else templates = templates.filter((template) => !template.boundary);
    if (!templates.length && mode === 'boundary') {
      templates = content.phraseTemplates.filter((template) => template.boundary);
    }
    if (!templates.length && mode === 'respite') {
      templates = content.phraseTemplates.filter((template) => !template.boundary && template.respite);
    }
    return templates;
  }

  function generatePhrase(run, options = {}) {
    if (!run) return null;
    const explicitTemplate = options.templateId
      ? content.phraseTemplates.find((template) => template.id === options.templateId)
      : null;
    let template = explicitTemplate;
    let mode = 'normal';

    if (!template) {
      const boundaryRequested = options.boundary === true
        || (options.boundary !== false && run.boundaryPending === true);
      const respiteRequested = options.respite === true
        || (
          options.respite !== false
          && !boundaryRequested
          && (run.respitePhrasesRemaining || 0) > 0
        );
      if (boundaryRequested) mode = 'boundary';
      else if (respiteRequested) mode = 'respite';
      template = selectFromTemplateBag(run, templatesFor(run, mode), mode);
      if (!template && mode !== 'normal') {
        mode = 'normal';
        template = selectFromTemplateBag(run, templatesFor(run, mode), mode);
      }
    }
    if (!template) return null;

    if (template.boundary) {
      run.boundaryPending = false;
      run.respitePhrasesRemaining = Math.max(
        run.respitePhrasesRemaining || 0,
        content.constants.boundaryRespitePhrases,
      );
    } else if (template.respite && (run.respitePhrasesRemaining || 0) > 0) {
      run.respitePhrasesRemaining -= 1;
    }

    run.phraseSerial += 1;
    if (run.lastTemplateId === template.id) run.consecutiveTemplateRepeats += 1;
    else {
      run.lastTemplateId = template.id;
      run.consecutiveTemplateRepeats = 1;
    }

    let geneIndex = 0;
    const placements = template.placements.map((placement) => {
      const generated = { ...placement };
      if (generated.kind === 'gene') {
        const roleOffset = (run.phraseSerial - 1) * 2 + geneIndex;
        generated.id = [
          run.seed,
          'phrase-' + run.phraseSerial,
          'gene-' + geneIndex,
        ].join(':');
        generated.roleId = content.roleOrder[roleOffset % content.roleOrder.length];
        generated.strand = randomInt(run.rng, 2) === 0 ? -1 : 1;
        generated.predicted = true;
        generated.points = content.constants.genePoints;
        geneIndex += 1;
      }
      return generated;
    });
    return {
      id: [run.seed, 'phrase-' + run.phraseSerial].join(':'),
      templateId: template.id,
      tier: run.tier,
      boundary: template.boundary,
      respite: template.respite,
      safeRoute: template.safeRoute,
      telegraphTicks: Math.max(template.telegraphTicks, difficultyForTier(run.tier).reactionTicks),
      span: template.span,
      recoveryDistance: template.recoveryDistance,
      jumpWindows: template.jumpWindows.map((window) => ({ ...window })),
      placements,
    };
  }

  function isPhraseSurvivable(phrase) {
    return phraseSurvivalIssue(phrase, content) === '';
  }

  function damage(run, reason = 'orange-obstacle') {
    if (!run || run.state !== 'playing') return { damaged: false, reason: 'not-playing' };
    const maxHealth = content.constants.maxHealth;
    const currentHealth = Number.isInteger(run.health)
      ? Math.max(0, Math.min(maxHealth, run.health))
      : maxHealth;
    run.health = Math.max(0, currentHealth - 1);
    const gameOver = run.health === 0;
    run.lastEvent = gameOver ? 'game-over' : 'health-lost';
    if (gameOver) {
      run.state = 'game_over';
      run.lastFailureReason = String(reason || 'orange-obstacle');
      updateSessionBests(run);
    }
    return {
      damaged: true,
      healthLost: 1,
      health: run.health,
      maxHealth,
      gameOver,
    };
  }

  function crash(run, reason = 'fatal-terrain-collision') {
    if (!run || run.state !== 'playing') return { crashed: false, reason: 'not-playing' };
    run.health = 0;
    run.lastFailureReason = String(reason || 'fatal-terrain-collision');
    run.state = 'game_over';
    run.lastEvent = 'game-over';
    updateSessionBests(run);
    return {
      crashed: true,
      fatal: true,
      health: 0,
      maxHealth: content.constants.maxHealth,
      gameOver: true,
    };
  }

  function restartRun(run, options = {}) {
    if (!run) return null;
    const replacement = createRun({ session: run.session, seed: options.seed });
    startRun(replacement);
    Object.keys(run).forEach((key) => delete run[key]);
    Object.assign(run, replacement);
    return run;
  }

  function snapshot(run) {
    if (!run) return null;
    const difficulty = difficultyForTier(run.tier);
    const upgrade = currentUpgrade(run);
    const palette = paletteForTier(run.tier);
    return Object.freeze({
      version: run.version,
      state: RUN_STATES.has(run.state) ? run.state : 'paused',
      seed: run.seed,
      rngDraws: run.rng.draws,
      score: run.score,
      best: {
        score: run.session.bestScore,
        distance: run.session.bestDistance,
        architectures: run.session.bestArchitectures,
      },
      distance: run.distanceUnits,
      ticks: run.ticks,
      tier: run.tier,
      completedArchitectures: run.completedArchitectures,
      architecture: {
        id: run.architecture.id,
        genes: run.architecture.genes.map((gene) => ({ ...gene })),
        required: content.constants.genesPerArchitecture,
        completed: run.architecture.genes.length,
      },
      lastArchitecture: run.lastArchitecture
        ? {
          id: run.lastArchitecture.id,
          genes: run.lastArchitecture.genes.map((gene) => ({ ...gene })),
          bonus: run.lastArchitecture.bonus,
        }
        : null,
      upgrade: { id: upgrade.id, label: upgrade.label },
      health: run.health,
      maxHealth: content.constants.maxHealth,
      difficulty: { ...difficulty },
      paletteId: palette.id,
      boundaryPending: run.boundaryPending === true,
      respitePhrasesRemaining: Math.max(0, run.respitePhrasesRemaining || 0),
      lastTemplateId: run.lastTemplateId || '',
      consecutiveTemplateRepeats: Math.max(0, run.consecutiveTemplateRepeats || 0),
      safeRunwayTicks: run.safeRunwayTicks,
      lastEvent: run.lastEvent,
      lastFailureReason: run.lastFailureReason,
    });
  }

  return Object.freeze({
    content,
    validationReport,
    normalizeSeed,
    createSeededRng,
    nextRandomUint,
    randomInt,
    validateContent,
    createSessionState,
    createRun,
    startRun,
    pauseRun,
    resumeRun,
    advanceTicks,
    difficultyForTier,
    currentUpgrade,
    paletteForTier,
    collectGene,
    generatePhrase,
    isPhraseSurvivable,
    damage,
    crash,
    restartRun,
    snapshot,
  });
});
