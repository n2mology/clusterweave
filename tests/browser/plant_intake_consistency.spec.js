const { test, expect } = require('@playwright/test');
const plant = 'LOCUS       Populus 12 bp DNA\n  ORGANISM  Populus trichocarpa\n            Eukaryota; Viridiplantae; Streptophyta.\nFEATURES             Location/Qualifiers\n     source          1..12\n     CDS             1..12\n                     /translation="MMM"\nORIGIN\n        1 atgatgatgtaa\n//\n';

test.beforeEach(async ({page}) => {
  await page.route('**/api/system/status*', route => route.fulfill({json: {
    online:true, service:'online', submissions_open:true, public_quota:{max_accessions:50,max_genome_files:50},
  }}));
  await page.goto('http://127.0.0.1:4173');
  await expect(page.locator('#bootstrap-splash')).toHaveClass(/hidden/);
});

test('new and reset intake are mixed and include pending plant tools without artifacts', async ({page}) => {
  const mixed=page.locator('input[name="analysis-scope"][value="mixed"]');
  await expect(mixed).toBeChecked();
  for (const width of [1440,390]) {
    await page.setViewportSize({width,height:1000});
    for (const [scope,label] of [['plants','Discover the hidden potential of plants'],['mixed','Discover the hidden potential of plants fungi and bacteria']]) {
      await page.locator('label').filter({has:page.locator(`input[name="analysis-scope"][value="${scope}"]`)}).click();
      await expect(page.locator('#overview h1')).toHaveText(label);
      await expect(page.locator('#overview h1')).toHaveAttribute('aria-label',label);
      await expect(page.locator('input[name="analysis-scope"]:checked + span')).toHaveCSS('background-color','rgb(255, 59, 167)');
      await expect(page.locator('#overview h1 > span')).toHaveCount(label.split(' ').length);
      await expect(page.locator('input[name="analysis-scope"]:checked + span')).toHaveCSS('font-weight','1000');
      expect(await page.locator('#overview h1').evaluate(e=>e.scrollWidth-e.clientWidth)).toBeLessThanOrEqual(1);
      if(process.env.CLUSTERWEAVE_UI_EVIDENCE) await page.locator('#overview').screenshot({path:process.env.CLUSTERWEAVE_UI_EVIDENCE+`/scope-${scope}-${width}.png`});
    }
  }
  await expect(page.locator('input[name="analysis-scope"][value="both"]')).toHaveCount(0);
  const data=await page.evaluate(()=>({
    plant:resultCategoryApplicable('plantismash'), fungi:resultCategoryApplicable('funbgcex'),
    historical:analysisContextFromJob({analysis_scope:'both'}).scope,
    missing:analysisContextFromJob({}).scope,
    files:activeResultFiles.length,
  }));
  expect(data).toEqual({plant:true,fungi:true,historical:'both',missing:'fungi',files:0});
  await expect(page.locator('#result-bubble-panel')).toContainText(/plantismash/i);
  await page.evaluate(()=>resetStagedAnalysisState('plants'));
  await page.evaluate(()=>resetStagedAnalysisState());
  await expect(mixed).toBeChecked();
  await page.reload();
  await expect(mixed).toBeChecked();
});

test('plant credit links upstream with license without a source-download footer',async ({page})=>{
  await expect(page.locator('#overview a[href$="plantismash-source.zip"]')).toHaveCount(0);
  await page.locator('#tool-credit-open').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog',{name:'Upstream tool credit'})).toBeVisible();
  await expect(page.locator('#tool-credit-close')).toBeFocused();
  await page.locator('#tool-credit-web-tab').focus();
  await page.keyboard.press('Enter');
  const credit=page.locator('.tool-credit-link').filter({hasText:'plantiSMASH'});
  await expect(credit).toHaveText('plantiSMASHAGPL-3.0+');
  await expect(credit).toHaveAttribute('href','https://github.com/plantismash/plantismash');
  await expect(credit).not.toHaveAttribute('download');
  await expect(page.locator('#tool-credit-overlay a[href$="plantismash-source.zip"]')).toHaveCount(0);
  await expect(page.locator('.tool-credit-source-note')).toHaveCount(0);
  await page.keyboard.press('Escape');
  await expect(page.locator('#tool-credit-open')).toBeFocused();
});

test('actual accession screen distinguishes plant taxonomy verification from annotation',async({page})=>{
  await page.route('**/api/inputs/validate',route=>route.fulfill({json:{results:[{
    accession:'GCF_000002775.5',accepted:true,organism_name:'Populus trichocarpa',taxon_group:'plants',
  }]}}));
  const input=page.locator('.brutal-accession-line:not(.is-concealed) textarea').first();
  await input.fill('GCF_000002775.5');await page.locator('#project-name').focus();
  await page.locator('#project-name').fill('plant_verification');
  await page.locator('#run-btn').click();
  await page.evaluate(()=>{renderBrutalAccessionRows();renderInputChecker();});
  await expect(page.locator('#input-checker-list')).toContainText('Populus trichocarpa / plants');
  await expect(page.locator('#input-checker-list')).toContainText('Taxonomy only; translated CDS validation is pending');
  await expect(page.locator('#input-checker-list')).not.toContainText('BACTERIAL ROUTING');
});

