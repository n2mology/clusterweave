(function attachClusterWeaveGameContent(root, factory) {
  const content = factory();
  if (typeof module === 'object' && module.exports) module.exports = content;
  if (root) root.ClusterWeaveGameContent = content;
})(typeof globalThis !== 'undefined' ? globalThis : this, function createClusterWeaveGameContent() {
  'use strict';

  function deepFreeze(value) {
    if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
    Object.getOwnPropertyNames(value).forEach((key) => deepFreeze(value[key]));
    return Object.freeze(value);
  }

  /*
   * These are deliberately broad, predicted-role buckets. They are game symbols,
   * not claims about a submitted genome, expression, chemistry, or biological value.
   */
  const roles = {
    core: {
      label: 'CORE?',
      shortLabel: 'CORE',
      color: '#00d9ff',
      glyph: 'diamond',
      predicted: true,
      description: 'A possible core biosynthetic role.',
    },
    tailoring: {
      label: 'TAILORING?',
      shortLabel: 'TAILOR',
      color: '#ff7a18',
      glyph: 'notch',
      predicted: true,
      description: 'A possible additional or tailoring role.',
    },
    transport: {
      label: 'TRANSPORT?',
      shortLabel: 'MOVE',
      color: '#b8a5ff',
      glyph: 'bars',
      predicted: true,
      description: 'A possible transport-associated role.',
    },
    regulation: {
      label: 'REGULATION?',
      shortLabel: 'REG',
      color: '#d7ff1f',
      glyph: 'pulse',
      predicted: true,
      description: 'A possible regulatory role.',
    },
    precursor: {
      label: 'PRECURSOR?',
      shortLabel: 'PRE',
      color: '#ff63bd',
      glyph: 'dot',
      predicted: true,
      description: 'A possible precursor-associated role.',
    },
    unassigned: {
      label: 'UNASSIGNED',
      shortLabel: '?',
      color: '#fff8e7',
      glyph: 'hatch',
      predicted: true,
      description: 'No role is assigned in this illustration.',
    },
  };

  const roleOrder = ['core', 'tailoring', 'transport', 'regulation', 'precursor', 'unassigned'];

  const upgrades = [
    {
      id: 'field_brush',
      threshold: 0,
      label: 'FIELD BRUSH',
      accessory: 'field-pack',
      effect: 'Base field kit.',
    },
    {
      id: 'role_lens',
      threshold: 1,
      label: 'ROLE LENS',
      accessory: 'visor-band',
      effect: 'Makes predicted-role symbols easier to read.',
    },
    {
      id: 'buffer_pack',
      threshold: 3,
      label: 'BUFFER PACK',
      accessory: 'buffer-cell',
      effect: 'Adds a visible buffer vial to the field kit.',
    },
    {
      id: 'context_beacon',
      threshold: 5,
      label: 'CONTEXT BEACON',
      accessory: 'shoulder-beacon',
      effect: 'Telegraphs the next arcade phrase.',
    },
  ];

  const palettes = [
    { id: 'cyan-depth', sky: '#070a12', grid: '#18233d', mist: '#163a4a', accent: '#00d9ff', biology: '#84e6a3', ground: '#fff8e7', under: '#7b6dff' },
    { id: 'orange-depth', sky: '#100914', grid: '#34203d', mist: '#52233d', accent: '#ff7a18', biology: '#63d6a3', ground: '#fff3dd', under: '#ff3ba7' },
    { id: 'acid-depth', sky: '#08120f', grid: '#17372e', mist: '#31533a', accent: '#d7ff1f', biology: '#8fd3ff', ground: '#f9ffe6', under: '#00a8cc' },
    { id: 'violet-depth', sky: '#0d0920', grid: '#28204d', mist: '#3e2d66', accent: '#b8a5ff', biology: '#69dbb8', ground: '#fff8e7', under: '#ff7a18' },
    { id: 'deep-weave', sky: '#05070d', grid: '#15223b', mist: '#243d58', accent: '#ff63bd', biology: '#7cc8ff', ground: '#fff8e7', under: '#00d9ff' },
  ];

  /*
   * Phrases describe only abstract arcade geometry. Every phrase has a declared
   * survivable route and a telegraph at or above the global reaction-time floor.
   */
  const phraseTemplates = [
    {
      "id": "flat-ribbon",
      "minTier": 1,
      "boundary": false,
      "respite": true,
      "safeRoute": "ground",
      "telegraphTicks": 132,
      "span": 140,
      "recoveryDistance": 96,
      "jumpWindows": [],
      "placements": [
        {
          "kind": "gene",
          "at": 24,
          "lane": "low"
        },
        {
          "kind": "gene",
          "at": 78,
          "lane": "mid"
        },
        {
          "kind": "gene",
          "at": 116,
          "lane": "low"
        }
      ]
    },
    {
      "id": "barrier-arc",
      "minTier": 1,
      "boundary": false,
      "respite": false,
      "safeRoute": "single-jump",
      "telegraphTicks": 124,
      "span": 150,
      "recoveryDistance": 88,
      "jumpWindows": [
        {
          "start": 20,
          "end": 108
        }
      ],
      "placements": [
        {
          "kind": "gene",
          "at": 35,
          "lane": "arc"
        },
        {
          "kind": "obstacle",
          "at": 57,
          "shape": "pylon"
        },
        {
          "kind": "gene",
          "at": 78,
          "lane": "arc"
        }
      ]
    },
    {
      "id": "field-plinth",
      "minTier": 1,
      "boundary": false,
      "respite": false,
      "safeRoute": "ground-or-platform",
      "telegraphTicks": 124,
      "span": 170,
      "recoveryDistance": 88,
      "jumpWindows": [],
      "placements": [
        {
          "kind": "platform",
          "at": 52,
          "shape": "plinth"
        },
        {
          "kind": "gene",
          "at": 66,
          "lane": "high"
        },
        {
          "kind": "gene",
          "at": 126,
          "lane": "low"
        }
      ]
    },
    {
      "id": "dnase-hop",
      "minTier": 2,
      "boundary": false,
      "respite": false,
      "safeRoute": "single-jump",
      "telegraphTicks": 116,
      "span": 165,
      "recoveryDistance": 92,
      "jumpWindows": [
        {
          "start": 28,
          "end": 124
        }
      ],
      "placements": [
        {
          "kind": "warning",
          "at": 10,
          "shape": "dnase-chevron"
        },
        {
          "kind": "pit",
          "at": 62,
          "shape": "hop"
        },
        {
          "kind": "gene",
          "at": 68,
          "lane": "arc"
        },
        {
          "kind": "gene",
          "at": 112,
          "lane": "mid"
        }
      ]
    },
    {
      "id": "plateau-drop",
      "minTier": 2,
      "boundary": false,
      "respite": false,
      "safeRoute": "ground-or-platform",
      "telegraphTicks": 112,
      "span": 190,
      "recoveryDistance": 86,
      "jumpWindows": [],
      "placements": [
        {
          "kind": "platform",
          "at": 34,
          "shape": "terrace"
        },
        {
          "kind": "gene",
          "at": 48,
          "lane": "high"
        },
        {
          "kind": "platform",
          "at": 112,
          "shape": "step"
        },
        {
          "kind": "gene",
          "at": 124,
          "lane": "mid"
        }
      ]
    },
    {
      "id": "twin-barrier",
      "minTier": 3,
      "boundary": false,
      "respite": false,
      "safeRoute": "two-jumps",
      "telegraphTicks": 108,
      "span": 250,
      "recoveryDistance": 92,
      "jumpWindows": [
        {
          "start": 18,
          "end": 100
        },
        {
          "start": 138,
          "end": 232
        }
      ],
      "placements": [
        {
          "kind": "obstacle",
          "at": 45,
          "shape": "short"
        },
        {
          "kind": "gene",
          "at": 55,
          "lane": "arc"
        },
        {
          "kind": "gene",
          "at": 122,
          "lane": "low"
        },
        {
          "kind": "obstacle",
          "at": 166,
          "shape": "pylon"
        },
        {
          "kind": "gene",
          "at": 180,
          "lane": "high"
        }
      ]
    },
    {
      "id": "broken-scaffold",
      "minTier": 3,
      "boundary": false,
      "respite": false,
      "safeRoute": "platform-to-jump",
      "telegraphTicks": 104,
      "span": 210,
      "recoveryDistance": 94,
      "jumpWindows": [
        {
          "start": 70,
          "end": 176
        }
      ],
      "placements": [
        {
          "kind": "platform",
          "at": 28,
          "shape": "terrace"
        },
        {
          "kind": "gene",
          "at": 90,
          "lane": "high"
        },
        {
          "kind": "warning",
          "at": 76,
          "shape": "dnase-chevron"
        },
        {
          "kind": "pit",
          "at": 108,
          "shape": "channel"
        },
        {
          "kind": "gene",
          "at": 116,
          "lane": "arc"
        }
      ]
    },
    {
      "id": "dnase-channel",
      "minTier": 4,
      "boundary": false,
      "respite": false,
      "safeRoute": "long-jump",
      "telegraphTicks": 100,
      "span": 180,
      "recoveryDistance": 96,
      "jumpWindows": [
        {
          "start": 26,
          "end": 134
        }
      ],
      "placements": [
        {
          "kind": "warning",
          "at": 8,
          "shape": "dnase-chevron"
        },
        {
          "kind": "pit",
          "at": 67,
          "shape": "channel"
        },
        {
          "kind": "gene",
          "at": 76,
          "lane": "high"
        },
        {
          "kind": "gene",
          "at": 130,
          "lane": "low"
        }
      ]
    },
    {
      "id": "platform-stairs",
      "minTier": 4,
      "boundary": false,
      "respite": false,
      "safeRoute": "ground-or-platform",
      "telegraphTicks": 96,
      "span": 230,
      "recoveryDistance": 88,
      "jumpWindows": [],
      "placements": [
        {
          "kind": "platform",
          "at": 24,
          "shape": "step"
        },
        {
          "kind": "gene",
          "at": 34,
          "lane": "mid"
        },
        {
          "kind": "platform",
          "at": 92,
          "shape": "plinth"
        },
        {
          "kind": "gene",
          "at": 106,
          "lane": "high"
        },
        {
          "kind": "platform",
          "at": 166,
          "shape": "step"
        },
        {
          "kind": "gene",
          "at": 178,
          "lane": "mid"
        }
      ]
    },
    {
      "id": "pylon-pit",
      "minTier": 5,
      "boundary": false,
      "respite": false,
      "safeRoute": "two-jumps",
      "telegraphTicks": 92,
      "span": 270,
      "recoveryDistance": 98,
      "jumpWindows": [
        {
          "start": 16,
          "end": 102
        },
        {
          "start": 142,
          "end": 250
        }
      ],
      "placements": [
        {
          "kind": "obstacle",
          "at": 45,
          "shape": "pylon"
        },
        {
          "kind": "gene",
          "at": 58,
          "lane": "arc"
        },
        {
          "kind": "warning",
          "at": 142,
          "shape": "dnase-chevron"
        },
        {
          "kind": "pit",
          "at": 177,
          "shape": "channel"
        },
        {
          "kind": "gene",
          "at": 186,
          "lane": "high"
        }
      ]
    },
    {
      "id": "double-nick",
      "minTier": 6,
      "boundary": false,
      "respite": false,
      "safeRoute": "two-jumps",
      "telegraphTicks": 88,
      "span": 280,
      "recoveryDistance": 100,
      "jumpWindows": [
        {
          "start": 16,
          "end": 105
        },
        {
          "start": 150,
          "end": 258
        }
      ],
      "placements": [
        {
          "kind": "warning",
          "at": 10,
          "shape": "dnase-chevron"
        },
        {
          "kind": "pit",
          "at": 48,
          "shape": "nick"
        },
        {
          "kind": "gene",
          "at": 55,
          "lane": "arc"
        },
        {
          "kind": "warning",
          "at": 142,
          "shape": "dnase-chevron"
        },
        {
          "kind": "pit",
          "at": 184,
          "shape": "hop"
        },
        {
          "kind": "gene",
          "at": 190,
          "lane": "high"
        }
      ]
    },
    {
      "id": "context-terraces",
      "minTier": 7,
      "boundary": false,
      "respite": false,
      "safeRoute": "platform-to-jump",
      "telegraphTicks": 84,
      "span": 245,
      "recoveryDistance": 94,
      "jumpWindows": [
        {
          "start": 118,
          "end": 220
        }
      ],
      "placements": [
        {
          "kind": "platform",
          "at": 25,
          "shape": "terrace"
        },
        {
          "kind": "gene",
          "at": 42,
          "lane": "high"
        },
        {
          "kind": "platform",
          "at": 92,
          "shape": "step"
        },
        {
          "kind": "obstacle",
          "at": 154,
          "shape": "block"
        },
        {
          "kind": "gene",
          "at": 168,
          "lane": "arc"
        }
      ]
    },
    {
      "id": "boundary-causeway",
      "minTier": 4,
      "boundary": true,
      "respite": false,
      "safeRoute": "three-jumps",
      "telegraphTicks": 90,
      "span": 360,
      "recoveryDistance": 120,
      "jumpWindows": [
        {
          "start": 15,
          "end": 100
        },
        {
          "start": 138,
          "end": 230
        },
        {
          "start": 265,
          "end": 352
        }
      ],
      "placements": [
        {
          "kind": "warning",
          "at": 0,
          "shape": "beacon"
        },
        {
          "kind": "obstacle",
          "at": 46,
          "shape": "short"
        },
        {
          "kind": "gene",
          "at": 58,
          "lane": "arc"
        },
        {
          "kind": "pit",
          "at": 175,
          "shape": "channel"
        },
        {
          "kind": "gene",
          "at": 184,
          "lane": "high"
        },
        {
          "kind": "obstacle",
          "at": 304,
          "shape": "pylon"
        },
        {
          "kind": "gene",
          "at": 316,
          "lane": "arc"
        }
      ]
    },
    {
      "id": "boundary-deep-weave",
      "minTier": 7,
      "boundary": true,
      "respite": false,
      "safeRoute": "three-jumps",
      "telegraphTicks": 82,
      "span": 390,
      "recoveryDistance": 130,
      "jumpWindows": [
        {
          "start": 15,
          "end": 105
        },
        {
          "start": 145,
          "end": 250
        },
        {
          "start": 288,
          "end": 382
        }
      ],
      "placements": [
        {
          "kind": "warning",
          "at": 0,
          "shape": "beacon"
        },
        {
          "kind": "pit",
          "at": 48,
          "shape": "nick"
        },
        {
          "kind": "gene",
          "at": 55,
          "lane": "arc"
        },
        {
          "kind": "platform",
          "at": 112,
          "shape": "step"
        },
        {
          "kind": "obstacle",
          "at": 184,
          "shape": "block"
        },
        {
          "kind": "gene",
          "at": 198,
          "lane": "high"
        },
        {
          "kind": "pit",
          "at": 324,
          "shape": "hop"
        },
        {
          "kind": "gene",
          "at": 330,
          "lane": "arc"
        }
      ]
    }
  ];

  const sources = {
    fungalDiversity: {
      label: 'Fungal diversity review',
      url: 'https://pmc.ncbi.nlm.nih.gov/articles/PMC6899921/',
    },
    evidenceModel: {
      label: 'MIBiG evidence model',
      url: 'https://academic.oup.com/nar/article/53/D1/D678/7919508',
    },
    familyFramework: {
      label: 'Gene-cluster family framework',
      url: 'https://www.nature.com/articles/s41589-019-0400-9',
    },
  };

  const geometry = {
    "playerWidth": 23,
    "playerHeight": 36,
    "playerVisualWidth": 34,
    "playerVisualHeight": 44,
    "geneHeight": 11,
    "minimumJumpRise": 40,
    "maximumPitWidth": 52,
    "maximumPlatformHeight": 22,
    "laneOffsets": {
      "low": 9,
      "mid": 29,
      "high": 48,
      "arc": 37
    },
    "obstacles": {
      "wide": {
        "width": 27,
        "height": 13
      },
      "short": {
        "width": 12,
        "height": 10
      },
      "block": {
        "width": 18,
        "height": 18
      },
      "pylon": {
        "width": 15,
        "height": 26
      }
    },
    "pits": {
      "nick": {
        "width": 30
      },
      "hop": {
        "width": 34
      },
      "channel": {
        "width": 46
      }
    },
    "platforms": {
      "step": {
        "width": 38,
        "height": 10
      },
      "plinth": {
        "width": 52,
        "height": 14
      },
      "terrace": {
        "width": 68,
        "height": 18
      }
    }
  };

  return deepFreeze({
    version: '20260714-runner6',
    title: 'CANDIDATE WEAVE',
    roles,
    roleOrder,
    upgrades,
    palettes,
    phraseTemplates,
    sources,
    geometry,
    constants: {
      "ticksPerSecond": 60,
      "maxHealth": 5,
      "genesPerArchitecture": 6,
      "genePoints": 25,
      "architectureBaseBonus": 150,
      "architectureBonusStep": 25,
      "baseSpeed": 84,
      "jumpVelocity": -195,
      "gravity": 400,
      "terminalVelocity": 320,
      "coyoteTicks": 7,
      "jumpBufferTicks": 9,
      "paceRampTicks": 90,
      "basePacePermille": 1000,
      "paceRungsPermille": [
        1000,
        1500,
        1750,
        2000,
        2500,
        2750,
        3000
      ],
      "paceCapPermille": 3000,
      "finalStageTier": 7,
      "finalStagePacePermille": 3000,
      "finalStageMotionScalePermille": 3000,
      "baseSpawnGapTicks": 128,
      "spawnGapStepTicks": 4,
      "minSpawnGapTicks": 88,
      "baseReactionTicks": 132,
      "reactionStepTicks": 4,
      "minReactionTicks": 72,
      "baseObstacleDensityPermille": 1000,
      "obstacleDensityStepPermille": 0,
      "obstacleDensityCapPermille": 1000,
      "maxJumpDistance": 112,
      "minimumLandingRun": 18,
      "minimumRecoveryDistance": 80,
      "boundaryRecoveryDistance": 110,
      "safeRunwayTicks": 120,
      "boundaryEveryArchitectures": 3,
      "boundaryRespitePhrases": 1,
      "maxEntities": 128
    },
    guide: {
      label: 'FIELD GUIDE',
      summary: 'How to read the gene weave',
      points: [
        'Each cassette is an illustrative genomic region, and every role label is predicted.',
        'Arrow direction shows gene orientation; nearby arrows do not prove co-transcription.',
        'A candidate architecture does not prove expression, a product, activity, safety, or value.',
        'DNase pits are an arcade metaphor for a DNA-degradation trench, not a claim about a gene, organism, or submitted genome.',
        'Fungal and bacterial forms in the scenery are decorative diversity cues, never hazards.',
      ],
      reviewStatus: 'pending_scientific_review',
    },
    guardrails: {
      architectureIsIllustrative: true,
      rolesArePredicted: true,
      coLocationDoesNotProveCoTranscription: true,
      candidateDoesNotProveProduct: true,
      pointsAreNotScientificEvidence: true,
      equalRolePointValue: true,
      biologyIsNeverAHazard: true,
      genesAndOrganismsAreNeverHazards: true,
      dnasePitsAreArcadeMetaphor: true,
      microbialSceneryIsDecorative: true,
      noUserJobData: true,
    },
  });
});
