'use strict';

const readline = require('readline');
const { chromium } = require('playwright');

const edgePath = process.argv[2];
const profileDir = process.argv[3];
let context;
let page;
let lastContentId = null;

function fail(code, message, retryable = false) {
  const error = new Error(message);
  error.auditCode = code;
  error.retryable = retryable;
  return error;
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

async function extractVisibleExposure() {
  const result = await page.evaluate(() => {
    const vw = innerWidth, vh = innerHeight;
    const rectOf = (el) => el.getBoundingClientRect();
    const visibleArea = (rect) => {
      const w = Math.max(0, Math.min(rect.right, vw) - Math.max(rect.left, 0));
      const h = Math.max(0, Math.min(rect.bottom, vh) - Math.max(rect.top, 0));
      return w * h;
    };
    const isVisible = (el) => {
      const r = rectOf(el), s = getComputedStyle(el);
      return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity || 1) > 0 && visibleArea(r) > 0;
    };
    const idFromHref = (href) => {
      const match = (href || '').match(/aweme_id=(\d{10,})/) ||
                    (href || '').match(/[?&]gid=(\d{10,})/) ||
                    (href || '').match(/\/video\/(\d{10,})/);
      return match ? match[1] : null;
    };
    const videos = [...document.querySelectorAll('video')].filter(isVisible)
      .map(el => ({el, rect: rectOf(el), area: visibleArea(rectOf(el))}))
      .sort((a, b) => b.area - a.area);
    const pageLinks = [...document.querySelectorAll('a[href]')].filter(isVisible);
    const visibleIdLinks = [];
    for (const anchor of pageLinks) {
      const id = idFromHref(anchor.href || '');
      if (id) visibleIdLinks.push({el: anchor, id, rect: rectOf(anchor)});
    }
    // Douyin keeps the previous and next cards mounted at the same time. DOM
    // order therefore does not reliably identify the card the user is seeing.
    // Start at the visual centre of the player and climb to the smallest large
    // ancestor that owns content-ID links. This anchors extraction to the
    // actual card under the user's eyes.
    let centerRoot = null;
    const centerHits = document.elementsFromPoint(vw * 0.55, vh * 0.45);
    outer: for (const hit of centerHits) {
      for (let p = hit; p && p !== document.body && p !== document.documentElement; p = p.parentElement) {
        const r = rectOf(p);
        if (visibleArea(r) < vw * vh * 0.12) continue;
        const ownedIds = [...p.querySelectorAll('a[href]')]
          .filter(isVisible).map(a => idFromHref(a.href || '')).filter(Boolean);
        if (ownedIds.length) {
          centerRoot = p;
          break outer;
        }
      }
    }
    const usableVideo = videos.length && videos[0].area >= vw * vh * 0.08 ? videos[0] : null;
    if (!centerRoot && !usableVideo && !visibleIdLinks.length) {
      return {__audit_error: {code: 'FEED_NOT_READY', message: '当前页面没有足够大的可见视频',
                              retryable: true, page_url: location.href, document_title: document.title,
                              body_text: (document.body?.innerText || '').slice(0, 1200)}};
    }
    const focus = centerRoot || (usableVideo ? usableVideo.el : visibleIdLinks[0].el);
    const focusRect = centerRoot ? rectOf(centerRoot) : (usableVideo ? usableVideo.rect : visibleIdLinks[0].rect);
    const focusArea = centerRoot ? visibleArea(focusRect) :
      (usableVideo ? usableVideo.area : Math.max(1, visibleArea(focusRect)));
    let root = focus;
    if (!centerRoot) {
      for (let p = focus.parentElement; p; p = p.parentElement) {
        if (p === document.body || p === document.documentElement) break;
        const area = visibleArea(rectOf(p));
        const text = p.innerText || '';
        if (text.includes('京ICP备') || text.includes('信息网络传播视听节目许可证')) break;
        if (area >= focusArea * 0.85 && area <= vw * vh * 1.25) root = p;
      }
    }
    const rootText = (root.innerText || '').trim();
    const links = [...root.querySelectorAll('a[href]')].filter(isVisible);
    const idCandidates = [];
    for (const a of links) {
      const href = a.href || '';
      const id = idFromHref(href);
      if (id) idCandidates.push({id, href, rect: rectOf(a)});
    }
    const idStats = new Map();
    for (const candidate of idCandidates) {
      const stat = idStats.get(candidate.id) || {count: 0, distance: 0};
      stat.count += 1;
      stat.distance += Math.abs(candidate.rect.top - vh * 0.78);
      idStats.set(candidate.id, stat);
    }
    const contentId = [...idStats.entries()].sort((a, b) =>
      b[1].count - a[1].count || a[1].distance - b[1].distance
    )[0]?.[0] || null;
    const authorNodes = [...root.querySelectorAll('span,p,div')].filter(el => {
      if (!isVisible(el)) return false;
      const text = (el.innerText || '').trim();
      const r = rectOf(el);
      return text.startsWith('@') && text.length < 80 && !text.includes('\n') &&
             r.left > vw * 0.06 && r.left < vw * 0.75 && r.top > vh * 0.4;
    }).sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);
    const authorNode = authorNodes[0];
    const authorRect = authorNode ? rectOf(authorNode) : focusRect;
    const authorLinks = links.filter(a => /\/user\//.test(a.href || '') && !/\/user\/self/.test(a.href || ''))
      .sort((a, b) => Math.abs(rectOf(a).top - authorRect.top) - Math.abs(rectOf(b).top - authorRect.top));
    const authorLink = authorLinks[0];
    const creatorMatch = authorLink?.href?.match(/\/user\/([^/?#]+)/);
    const creatorId = creatorMatch ? creatorMatch[1] : null;
    const author = (authorNode?.innerText || authorLink?.innerText || '').trim().replace(/^@/, '') || null;
    const leaves = [...root.querySelectorAll('span,p,div')].filter(el => {
      if (!isVisible(el) || el.children.length > 2) return false;
      const text = (el.innerText || '').trim();
      if (text.length < 4 || text.length > 800) return false;
      const r = rectOf(el);
      return r.left > vw * 0.06 && r.left < vw * 0.72 && r.top > vh * 0.45 &&
             !text.includes('京ICP备') && text.split('\n').length <= 4;
    }).map(el => {
      const text = (el.innerText || '').trim();
      const r = rectOf(el);
      let score = Math.min(text.length, 160);
      if (text.includes('#')) score += 80;
      if (text.startsWith('@')) score -= 100;
      if (/^\d+(\.\d+)?万?$/.test(text) || /^\d{1,2}:\d{2}/.test(text)) score -= 120;
      if (/^(发送|倍速|智能|清屏|连播|听抖音|展开)$/.test(text)) score -= 120;
      score += Math.max(0, 40 - Math.abs(r.top - vh * 0.82) / 12);
      return {text, score};
    }).sort((a, b) => b.score - a.score);
    let title = leaves[0]?.text || null;
    if (title && author && title.startsWith('@' + author)) title = title.slice(author.length + 1).trim();
    // Prefer the complete visible caption block after the author/date marker.
    // A caption can start with hashtags and put its actual title on the next
    // line; scoring a single leaf used to lose that trailing title.
    const rootLines = rootText.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    const authorLineIndex = rootLines.findIndex(line => author && line === `@${author}`);
    if (authorLineIndex >= 0) {
      const captionLines = [];
      for (let i = authorLineIndex + 1; i < rootLines.length; i += 1) {
        const line = rootLines[i];
        if (/^[·•]?\s*(\d+\s*(秒|分钟|小时|天|周|月|年)前|\d{1,2}月\d{1,2}日)$/.test(line)) continue;
        if (/^\d{1,2}:\d{2}\s*\/\s*\d{1,2}:\d{2}$/.test(line) ||
            /^(发送|倍速|智能|清屏|连播|听抖音|展开|下一集)$/.test(line) ||
            line.startsWith('作者声明')) break;
        captionLines.push(line);
      }
      if (captionLines.length) title = captionLines.join('\n');
    }
    const visibleAdLabel = /(^|\s)(广告|赞助|推广|品牌广告|购物)(\s|$)/m.test(rootText);
    const fraction = usableVideo ?
      Math.min(1, usableVideo.area / Math.max(1, usableVideo.rect.width * usableVideo.rect.height)) :
      Math.min(1, visibleArea(rectOf(root)) / Math.max(1, vw * vh));
    return {
      content_id: contentId, creator_id: creatorId, author, title_or_text: title,
      content_type: 'video',
      url_or_internal_id: contentId ? `https://www.douyin.com/video/${contentId}` : location.href,
      sponsored: visibleAdLabel ? true : null, visible_ad_label: visibleAdLabel,
      exposure_unit: 'visible_video', view_id: contentId, slot_index: 0,
      visible_fraction: Number(fraction.toFixed(4)), page_url: location.href,
      document_title: document.title,
      video_duration_seconds: usableVideo && Number.isFinite(usableVideo.el.duration) ? usableVideo.el.duration : null,
      video_current_time_seconds: usableVideo && Number.isFinite(usableVideo.el.currentTime) ? usableVideo.el.currentTime : null,
      extraction_basis: centerRoot ? 'rendered_dom_and_visual_center_card' :
        (usableVideo ? 'rendered_dom_and_visible_video' : 'rendered_dom_and_visible_content_link'),
      raw_visible_text: rootText.slice(0, 4000),
    };
  });
  if (result && result.__audit_error) {
    const detail = result.__audit_error;
    throw fail(detail.code, `${detail.message}；URL=${detail.page_url}；标题=${detail.document_title}；页面=${detail.body_text}`,
               !!detail.retryable);
  }
  return result;
}

async function handle(req) {
  await ensureBrowser();
  if (req.action === 'open') {
    const current = new URL(page.url());
    const requested = new URL(req.url);
    if (current.origin !== requested.origin || current.pathname !== requested.pathname ||
        current.searchParams.get('recommend') !== requested.searchParams.get('recommend')) {
      await page.goto(req.url, {waitUntil: 'domcontentloaded', timeout: req.timeout_ms || 45000});
    }
    await page.bringToFront();
    await page.waitForTimeout(2500);
    const readLoginState = async () => {
      for (let attempt = 0; attempt < 20; attempt += 1) {
        try {
          return await page.evaluate(() => ({
            url: location.href,
            loginVisible: [...document.querySelectorAll('button,a,div')].some(el => {
              const r = el.getBoundingClientRect();
              return (el.innerText || '').trim() === '登录' && r.width > 0 && r.height > 0;
            }),
          }));
        } catch (error) {
          if (!String(error.message || error).includes('Execution context was destroyed')) throw error;
          await page.waitForTimeout(300);
        }
      }
      throw fail('PAGE_NAVIGATION_UNSTABLE', '登录跳转后页面执行上下文持续不可用', true);
    };
    let loginState = await readLoginState();
    if (loginState.loginVisible && req.login_wait_ms > 0) {
      await page.evaluate(() => {
        document.title = `【专用采集登录】${document.title.replace(/^【专用采集登录】/, '')}`;
      });
      await page.bringToFront();
      const loginDeadline = Date.now() + req.login_wait_ms;
      while (Date.now() < loginDeadline && loginState.loginVisible) {
        await page.waitForTimeout(1000);
        loginState = await readLoginState();
        if (loginState.loginVisible) {
          await page.evaluate(() => {
            document.title = `【专用采集登录】${document.title.replace(/^【专用采集登录】/, '')}`;
          });
        }
      }
      if (!loginState.loginVisible) {
        await page.goto(req.url, {waitUntil: 'domcontentloaded', timeout: req.timeout_ms || 45000});
        await page.waitForTimeout(2500);
        loginState = await readLoginState();
      }
    }
    if (loginState.loginVisible && !new URL(loginState.url).searchParams.has('recommend')) {
      throw fail('LOGIN_REQUIRED',
                 `独立Edge测试资料尚未登录，抖音把推荐入口重定向到了${loginState.url}。登录一次后该资料会持久保存会话。`);
    }
    if (!loginState.loginVisible && new URL(loginState.url).pathname === '/jingxuan') {
      const recommendLink = page.locator('a[href*="recommend=1"]', {hasText: '推荐'}).first();
      if (await recommendLink.isVisible()) {
        await recommendLink.click();
        await page.waitForTimeout(3000);
        loginState = await readLoginState();
      }
    }
    let metadata;
    const readyDeadline = Date.now() + 20000;
    while (Date.now() < readyDeadline) {
      try {
        metadata = await extractVisibleExposure();
        if (metadata.content_id) break;
      } catch (error) {
        if (!error.retryable) throw error;
      }
      await page.waitForTimeout(500);
    }
    if (!metadata || !metadata.content_id) {
      throw fail('FEED_NOT_READY', '推荐页在20秒内未出现可核验的当前内容ID', true);
    }
    lastContentId = metadata.content_id;
    return {feed_ready: !!lastContentId, content_id: lastContentId, page_url: page.url()};
  }
  if (req.action === 'read_current') {
    const metadata = await extractVisibleExposure();
    if (!metadata.content_id) throw fail('EXPOSURE_NOT_IDENTIFIED', '未从当前可见卡片中提取到内容ID', true);
    if (req.evidence_path) await page.screenshot({path: req.evidence_path, fullPage: false});
    lastContentId = metadata.content_id;
    return {metadata};
  }
  if (req.action === 'advance_once') {
    const before = lastContentId || (await extractVisibleExposure()).content_id;
    await page.bringToFront();
    const viewport = await page.evaluate(() => ({width: innerWidth, height: innerHeight}));
    const waitForChange = async (timeoutMs) => {
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        await page.waitForTimeout(350);
        try {
          const current = await extractVisibleExposure();
          if (current.content_id && current.content_id !== before) return current.content_id;
        } catch (_) {}
      }
      return null;
    };
    // The down control sits about 64 px from the right edge in the responsive
    // desktop layout. Retry a bounded sequence because hover overlays can
    // briefly intercept one input. Every action is verified by a content-ID
    // change before another action is sent.
    let after = null;
    for (let attempt = 0; attempt < 3 && !after; attempt += 1) {
      await page.mouse.move(viewport.width - 64, viewport.height * 0.66);
      await page.mouse.click(viewport.width - 64, viewport.height * 0.66);
      after = await waitForChange(4000);
      if (after) break;
      await page.mouse.move(viewport.width * 0.58, viewport.height * 0.52);
      await page.mouse.wheel(0, Math.max(650, viewport.height * 0.92));
      after = await waitForChange(4000);
      if (after) break;
      await page.keyboard.press(attempt % 2 === 0 ? 'ArrowDown' : 'PageDown');
      after = await waitForChange(4000);
    }
    if (after) {
      lastContentId = after;
      return {before, after};
    }
    throw fail('ADVANCE_NOT_CONFIRMED', `向下翻页后内容ID仍为${before || '未知'}`);
  }
  if (req.action === 'health') {
    const metadata = await extractVisibleExposure();
    return {feed_ready: !!metadata.content_id, content_id: metadata.content_id, page_url: page.url()};
  }
  if (req.action === 'close') {
    await context.close(); context = null; return {closed: true};
  }
  throw fail('BROWSER_PROTOCOL_ERROR', `未知命令: ${req.action}`);
}

const rl = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
rl.on('line', async (line) => {
  let req;
  try {
    req = JSON.parse(line);
    const result = await handle(req);
    process.stdout.write(JSON.stringify({id: req.id, ok: true, result}) + '\n');
  } catch (error) {
    const code = error.auditCode || 'BROWSER_AUTOMATION_FAILED';
    process.stdout.write(JSON.stringify({id: req?.id, ok: false, error: {
      code, message: String(error.message || error), retryable: !!error.retryable,
    }}) + '\n');
  }
});