for (const large of [false,true]) test(`plant upload ${large?'large':'small'} preview retains annotation limits`,async({page})=>{
  await page.locator('#file-input').setInputFiles({name:'Populus.gbk',mimeType:'text/plain',buffer:Buffer.from(plant+(large?' '.repeat(5*1024*1024):''))});
  await expect(page.locator('#file-list')).toContainText('Populus.gbk');
  await expect.poll(()=>page.evaluate(()=>genomeCheckCache.size)).toBeGreaterThan(0);
  const checks=await page.evaluate(()=>Array.from(genomeCheckCache.values()));
  expect(JSON.stringify(checks)).not.toMatch(/authoritative fungal taxonomy|bacterial GenBank|Prodigal/);
  expect(JSON.stringify(checks)).toMatch(/validation|validate/);
});

test('saved plant and mixed receipts retain authoritative taxa and all counts',async({page})=>{
  const data=await page.evaluate(()=>{
    const job={id:'plant-saved',analysis_scope:'mixed',taxon_counts:{plants:1,fungi:1,bacteria:1},input_summary:{accession_metadata:[{accession:'GCF_000002775.5',taxon_group:'plants',organism_name:'Populus trichocarpa'}]}};
    const receipt=runSetupReceiptFromJob(job);const item=receiptAcceptedInputItems(receipt)[0];
    return {group:item.taxonGroup,taxa:receiptTaxaLine(receipt,item),scope:receipt.analysisScope,
      counts:receipt.taxonCounts,unknown:receiptTaxaLine({analysisScope:'mixed'},{kind:'NCBI accession'})};
  });
  expect(data.group).toBe('plants');expect(data.taxa).toBe('plants / NCBI taxonomy');
  expect(data.counts).toMatchObject({fungi:1,bacteria:1,plants:1});expect(data.unknown).toBe('NCBI taxonomy pending');
});

test('unannotated plant upload is blocked and a translated same-stem pair stays pending',async({page})=>{
  await page.locator('label').filter({has:page.locator('input[name="analysis-scope"][value="plants"]')}).click();
  const fasta={name:'Populus.fna',mimeType:'text/plain',buffer:Buffer.from('>Populus\natgatgatgtaa\n')};
  await page.locator('#file-input').setInputFiles(fasta);
  await expect(page.locator('#input-checker-list')).toContainText('FASTA alone cannot run plantiSMASH');
  await expect(page.locator('#input-checker-list .blocked')).toHaveCount(1);
  await page.locator('#file-input').setInputFiles({name:'Populus.gbk',mimeType:'text/plain',buffer:Buffer.from(plant)});
  await expect(page.locator('#input-checker-list')).toContainText('sequence and translated CDS matching remain pending');
  await expect(page.locator('#input-checker-list .blocked')).toHaveCount(0);
});

test('saved-run reopening shows plant receipts and counts without changing historical scope',async({page})=>{
  await page.evaluate(()=>{
    const receipt=runSetupReceiptFromJob({analysis_scope:'mixed',taxon_counts:{plants:1,fungi:1,bacteria:1},
      input_summary:{accession_metadata:[{accession:'GCF_000002775.5',taxon_group:'plants',organism_name:'Populus trichocarpa'}]}});
    renderRunSetupAccessPanel({jobId:'SavedPlantFixture00001',receipt,status:'running'});
  });
  await expect(page.locator('#run-setup-analysis-scope')).toHaveText('Mixed · 1 fungi / 1 bacteria / 1 plants');
  await expect(page.locator('#run-setup-input-list .receipt-taxon-chip')).toHaveText('Plants');
  await page.evaluate(()=>{
    const receipt=runSetupReceiptFromJob({analysis_scope:'both',accessions:['GCF_000009045.1']});
    renderRunSetupAccessPanel({jobId:'LegacyFixture00000001',receipt,status:'success'});
  });
  await expect(page.locator('#run-setup-analysis-scope')).toContainText('Both');
});

test('supplied plant incompatibility keeps record protein and reason in submission feedback',async({page})=>{
  const detail='Plant annotation validation: Supplied plant annotation incompatible: NC_037285.2 / CDS 236 / LOC7487044 / XP_024463069.1: complete_cds_has_partial_codon';
  await page.route('**/api/jobs',route=>route.fulfill({status:400,json:{detail}}));
  await page.locator('label').filter({has:page.locator('input[name="analysis-scope"][value="plants"]')}).click();
  await page.locator('#project-name').fill('plant_incompatible');
  await page.locator('#file-input').setInputFiles({name:'Populus.gbk',mimeType:'text/plain',buffer:Buffer.from(plant)});
  await page.locator('#data-use-ack').check();
  await page.locator('#run-btn').click();
  await expect(page.locator('#run-btn')).toHaveText('Submit run');
  await page.locator('#run-btn').click();
  await expect(page.locator('#upload-status')).toContainText(detail);
  await expect(page.locator('#upload-status')).not.toContainText('Annotation required');
});
