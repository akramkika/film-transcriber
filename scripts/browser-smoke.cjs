// Optional manual end-to-end check. Requires Playwright with Microsoft Edge installed.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    const base = process.env.FILM_TEST_URL || 'http://127.0.0.1:8001';
    await page.goto(base);
    await page.locator('#video-file').setInputFiles(path.resolve('artifacts/smoke/scene-test.mp4'));
    await page.locator('#start-seconds').fill('2');
    const created = page.waitForResponse(response => response.url() === `${base}/api/jobs` && response.request().method() === 'POST');
    await page.locator('#transcribe').click();
    const response = await created;
    assert.equal(response.status(), 202);
    const jobId = (await response.json()).id;
    await page.locator('#job-status[data-status="COMPLETED"], #job-status[data-status="FAILED"]').waitFor({ timeout: 240000 });
    const job = await (await page.request.get(`${base}/api/jobs/${jobId}`)).json();
    assert.equal(job.status, 'COMPLETED', job.error?.message);
    assert.ok(job.result.segments.length > 0, 'Real speech must produce segments');
    const segments = job.result.segments;
    const offset = job.result.scene_start_seconds;
    await page.locator('#video').evaluate(video => { video.muted = true; video.currentTime = 0; });
    await page.waitForTimeout(200);
    assert.equal(await page.locator('.segment.active').count(), 0, 'No segment before scene');
    await page.locator('.segment-time').last().click();
    const lastTime = await page.locator('#video').evaluate(video => video.currentTime);
    assert.ok(Math.abs(lastTime - (offset + segments.at(-1).start)) < 0.1, 'Seek uses scene offset');
    await page.locator('.segment-time').first().click();
    await page.waitForTimeout(300);
    assert.ok(await page.locator('.segment').first().evaluate(row => row.classList.contains('active')));
    await page.locator('#video').evaluate(async video => { video.playbackRate = 2; await video.play(); });
    await page.waitForTimeout(900);
    await page.locator('#video').evaluate(video => video.pause());
    const paused = await page.locator('#video').evaluate(video => video.currentTime);
    await page.waitForTimeout(300);
    assert.equal(await page.locator('#video').evaluate(video => video.currentTime), paused);
    for (const format of ['txt', 'srt', 'json']) {
      const exported = await page.request.get(`${base}/api/jobs/${jobId}/exports/${format}`);
      assert.equal(exported.status(), 200);
      assert.ok((await exported.body()).length > 0);
    }
    const videoBox = await page.locator('#video').boundingBox();
    const textBox = await page.locator('#transcript-scroll').boundingBox();
    assert.ok(videoBox.x + videoBox.width <= textBox.x, 'Desktop panels sit side by side');
    await page.screenshot({ path: 'artifacts/ui-desktop.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: 'artifacts/ui-mobile.png', fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No mobile overflow');
    assert.deepEqual(errors, []);
    const summary = { status: 'passed', job_id: jobId, segments: segments.length, language: job.result.language, metrics: job.result.metrics, checks: ['real ASR', 'offset seek', 'silence before scene', 'playback x2', 'pause', 'exports', 'desktop split', 'mobile layout', 'no JS errors'] };
    await fs.writeFile('artifacts/smoke-result.json', JSON.stringify(summary, null, 2));
    console.log(JSON.stringify(summary));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
