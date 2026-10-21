'use strict';

const readline = require('readline');
const { chromium } = require('playwright');

const edgePath = process.argv[2];
const profileDir = process.argv[3];
let context;
let page;
let homePage;
let lastContentId = null;
const visited = new Set();

function fail(code, message, retryable = false) {
  const error = new Error(message);
  error.auditCode = code;
  error.retryable = retryable;
  return error;
}

function videoId(url) {
  const match = String(url || '').match(/\/video\/(BV[0-9A-Za-z]+|av\d+)/i);
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
  homePage = page;
  page.setDefaultTimeout(15000);
}

async function loginVisible() {
  return page.evaluate(() => [...document.querySelectorAll('button,a,div,span')].some(el => {
    const r = el.getBoundingClientRect();
    const text = (el.innerText || '').trim();
    return text === '登录' && r.width > 0 && r.height > 0 && r.top >= 0 && r.top < innerHeight;
  }));
}

async function detailMetadata() {
  await page.waitForLoadState('domcontentloaded').catch(() => null);
  const result = await page.evaluate(() => {
    const clean = value => String(value || '').replace(/\s+/g, ' ').trim() || null;
    const fromUrl = value => {
      const m = String(value || '').match(/\/video\/(BV[0-9A-Za-z]+|av\d+)/i);
      return m ? m[1] : null;
    };
    const meta = key => document.querySelector(`meta[property="${key}"],meta[name="${key}"]`)?.content || null;
    const contentId = fromUrl(location.href) || fromUrl(document.querySelector('link[rel="canonical"]')?.href);
    const pick = selectors => {
      for (const selector of selectors) {
        const el = document.querySelector(selector);
        const value = clean(el?.innerText || el?.textContent);
        if (value) return value;
      }
      return null;
    };
    let title = pick(['h1.video-title', 'h1[title]', '.video-title', '[data-title]']) ||
      clean(meta('og:title')) || clean(document.title);
    if (title) title = title.replace(/_哔哩哔哩.*$/u, '').trim() || null;
    let captionText = pick([
      '.video-desc-container .desc-info-text', '.video-desc-container .desc-info',
      '.basic-desc-info', '#v_desc .desc-info-text', '.desc-info-text'
    ]);
    if (captionText === '-' || captionText === '暂无简介') captionText = null;
    const tags = [];
    const addTag = value => {
      const tag = clean(value)?.replace(/^#+/, '');
      if (tag && tag.length <= 80 && !tags.includes(tag)) tags.push(tag);
    };
    for (const el of document.querySelectorAll(
      '.tag-panel .tag-link, .video-tag-container .tag-link, .tag-wrap .tag-link, .tag-wrap a'
    )) addTag(el.innerText || el.textContent);
    // Metadata keywords include generic site terms and sometimes repeat the
    // title. Use them only as a last resort when the visible tag panel is empty.
    if (!tags.length) {
      for (const value of String(meta('keywords') || '').split(/[,，]/)) {
        const normalized = clean(value);
        if (!normalized || normalized === title || /^(哔哩哔哩|bilibili|B站|弹幕)$/i.test(normalized)) continue;
        addTag(normalized);
      }
    }
    return {content_id: contentId, title, caption_text: captionText, tags, content_type: 'video'};
  });
  if (!result.content_id) throw fail('EXPOSURE_NOT_IDENTIFIED', '视频页中没有可核验的BV/av内容ID', true);
  if (!result.title) throw fail('CONTENT_NOT_READY', '视频标题尚未加载', true);
  return result;
}

async function adoptOpenedPage(beforePages) {
  const deadline = Date.now() + 8000;
  while (Date.now() < deadline) {
    const pages = context.pages();
    const created = pages.find(candidate => !beforePages.includes(candidate));
    if (created) {
      page = created;
      page.setDefaultTimeout(15000);
      await page.bringToFront();
      return;
    }
    if (videoId(page.url())) return;
    await page.waitForTimeout(300);
  }
}

async function openNextCard() {
  page = homePage;
  await page.bringToFront();
  for (let scrollRound = 0; scrollRound < 15; scrollRound += 1) {
    const candidates = await page.evaluate(visitedIds => {
      const seen = new Set(visitedIds);
      const rows = [];
      const idFrom = value => {
        const m = String(value || '').match(/\/video\/(BV[0-9A-Za-z]+|av\d+)/i);
        return m ? m[1] : null;
      };
      for (const a of document.querySelectorAll('a[href*="/video/"]')) {
        const id = idFrom(a.href);
        if (!id || seen.has(id)) continue;
        const r = a.getBoundingClientRect();
        if (r.width < 90 || r.height < 55 || r.bottom <= 100 || r.top >= innerHeight) continue;
        rows.push({id, x: r.left + Math.min(r.width / 2, 220), y: r.top + Math.min(r.height / 2, 150),
                   top: r.top, left: r.left});
      }
      rows.sort((a, b) => a.top - b.top || a.left - b.left);
      return rows.filter((row, index, all) => all.findIndex(other => other.id === row.id) === index);
    }, [...visited]);
    for (const target of candidates.slice(0, 6)) {
      const beforePages = context.pages();
      await page.mouse.click(target.x, target.y);
      await adoptOpenedPage(beforePages);
      const current = videoId(page.url());
      if (current) {
        visited.add(current);
        lastContentId = current;
        return current;
      }
      visited.add(target.id);
      page = homePage;
      await page.bringToFront();
    }
    const amount = await page.evaluate(() => Math.max(650, innerHeight * 0.85));
    await page.mouse.wheel(0, amount);
    await page.waitForTimeout(900);
  }
  throw fail('NO_UNVISITED_CARD', '连续滚动后没有找到新的可见视频卡片');
}

async function returnHome() {
  if (page !== homePage && !page.isClosed()) {
    await page.close();
    page = homePage;
  } else if (videoId(page.url())) {
    await page.goBack({waitUntil: 'domcontentloaded', timeout: 15000}).catch(() => null);
  }
  await homePage.bringToFront();
  page = homePage;
  await page.waitForTimeout(900);
  if (videoId(page.url())) throw fail('RETURN_NOT_CONFIRMED', '无法确认已从视频页返回首页');
}

async function handle(req) {
  await ensureBrowser();
  if (req.action === 'open') {
    if (!page.url().startsWith('https://www.bilibili.com')) {
      await page.goto(req.url, {waitUntil: 'domcontentloaded', timeout: req.timeout_ms || 45000});
    }
    homePage = page;
    await page.bringToFront();
    await page.waitForTimeout(2500);
    let needsLogin = await loginVisible();
    if (needsLogin && req.login_wait_ms > 0) {
      const deadline = Date.now() + req.login_wait_ms;
      while (Date.now() < deadline && needsLogin) {
        await page.waitForTimeout(1000);
        needsLogin = await loginVisible();
      }
    }
    if (needsLogin) throw fail('LOGIN_REQUIRED', '哔哩哔哩专用Edge资料尚未登录，请先完成登录');
    if (videoId(page.url())) await returnHome();
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
    await returnHome();
    const after = await openNextCard();
    if (!after || after === before) throw fail('ADVANCE_NOT_CONFIRMED', '下一条视频ID没有变化');
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
