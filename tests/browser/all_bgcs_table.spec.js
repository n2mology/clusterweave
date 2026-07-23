const { test, expect } = require('@playwright/test');

const baseUrl = 'http://127.0.0.1:4173';


test('ALL BGC defaults to All and scrolls without stealing search focus', async ({ page }) => {
  await page.goto(baseUrl);
  await page.evaluate(() => {
    document.body.innerHTML = '<main style="width:420px"><div class="result-focus-panel"><div class="result-reader-surface"><div id="files-container"><div class="summary-reader-doc" id="summary-reader-doc"></div></div></div></div></main>';
    const rows = [
      {
        genome: 'Zeta_fungus',
        taxon_group: 'fungi',
        detector_relation: 'shared',
        antismash_bgc_id: 'region_1',
        antismash_bgc_class: 'NRPS',
        funbgcex_bgc_id: 'BGC1',
        antismash_knowncluster_product: 'siderophore',
      },
      {
        genome: 'Acremonium_fungus',
        taxon_group: 'fungi',
        detector_relation: 'shared',
        antismash_bgc_id: 'region_2',
        antismash_bgc_class: 'T1PKS',
        funbgcex_bgc_id: 'BGC2',
        antismash_knowncluster_product: 'terpene',
      },
      {
        genome: 'Alpha_bacterium',
        taxon_group: 'bacteria',
        detector_relation: 'antismash_only',
        antismash_bgc_id: 'Alpha_bacterium_NC_000001.1.region003',
        antismash_bgc_class: 'T1PKS',
        antismash_knowncluster_similarity_score: '87',
        antismash_knowncluster_accession: 'BGC0000001',
        antismash_knowncluster_product: 'polyketide with an intentionally long annotation',
        antismash_clustercompare_similarity_score: '0.91',
        antismash_clustercompare_compounds: 'compound cluster',
        antismash_clustercompare_organism: 'Reference bacterium',
      },
      {
        genome: 'Beta_bacterium',
        taxon_group: 'bacteria',
        detector_relation: 'antismash_only',
        antismash_bgc_id: 'region_4',
        antismash_bgc_class: 'NRPS',
        antismash_knowncluster_product: 'peptide',
      },
    ];
    for (let index = 0; index < 24; index += 1) {
      rows.push({
        genome: 'Bacterium_' + String(index).padStart(2, '0'),
        taxon_group: 'bacteria',
        detector_relation: 'antismash_only',
        antismash_bgc_id: 'region_' + String(index + 5),
        antismash_bgc_class: 'NRPS',
        antismash_knowncluster_product: 'peptide',
      });
    }
    allBgcTableState = {
      path: 'all_tools_bgc_comparison.csv',
      rows,
      query: '',
      taxon: '',
      genome: '',
      sortKey: 'genome',
      sortDir: 'asc',
    };
    renderAllBgcTable();
  });

  const organism = page.getByRole('combobox', { name: 'Organism', exact: true });
  await expect(organism).toHaveValue('');
  await expect(page.locator('.all-bgc-table tbody tr')).toHaveCount(28);
  await expect(page.locator('.all-bgc-table thead th')).toHaveText([
    'Organism ↑', 'Kingdom', 'Detector support', 'antiSMASH region',
    'antiSMASH BGC class', 'KnownClusterBlast score', 'KnownCluster accession',
    'KnownCluster product', 'ClusterCompare score', 'ClusterCompare compounds',
    'ClusterCompare organism', 'FunBGCeX core enzymes', 'FunBGCeX similar BGC',
    'FunBGCeX similarity score', 'FunBGCeX putative product',
  ]);

  const wrap = page.locator('.all-bgc-table-wrap');
  const overflow = await wrap.evaluate(element => ({
    horizontal: element.scrollWidth > element.clientWidth,
    vertical: element.scrollHeight > element.clientHeight,
  }));
  expect(overflow).toEqual({ horizontal: true, vertical: true });
  await wrap.hover();
  await page.mouse.wheel(0, 600);
  await expect.poll(() => wrap.evaluate(element => element.scrollTop)).toBeGreaterThan(0);

  await page.getByRole('combobox', { name: 'Kingdom', exact: true }).selectOption('bacteria');
  await expect(organism).toHaveValue('');
  const organismValues = await organism.locator('option').evaluateAll(options => options.map(option => option.value));
  expect(organismValues).not.toContain('Acremonium_fungus');
  expect(organismValues).not.toContain('Zeta_fungus');

  await organism.selectOption('Alpha_bacterium');
  const search = page.getByRole('searchbox', { name: 'Search', exact: true });
  await search.pressSequentially('polyketide');
  await expect(search).toHaveValue('polyketide');
  await expect(search).toBeFocused();
  await expect(page.locator('.all-bgc-table tbody tr')).toHaveCount(1);
  await expect(page.locator('.all-bgc-table tbody tr')).toContainText('NC_000001.1.region003');
  await expect(page.locator('.all-bgc-table tbody tr')).not.toContainText('Alpha_bacterium_NC_000001.1.region003');
  await expect(page.locator('.all-bgc-table tbody tr')).toContainText('BGC0000001');
  await expect(page.locator('.all-bgc-table tbody tr')).toContainText('0.91');
  await expect(page.getByRole('button', { name: 'Previous' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Next' })).toHaveCount(0);
});

test('ATLAS shows domain sections, member genomes, and numerically scored annotations', async ({ page }) => {
  await page.goto(baseUrl);
  const selected = await page.evaluate(() => preferredSummaryViewFile([
    'data/results/example/summary/family_atlas_shortlist.md',
    'data/results/example/summary/family_atlas_shortlist.tsv',
  ], 'atlas'));
  expect(selected).toMatch(/\.tsv$/);

  await page.evaluate(() => {
    document.body.innerHTML = '<main style="width:720px"><div class="result-focus-panel"><div class="result-reader-surface"><div id="files-container"><div class="summary-reader-doc" id="summary-reader-doc"></div></div></div></div></main>';
    const headers = [
      'atlas_rank', 'manual_review_bucket', 'bigscape_cc', 'shared_cc_primary_families',
      'shared_cc_record_count', 'shared_cc_dataset_genome_count', 'shared_cc_dataset_genomes',
      'shared_cc_dataset_organisms', 'shared_cc_taxon_groups', 'genome', 'taxon_group',
      'antismash_class', 'antismash_knowncluster_product', 'antismash_knowncluster_accession',
      'antismash_knowncluster_similarity_score', 'antismash_clustercompare_compounds',
      'antismash_clustercompare_similarity_score', 'antismash_clustercompare_organism',
      'funbgcex_similar_bgc', 'funbgcex_similarity_score', 'funbgcex_putative_product',
      'recommended_followup', 'safe_claim_text',
    ];
    const rows = [
      ['1', 'atlas_now', '42', 'FAM_00001', '12', '2', 'Alpha_fungus;Gamma_fungus', 'Alpha fungus;Gamma fungus', 'fungi', 'Alpha_fungus', 'fungi', 'T1PKS', 'compound alpha', 'BGC0000001', '88', 'cluster compound', '0.91', 'Reference fungus', 'FGBGC-1', '73', 'fun product', 'review GCF context', 'Product identity is not assigned.'],
      ['2', 'atlas_context', '43', 'FAM_00002', '9', '2', 'Alpha_bacterium;Beta_bacterium', 'Alpha bacterium;Beta bacterium', 'bacteria', 'Alpha_bacterium', 'bacteria', 'NRPS', 'bacterial product', 'BGC0000002', '64', 'bacterial cluster compound', '0.82', 'Reference bacterium', '', '', '', 'review bacterial context', 'Product identity is not assigned.'],
      ['3', 'atlas_now', '44', 'FAM_00003', '8', '2', 'Alpha_fungus;Alpha_bacterium', 'Alpha fungus;Alpha bacterium', 'bacteria;fungi', 'Alpha_fungus', 'fungi', 'terpene', '', '', '', '', '', '', 'FGBGC-3', '51', 'cross product', 'confirm experimentally', 'Putative family annotation.'],
    ];
    const text = [headers.join('\t'), ...rows.map(row => row.join('\t'))].join('\n');
    document.getElementById('summary-reader-doc').innerHTML = renderTextSummary(
      'data/results/example/summary/family_atlas_shortlist.tsv',
      text,
    );
  });

  await expect(page.locator('.summary-condensed-title')).toHaveText('DATASET-WIDE FAMILY ATLAS');
  await expect(page.locator('.summary-condensed-meta')).toHaveText('3 total families · Fungal 1 · Bacterial 1 · Cross-kingdom 1');
  await expect(page.locator('.atlas-domain-head h3')).toHaveText([
    'Fungal families', 'Bacterial families', 'Cross-kingdom families',
  ]);
  await expect(page.locator('.atlas-table').first().locator('thead th')).toHaveText([
    'Rank', 'Representative organism', 'BiG-SCAPE CC', 'GCF families', 'BGCs',
    'Genome count', 'Genome members', 'BGC class', 'Scored annotation hits', 'Note',
  ]);
  await expect(page.locator('.atlas-table tbody tr')).toHaveCount(3);
  await expect(page.locator('.atlas-rank-badge')).toHaveText(['1', '2', '3']);
  await expect(page.locator('[data-atlas-domain="fungi"]')).toContainText('Alpha fungus · Gamma fungus');
  await expect(page.locator('[data-atlas-domain="bacteria"]')).toContainText('Alpha bacterium · Beta bacterium');
  await expect(page.locator('[data-atlas-domain="bacteria"]')).toContainText('KnownClusterBlast: bacterial product · BGC0000002 · score 64');
  await expect(page.locator('[data-atlas-domain="bacteria"]')).toContainText('ClusterCompare: bacterial cluster compound · Reference bacterium · score 0.82');
  await expect(page.locator('[data-atlas-domain="cross"]')).toContainText('FunBGCeX similar BGC: FGBGC-3 · cross product · score 51');
  await expect(page.locator('#summary-reader-doc')).not.toContainText('Known-cluster High');
  await expect(page.locator('#summary-reader-doc')).toContainText('Product identity is not assigned. Follow-up: review GCF context.');
  const headerStyle = await page.locator('.atlas-table').first().locator('th').nth(1).evaluate(element => {
    const style = getComputedStyle(element);
    return { paddingLeft: parseFloat(style.paddingLeft), whiteSpace: style.whiteSpace };
  });
  expect(headerStyle.paddingLeft).toBeGreaterThan(8);
  expect(headerStyle.whiteSpace).toBe('normal');
});
