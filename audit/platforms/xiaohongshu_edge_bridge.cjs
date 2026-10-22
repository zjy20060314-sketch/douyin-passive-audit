'use strict';

const readline = require('readline');
const { chromium } = require('playwright');

const edgePath = process.argv[2];
const profileDir = process.argv[3];
let context;
let page;
let lastContentId = null;
const visited = new Set();
let siteUrl = 'https://www.xiaohongshu.com/explore';

function fail(code, message, retryable = false) {
  const error = new Error(message);
  error.auditCode = code;
  error.retryable = retryable;
  return error;
}

function noteId(url) {
  const match = String(url || '').match(/\/(?:explore|discovery\/item)\/([0-9a-zA-Z]+)/);
  return match ? match[1] : null;
}

async function ensureBrowser() {
  if (context) return;
  context = await chromium.launchPersistentContext(profileDir, {
    executablePath: edgePath,
    headless: false,
    viewport: null,
    args: ['--start-maximized', '--no-first-run', '--disable-features=msEdgeSidebarV2'],
  });
  page = context.pages()[0] || await context.newPage();
  page.setDefaultTimeout(15000);
}

async function loginVisible() {
  return page.evaluate(() => [...document.querySelectorAll('button,a,div')].some(el => {
    const r = el.getBoundingClientRect();
    const text = (el.innerText || '').trim().toLowerCase();
    return ['登录', 'log in', 'login'].includes(text) && r.width > 0 && r.height > 0;
  }));
}

function sameSite(current, target) {
  try {
    return new URL(current).hostname === new URL(target).hostname;
  } catch (_) {
    return false;
  }
}

async function detailMetadata() {
  const result = await page.evaluate(() => {
    const isVisible = el => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight &&
        s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity || 1) > 0;
    };
    const idFrom = value => {
      const m = String(value || '').match(/\/(?:explore|discovery\/item)\/([0-9a-zA-Z]+)/);
      return m ? m[1] : null;
    };
    const contentId = idFrom(location.href) || [...document.querySelectorAll('link[rel="canonical"],a[href]')]
      .map(el => idFrom(el.href)).find(Boolean) || null;
    const pickText = list => {
      for (const selector of list) {
        const candidates = [...document.querySelectorAll(selector)].filter(isVisible)
          .map(el => (el.innerText || el.textContent || '').trim()).filter(Boolean)
          .sort((a, b) => a.length - b.length);
        if (candidates.length) return candidates[0];
      }
      return null;
    };
    const title = pickText([
      '#detail-title', '.note-content .title', '.note-detail-mask .title',
      '[class*="note"] [class*="title"]'
    ]);
    const captionText = pickText([
      '#detail-desc', '.note-content .desc', '.note-detail-mask .desc',
      '[class*="note"] [class*="desc"]'
    ]);
    const tagLinks = [...document.querySelectorAll('a[href]')].filter(isVisible).filter(a => {
      const text = (a.innerText || a.textContent || '').trim();
      return text.startsWith('#') && text.length > 1 && text.length < 100;
    });
    const tags = [];
    for (const link of tagLinks) {
      const tag = (link.innerText || link.textContent || '').trim().replace(/^#+/, '');
      if (tag && !tags.includes(tag)) tags.push(tag);
    }
    const visibleVideos = [...document.querySelectorAll('video')].filter(isVisible);
    const visibleImages = [...document.querySelectorAll('img')].filter(isVisible).filter(img => {
      const r = img.getBoundingClientRect();
      return r.width >= 180 && r.height >= 180;
    });
    const contentType = visibleVideos.length ? 'video' : (visibleImages.length ? 'image_text' : null);
    return {
      content_id: contentId,
      title,
      caption_text: captionText,
      tags,
      content_type: contentType,
    };
  });
  if (!result.content_id) throw fail('EXPOSURE_NOT_IDENTIFIED', '详情弹窗中没有可核验的笔记ID', true);
  return result;
}

async function openNextCard() {
  for (let scrollRound = 0; scrollRound < 12; scrollRound += 1) {
    const candidates = await page.evaluate(visitedIds => {
      const seen = new Set(visitedIds);
      const rows = [];
      for (const a of document.querySelectorAll(
        'a[href*="/explore/"], a[href*="/discovery/item/"]'
      )) {
        const m = String(a.href || '').match(/\/(?:explore|discovery\/item)\/([0-9a-zA-Z]+)/);
        if (!m || seen.has(m[1])) continue;
        const r = a.getBoundingClientRect();
        if (r.width < 80 || r.height < 80 || r.bottom <= 80 || r.top >= innerHeight) continue;
        rows.push({id: m[1], x: r.left + r.width / 2, y: r.top + Math.min(r.height / 2, 220),
                   top: r.top, left: r.left});
      }
      rows.sort((a, b) => a.top - b.top || a.left - b.left);
      return rows;
    }, [...visited]);
    if (candidates.length) {
      // Use the same visible click as a person. Sticky controls can cover an
      // occasional card, so skip that card after one bounded attempt instead
      // of aborting the whole passive session.
      for (const target of candidates.slice(0, 4)) {
        await page.mouse.click(target.x, target.y);
        const deadline = Date.now() + 5000;
        while (Date.now() < deadline) {
          await page.waitForTimeout(350);
          const current = noteId(page.url());
          if (current) {
            visited.add(current);
            lastContentId = current;
            return current;
          }
        }
        visited.add(target.id);
      }
      continue;
    }
    const amount = await page.evaluate(() => Math.max(650, innerHeight * 0.85));
    await page.mouse.wheel(0, amount);
    await page.waitForTimeout(900);
  }
  throw fail('NO_UNVISITED_CARD', '连续滚动后没有找到新的可见笔记卡片');
}

