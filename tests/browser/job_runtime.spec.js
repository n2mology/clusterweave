const {test, expect} = require('@playwright/test');

async function openClock(page, pollDelay = 1500) {
  await page.goto('http://127.0.0.1:4173/assets/progress-tree-contract.json');
  await page.clock.install({time: new Date('2026-01-01T00:00:00Z')});
  await page.clock.pauseAt(new Date('2026-01-01T00:00:01Z'));
  await page.setContent('<time id="results-job-runtime" hidden></time>');
  await page.evaluate(async pollDelay => {
    const {createJobLifecycleBoundary, createJobLifecycleControllerBoundary} = await import('/assets/job-lifecycle-boundary.js');
    const timer = document.getElementById('results-job-runtime');
    const text = Object.getOwnPropertyDescriptor(Node.prototype, 'textContent');
    const writes = [];
    Object.defineProperty(timer, 'textContent', {
      get() {return text.get.call(this);},
      set(value) {
        writes.push({at: Date.now(), value});
        text.set.call(this, value);
      },
    });
    const state = {activeJobMeta: null, activeStageState: null};
    const policy = createJobLifecycleBoundary({stages: []});
    const controller = createJobLifecycleControllerBoundary({state, lifecyclePolicy: policy,
      capabilities: {syncClusterweaveGameHost() {}}, stages: []});
    const origin = Date.now();
    const select = job => {
      state.activeJobMeta = job;
      controller.renderJobRuntime(job);
    };
    globalThis.runtimeFixture = {state, controller, writes, origin, select};
    select({id: 'first', status: 'running', started_at: new Date(origin - 600).toISOString()});
    controller.startStageTicker();
    globalThis.runtimePolls = 0;
    setInterval(() => {
      globalThis.runtimePolls++;
      if (state.activeJobMeta) controller.setWorkflowExperienceState({...state.activeJobMeta});
    }, pollDelay);
  }, pollDelay);
}

for (const pollDelay of [1500, 3000]) {
  test(`runtime seconds stay evenly spaced with ${pollDelay} ms polling`, async ({page}) => {
    await openClock(page, pollDelay);
    await page.clock.runFor(10000);
    const observed = await page.evaluate(() => ({
      times: runtimeFixture.writes.map(row => row.at - runtimeFixture.origin),
      values: runtimeFixture.writes.map(row => row.value),
      polls: runtimePolls,
    }));
    expect(observed.times).toEqual([0, ...Array.from({length: 10}, (_, i) => 400 + i * 1000)]);
    expect(observed.polls).toBe(Math.floor(10000 / pollDelay));
    expect(new Set(observed.values).size).toBe(11);
    await expect(page.locator('time')).toHaveText('(00:00:00:10)');
    await expect(page.locator('time')).toHaveAttribute('datetime', 'PT10S');
  });
}

test('runtime switches job and rerun clocks, freezes terminal time, and clears on idle', async ({page}) => {
  await openClock(page);
  await page.clock.runFor(1200);
  await page.evaluate(() => runtimeFixture.select({id: 'second', status: 'pending',
    created_at: new Date(Date.now() - 2200).toISOString()}));
  await expect(page.locator('time')).toHaveText('(00:00:00:02)');
  const switched = await page.evaluate(() => runtimeFixture.writes.length);
  await page.clock.runFor(799);
  expect(await page.evaluate(() => runtimeFixture.writes.length)).toBe(switched);
  await page.clock.runFor(1);
  await expect(page.locator('time')).toHaveText('(00:00:00:03)');
  await page.evaluate(() => runtimeFixture.select({...runtimeFixture.state.activeJobMeta,
    status: 'success', completed_at: new Date(Date.now() - 1000).toISOString()}));
  await expect(page.locator('time')).toHaveText('(00:00:00:02)');
  await expect(page.locator('time')).toHaveAttribute('title', 'Final total job runtime');
  const frozen = await page.evaluate(() => runtimeFixture.writes.length);
  await page.clock.runFor(5000);
  expect(await page.evaluate(() => runtimeFixture.writes.length)).toBe(frozen);
  await page.evaluate(() => runtimeFixture.select({id: 'second', status: 'running',
    started_at: new Date(Date.now() - 250).toISOString()}));
  await expect(page.locator('time')).toHaveText('(00:00:00:00)');
  await page.clock.runFor(750);
  await expect(page.locator('time')).toHaveText('(00:00:00:01)');
  await page.evaluate(() => runtimeFixture.select(null));
  await expect(page.locator('time')).toBeHidden();
  await expect(page.locator('time')).not.toHaveAttribute('datetime');
  const idle = await page.evaluate(() => runtimeFixture.writes.length);
  await page.clock.runFor(4000);
  expect(await page.evaluate(() => runtimeFixture.writes.length)).toBe(idle);
});

test('runtime catches up after a suspended tab and realigns the next second', async ({page}) => {
  await openClock(page);
  await page.clock.runFor(400);
  await page.clock.setSystemTime(new Date('2026-01-01T01:00:01.350Z'));
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  await expect(page.locator('time')).toHaveText('(00:01:00:00)');
  const resumed = await page.evaluate(() => runtimeFixture.writes.length);
  await page.clock.runFor(49);
  expect(await page.evaluate(() => runtimeFixture.writes.length)).toBe(resumed);
  await page.clock.runFor(1);
  await expect(page.locator('time')).toHaveText('(00:01:00:01)');
  await page.clock.runFor(1000);
  await expect(page.locator('time')).toHaveText('(00:01:00:02)');
});