async function returnToExplore() {
  if (!noteId(page.url())) return;
  await page.goBack({waitUntil: 'domcontentloaded', timeout: 15000}).catch(() => null);
  await page.waitForTimeout(800);
  if (noteId(page.url())) {
    await page.keyboard.press('Escape');
    await page.waitForTimeout(600);
  }
  if (noteId(page.url())) throw fail('RETURN_NOT_CONFIRMED', '无法确认已从详情返回发现页');
}

async function handle(req) {
  await ensureBrowser();
  if (req.action === 'launch') {
    siteUrl = req.url || siteUrl;
    if (!sameSite(page.url(), siteUrl) || noteId(page.url())) {
      await page.goto(siteUrl, {waitUntil: 'domcontentloaded', timeout: req.timeout_ms || 45000});
    }
    await page.bringToFront();
    await page.waitForTimeout(1200);
    return {page_ready: true, needs_login: await loginVisible(), page_url: page.url()};
  }
  if (req.action === 'prepare') {
    siteUrl = req.url || siteUrl;
    await page.bringToFront();
    if (noteId(page.url())) await returnToExplore();
    if (!sameSite(page.url(), siteUrl)) {
      await page.goto(siteUrl, {
        waitUntil: 'domcontentloaded', timeout: req.timeout_ms || 45000,
      });
      await page.waitForTimeout(2200);
    }
    if (await loginVisible()) {
      throw fail('LOGIN_REQUIRED', 'RedNote/小红书专用Edge资料尚未登录，请先完成登录');
    }
    const id = await openNextCard();
    return {detail_ready: true, content_id: id, page_url: page.url()};
  }
  if (req.action === 'open') {
    siteUrl = req.url || siteUrl;
    if (!sameSite(page.url(), siteUrl) || noteId(page.url())) {
      await page.goto(siteUrl, {waitUntil: 'domcontentloaded', timeout: req.timeout_ms || 45000});
    }
    await page.bringToFront();
    await page.waitForTimeout(2200);
    let needsLogin = await loginVisible();
    if (needsLogin && req.login_wait_ms > 0) {
      const deadline = Date.now() + req.login_wait_ms;
      while (Date.now() < deadline && needsLogin) {
        await page.waitForTimeout(1000);
        needsLogin = await loginVisible();
      }
    }
    if (needsLogin) throw fail('LOGIN_REQUIRED', 'RedNote/小红书专用Edge资料尚未登录，请先完成登录');
    if (noteId(page.url())) await returnToExplore();
    const id = await openNextCard();
    return {detail_ready: true, content_id: id, page_url: page.url()};
  }
  if (req.action === 'read_current') {
    const metadata = await detailMetadata();
    if (req.evidence_path) await page.screenshot({path: req.evidence_path, fullPage: false});
    lastContentId = metadata.content_id;
    visited.add(lastContentId);
    return {metadata};
  }
  if (req.action === 'advance_once') {
    const before = lastContentId;
    await returnToExplore();
    const after = await openNextCard();
    if (!after || after === before) throw fail('ADVANCE_NOT_CONFIRMED', '下一条笔记ID没有变化');
    return {before, after};
  }
  if (req.action === 'health') {
    const metadata = await detailMetadata();
    return {detail_ready: !!metadata.content_id, content_id: metadata.content_id, page_url: page.url()};
  }
  if (req.action === 'close') {
    await context.close(); context = null; return {closed: true};
  }
  throw fail('BROWSER_PROTOCOL_ERROR', `未知命令: ${req.action}`);
}

const rl = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
rl.on('line', async line => {
  let req;
  try {
    req = JSON.parse(line);
    const result = await handle(req);
    process.stdout.write(JSON.stringify({id: req.id, ok: true, result}) + '\n');
  } catch (error) {
    process.stdout.write(JSON.stringify({id: req?.id, ok: false, error: {
      code: error.auditCode || 'BROWSER_AUTOMATION_FAILED',
      message: String(error.message || error), retryable: !!error.retryable,
    }}) + '\n');
  }
});
