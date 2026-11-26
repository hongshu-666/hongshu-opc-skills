const {execFileSync} = require('node:child_process');
const {mkdirSync, readFileSync, statSync, unlinkSync, writeFileSync} = require('node:fs');
const {homedir, tmpdir} = require('node:os');
const {dirname, join, resolve} = require('node:path');
const {setTimeout: wait} = require('node:timers/promises');


const loopback = new Set(['127.0.0.1', 'localhost', '[::1]']);
const platformOf = url => /(?:^|\.)douyin\.com$/.test(url.hostname) ? 'douyin'
    : /(?:^|\.)xiaohongshu\.com$/.test(url.hostname) ? 'xiaohongshu' : '';
const shortHost = new Set(['v.douyin.com', 'xhslink.com', 'xhslink.cn', 'www.xhslink.com', 'www.xhslink.cn']);
const workId = (url, platform) => (
    platform === 'douyin' ? /^\/(?:video|note)\/(\d{15,22})\/?$/
        : /^\/(?:explore|discovery\/item|user\/profile\/[a-f0-9]{24})\/([a-f0-9]{24})\/?$/i
).exec(url.pathname)?.[1];
const homePattern = {
    douyin: /^\/user\/[^/]+\/?$/,
    xiaohongshu: /^\/user\/profile\/[a-f0-9]{24}\/?$/i,
};
const defaultVerifyUrl = 'data:text/html;charset=utf-8,%3Ctitle%3Ehongshu-env-verify%3C%2Ftitle%3E%3Cmain%20id%3Dok%3EREADY%3C%2Fmain%3E';

async function webPage(input, mode) {
    let url = new URL(input);
    for (let i = 0; i < 5 && shortHost.has(url.hostname) && url.protocol === 'https:'; i++) {
        const response = await fetch(url, {redirect: 'manual', signal: AbortSignal.timeout(8000)});
        await response.body?.cancel();
        const location = response.headers.get('location');
        if (!location) break;
        url = new URL(location, url);
    }
    if (url.protocol === 'https:' && url.hostname === 'www.iesdouyin.com') {
        const shared = /^\/share\/(user|video|note)\/([\w-]+)\/?$/.exec(url.pathname);
        if (shared) url = new URL('/' + shared[1] + '/' + shared[2], 'https://www.douyin.com');
    }
    if (url.protocol === 'https:' && platformOf(url) === 'xiaohongshu' && url.pathname === '/login') {
        const desktopPath = url.searchParams.get('redirectPath');
        if (desktopPath) {
            const desktop = new URL(desktopPath, url.origin);
            if (desktop.origin === url.origin) url = desktop;
        }
    }
    const platform = platformOf(url);
    const match = mode === 'list' ? homePattern[platform]?.test(url.pathname) : workId(url, platform);
    if (url.protocol !== 'https:' || !platform || !match || url.username || url.password) {
        throw new Error('请使用正常桌面网页里的同一账号主页或作品 HTTPS 链接');
    }
    return {url, platform};
}

function readReadyStamp() {
    try {
        const data = JSON.parse(readFileSync(join(homedir(), '.cache', 'reach-tools', 'env-ready.json'), 'utf8'));
        return data && typeof data === 'object' ? data : null;
    } catch { return null; }
}

function persistentAppDir() {
    const home = homedir();
    return process.platform === 'darwin'
        ? join(home, 'Library', 'Application Support', 'HongshuCollect')
        : process.platform === 'win32'
            ? join(process.env.LOCALAPPDATA || join(home, 'AppData', 'Local'), 'HongshuCollect')
            : join(home, '.local', 'share', 'hongshu-collect');
}

function dedicatedChromeProfiles(stamp) {
    const home = homedir();
    const persistent = join(persistentAppDir(), 'chrome-profile');
    const legacy = join(home, '.cache', 'chrome-devtools-mcp', 'chrome-profile');
    return [...new Set([stamp?.chrome_profile, persistent, legacy].filter(Boolean))];
}

function browserError(code, message) {
    const err = new Error(message);
    err.code = code;
    return err;
}

function requireMachineReady() {
    const stamp = readReadyStamp();
    const missing = [];
    if (stamp?.browser_verified !== true) missing.push('browser_verify');
    if (stamp?.asr_smoke_verified !== true) missing.push('asr_smoke');
    if (missing.length) {
        return {
            status: 'needs_env_ready',
            missing,
            message: '首次使用须先同时完成浏览器读写与固定中文短音频转写两项验收并写入本机就绪记录，再执行采集',
        };
    }
    return null;
}

async function chromeEndpoint() {
    const explicit = process.env.REACH_CHROME_URL;
    const stamp = readReadyStamp();
    const profiles = dedicatedChromeProfiles(stamp);
    const activePorts = [];
    const dapWsByPort = new Map();
    const addWs = (map, portStr, wsPath) => {
        if (!portStr || !wsPath?.startsWith('/devtools/browser/')) return;
        if (!map.has(portStr)) map.set(portStr, new Set());
        map.get(portStr).add(wsPath);
    };
    const dedicatedPsPorts = new Set();
    const unsafePsPorts = new Set();
    const foreignPsPorts = new Set();
    for (const profileDir of profiles) {
        try {
            const lines = readFileSync(join(profileDir, 'DevToolsActivePort'), 'utf8').split(/\r?\n/).map(s => s.trim()).filter(Boolean);
            if (lines[0] && /^\d{1,5}$/.test(lines[0])) {
                activePorts.push(lines[0]);
                addWs(dapWsByPort, lines[0], lines[1]);
            }
        } catch {}
    }
    if (process.platform !== 'win32') {
        try {
            const processes = execFileSync('ps', ['-axo', 'command='], {encoding: 'utf8', timeout: 1500, stdio: ['ignore', 'pipe', 'ignore']});
            for (const line of processes.split('\n')) {
                if (!/^\s*(?:\/(?:Applications|Users\/[^/\n]+\/Applications)\/Google Chrome\.app\/Contents\/MacOS\/Google Chrome|\/\S+\/(?:google-chrome(?:-stable)?|chromium|chrome))(?:\s|$)/.test(line)) continue;
                const port = /--remote-debugging-port(?:=|\s+)(\d+)/.exec(line)?.[1];
                if (!port || !Number(port)) continue;
                if (/\s--no-sandbox(?:\s|$)/.test(line)) {
                    unsafePsPorts.add(port);
                } else if (profiles.some(dir => line.includes(dir))) {
                    dedicatedPsPorts.add(port);
                    activePorts.push(port);
                } else {
                    foreignPsPorts.add(port);
                }
            }
        } catch {}
    }
    const addresses = explicit ? [explicit] : [...new Set(activePorts)].map(p => 'http://127.0.0.1:' + p);
    let sandboxBlocked = false;
    let occupiedDetail = '';
    for (const address of addresses) {
        try {
            const url = new URL(address);
            if (url.protocol !== 'http:' || !loopback.has(url.hostname) || !url.port || url.username || url.password) continue;
            const reply = await fetch(new URL('/json/version', url), {redirect: 'error', signal: AbortSignal.timeout(1200)});
            const info = await reply.json();
            if (reply.ok && /^(?:Chrome|Chromium)\//.test(info.Browser) && info.webSocketDebuggerUrl) {
                const wsPath = new URL(info.webSocketDebuggerUrl).pathname;
                const dapWs = dapWsByPort.get(url.port);
                const dapMatched = Boolean(dapWs?.has(wsPath));
                const psMatched = dedicatedPsPorts.has(url.port) && (!dapWs || dapMatched);
                if (unsafePsPorts.has(url.port)) {
                    occupiedDetail = `端口 ${url.port} 上运行的是关闭安全保护（--no-sandbox）的旧浏览器实例，拒绝复用，请正常退出该实例后再用安全入口打开`;
                    continue;
                }
                if (foreignPsPorts.has(url.port) || (!dapMatched && !psMatched)) {
                    occupiedDetail = `端口 ${url.port} 已被其他浏览器实例占用（与专用采集资料目录不匹配），保留现场不强行连接`;
                    continue;
                }
                return {origin: url.origin, browser: info.Browser, wsUrl: info.webSocketDebuggerUrl};
            }
        } catch (error) {
            const code = error?.cause?.code || error?.code || '';
            if (code === 'EPERM' || code === 'EACCES') sandboxBlocked = true;
        }
    }
    if (sandboxBlocked) {
        throw browserError('needs_permission', '当前会话缺少连接本机专用采集浏览器的权限（EPERM），请申请本机执行权限后重试，无需重新打开浏览器');
    }
    if (occupiedDetail) {
        throw browserError('port_occupied', occupiedDetail);
    }
    throw browserError('needs_launch', '未检测到运行中的专用采集浏览器，请经用户同意后通过统一启动入口打开专用采集浏览器');
}

async function createBackgroundTarget(browserWsUrl, background = true) {
    if (!browserWsUrl) return '';
    let ws;
    try {
        const debug = new URL(browserWsUrl);
        if (debug.protocol !== 'ws:' || !loopback.has(debug.hostname)) return '';
        ws = new WebSocket(debug);
        await new Promise((resolve, reject) => {
            const t = setTimeout(() => reject(new Error('timeout')), 3000);
            ws.addEventListener('open', () => { clearTimeout(t); resolve(); }, {once: true});
            ws.addEventListener('error', () => { clearTimeout(t); reject(new Error('error')); }, {once: true});
        });
        const targetId = await new Promise((resolve, reject) => {
            const t = setTimeout(() => reject(new Error('timeout')), 3000);
            const onMsg = ev => {
                const msg = JSON.parse(ev.data);
                if (msg.id === 1) {
                    clearTimeout(t);
                    ws.removeEventListener('message', onMsg);
                    resolve(msg.result?.targetId || '');
                }
            };
            ws.addEventListener('message', onMsg);
            ws.send(JSON.stringify({id: 1, method: 'Target.createTarget', params: {url: 'about:blank', background}}));
        });
        return targetId;
    } catch { return ''; } finally { try { ws?.close(); } catch {} }
}

async function chromeTab(endpoint, resumeId = '', browserWsUrl = '', background = true, strictBackground = false) {
    const request = (path, method = 'GET') => fetch(endpoint + path, {
        method, redirect: 'error', signal: AbortSignal.timeout(5000),
    });
    const findTab = async id => {
        try {
            const listed = await request('/json/list');
            if (!listed.ok) return null;
            const tabs = await listed.json();
            return tabs.find(item => item && item.id === id && item.type === 'page' && item.webSocketDebuggerUrl) || null;
        } catch { return null; }
    };
    let target = null;
    let reused = false;
    if (resumeId) {
        const found = await findTab(resumeId);
        if (found) {
            target = found;
            reused = true;
        }
    }
    if (!target && browserWsUrl) {
        const bgId = await createBackgroundTarget(browserWsUrl, background);
        if (bgId) {
            for (let attempt = 0; attempt < 5 && !target; attempt++) {
                target = await findTab(bgId);
                if (!target) await wait(200);
            }
            if (!target) {
                throw new Error('专用 Chrome 已返回新标签页 ID 但暂未查到该页，保留现场不重复开第二张标签页');
            }
        }
    }
    if (!target) {
        if (background && strictBackground) {
            throw new Error('后台新建采集标签页失败（当前要求全程静默，未执行普通开页），保留现场请重试或传入已有任务 --tab');
        }
        const response = await request('/json/new?about:blank', 'PUT');
        if (!response.ok) throw new Error('专用 Chrome 无法新建临时标签页');
        target = await response.json();
    }
    const {id, webSocketDebuggerUrl} = target;
    const closeTab = async () => { try { await request('/json/close/' + encodeURIComponent(id)); } catch {} };
    let socket;
    try {
        const debug = new URL(webSocketDebuggerUrl);
        if (debug.protocol !== 'ws:' || !loopback.has(debug.hostname) || debug.port !== new URL(endpoint).port
            || debug.pathname !== '/devtools/page/' + id) throw new Error('标签页连接地址无效');
        socket = new WebSocket(debug);
        await new Promise((resolve, reject) => {
            const timeout = setTimeout(() => reject(new Error('标签页连接超时')), 4000);
            const settle = fn => () => { clearTimeout(timeout); fn(); };
            socket.addEventListener('open', settle(resolve), {once: true});
            socket.addEventListener('error', settle(() => reject(new Error('标签页连接失败'))), {once: true});
        });
    } catch (error) {
        socket?.close();
        if (!reused) await closeTab();
        throw error;
    }
    let serial = 0;
    const call = (method, params) => new Promise((resolve, reject) => {
        const msgId = ++serial;
        const timeout = setTimeout(() => finish(new Error('浏览器动作超时')), 7000);
        function finish(error, result) {
            clearTimeout(timeout);
            socket.removeEventListener('message', onMessage);
            socket.removeEventListener('close', onClose);
            if (error) reject(error);
            else resolve(result);
        }
        function onClose() { finish(new Error('浏览器连接已断开')); }
        function onMessage(event) {
            const reply = JSON.parse(event.data);
            if (reply.id === msgId) finish(reply.error && new Error('浏览器动作失败：' + method), reply.result);
        }
        socket.addEventListener('message', onMessage);
        socket.addEventListener('close', onClose);
        try { socket.send(JSON.stringify({id: msgId, method, params})); }
        catch { onClose(); }
    });
    const tabGuard = `(() => {
        const bad = /^(?:bytedance|snssdk\\d*|aweme|xhsdiscover|bilibili|weixin|zhihu):/i;
        const mute = m => { if (m && 'muted' in m) { try { m.muted = true; m.volume = 0; } catch {} } };
        const origPlay = HTMLMediaElement.prototype.play;
        HTMLMediaElement.prototype.play = function(...a) { mute(this); return origPlay.apply(this, a); };
        for (const ev of ['play', 'playing', 'loadedmetadata', 'volumechange']) {
            document.addEventListener(ev, e => { if (e.target && !e.target.muted) mute(e.target); }, true);
        }
        const desc = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'src');
        if (desc?.set) Object.defineProperty(HTMLIFrameElement.prototype, 'src', {
            configurable: true, enumerable: true, get: desc.get,
            set(v) { if (!bad.test(String(v || ''))) return desc.set.call(this, v); },
        });
        const origAttr = Element.prototype.setAttribute;
        Element.prototype.setAttribute = function(k, v) {
            if ((k === 'src' || k === 'href') && bad.test(String(v || ''))) return;
            return origAttr.call(this, k, v);
        };
        const origClick = HTMLAnchorElement.prototype.click;
        HTMLAnchorElement.prototype.click = function(...a) {
            if (bad.test(String(this.href || this.getAttribute('href') || ''))) return;
            return origClick.apply(this, a);
        };
    })();`;
    await call('Page.enable').catch(() => {});
    await call('Page.addScriptToEvaluateOnNewDocument', {source: tabGuard}).catch(() => {});
    return {
        id,
        reused,
        call,
        async evaluate(fn, ...args) {
            const value = await call('Runtime.evaluate', {
                expression: '(' + fn + ')(...' + JSON.stringify(args) + ')',
                returnByValue: true,
            });
            if (value.exceptionDetails) throw new Error('页面结构变化，无法读取该页');
            return value.result.value;
        },
        disconnect() { socket.close(); },
        async close() { socket.close(); await closeTab(); },
    };
}

function pageGate() {
    const href = location.href;
    const text = (document.body?.innerText || '').trim();
    const visibleBlocking = selector => [...document.querySelectorAll(selector)].some(el => {
        const rect = el.getBoundingClientRect();
        return el.getClientRects().length > 0 && rect.width >= 120 && rect.height >= 80;
    });
    if (href === 'about:blank' || (!text && !document.querySelector('img,video,iframe,canvas'))) {
        return {gate: 'blank_page', href};
    }
    if (/(?:^|\/)website-login\/error(?:\/|$)/i.test(location.pathname)) {
        return {gate: 'site_restricted', href, detail: text.split(/\r?\n/).filter(Boolean).slice(0, 2).join('：')};
    }
    if (/(?:^|\/)(?:verify|captcha|secsdk)(?:\/|$)/i.test(location.pathname)
        || visibleBlocking('.captcha_verify_container, #captcha_container, .red-captcha, [id*="captcha"], [class*="captcha"], iframe[src*="captcha"], iframe[src*="verify"], iframe[src*="secsdk"]')) {
        return {gate: 'needs_verification', href};
    }
    if (/(?:^|\/)(?:login|signin|passport)(?:\/|$)/i.test(location.pathname)
        || visibleBlocking('.login-modal, .login-container, [class*="login-mask"], #login-pannel, [data-e2e="login-modal"]')) {
        return {gate: 'needs_login', href};
    }
    return {gate: 'none', href};
}

function accountStep(platform, home, advance) {
    if (location.protocol !== 'https:' || location.hostname !== home.host
        || location.pathname.replace(/\/$/, '') !== home.path) return {pending: true};
    const xhs = platform === 'xiaohongshu';
    const postLink = xhs ? 'section.note-item a.cover[href]' : 'a[href*="/video/"], a[href*="/note/"]';
    const first = document.querySelector(postLink);
    const root = xhs ? document.querySelector('#userPostedFeeds, .user-posted-feeds') || first?.closest('.feeds-container')
        : document.querySelector('[data-e2e="user-post-list"], [data-e2e="user-post-list-container"]') || first?.closest('ul');
    if (!root) return {pending: true};
    const douyinScroller = xhs ? null : root.closest('.route-scroll-container');
    let scroller = root;
    while (scroller && scroller !== document.body && !(
        /auto|scroll/.test(getComputedStyle(scroller).overflowY) && scroller.scrollHeight > scroller.clientHeight + 2
    )) scroller = scroller.parentElement;
    if (douyinScroller?.scrollHeight > douyinScroller?.clientHeight) scroller = douyinScroller;
    if (!scroller || scroller === document.body) scroller = document.scrollingElement;
    const end = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 3;
    const textOf = node => node?.textContent?.trim() || '';
    const metric = value => /^\d+(?:\.\d+)?\s*[万亿wWkK]?$/.test(value) ? value : '';
    const records = [];
    for (const link of root.querySelectorAll(postLink)) {
        if (!link.getClientRects().length) continue;
        const url = new URL(link.href, location.href);
        if (url.hostname !== location.hostname || url.protocol !== 'https:') continue;
        const card = xhs ? link.closest('section.note-item') : link.closest('li') || link;
        const id = xhs ? card?.getAttribute('data-note-id') : /^\/(?:video|note)\/(\d+)\/?$/.exec(url.pathname)?.[1];
        if (!id || !card || !url.pathname.replace(/\/$/, '').endsWith('/' + id)) continue;
        const title = textOf(card.querySelector(xhs ? '.title span, .title' : '[data-e2e="video-desc"], p'))
            || link.getAttribute('title') || link.querySelector('img[alt]')?.getAttribute('alt')
            || link.innerText.split('\n').map(s => s.trim()).find(s => s && !metric(s)) || '';
        const like = xhs ? card.querySelector('.like-wrapper .count') : card.querySelector('[data-e2e="video-like-count"], [aria-label^="点赞"], .author-card-user-video-like');
        const likes = metric(textOf(like)) || metric(like?.getAttribute('aria-label')?.replace(/^点赞\s*/, '') || '');
        const coverSrc = xhs ? (card.querySelector('a.cover img[src]')?.src || '') : '';
        const coverUrl = /^https:\/\//.test(coverSrc) ? coverSrc : '';
        records.push({
            id, url: url.href, title,
            ...(likes ? {likes_display: likes, evidence: {likes: '作品卡片点赞'}} : {}),
            ...(coverUrl ? {cover_url: coverUrl} : {}),
        });
    }
    const accountName = xhs
        ? (textOf(document.querySelector('.user-name, .info-part .user-nickname')) || document.title.replace(/\s*[-_|｜]\s*小红书\s*$/, '').trim())
        : (textOf(document.querySelector('[data-e2e="user-info"] h1, h1')) || document.title.replace(/\s*的抖音\s*[-_|｜]\s*抖音\s*$/, '').replace(/\s*[-_|｜]\s*抖音\s*$/, '').trim());
    const countText = textOf(document.querySelector('[data-e2e="user-tab-post"], [data-e2e="user-post-tab"]'))
        || [...document.querySelectorAll('button, [role="tab"], span')].map(textOf).find(text => /^作品\s*\d+$/.test(text))
        || '';
    const count = /作品\s*([0-9]+)$/.exec(countText)?.[1] || null;
    const endText = end && [...root.parentElement.querySelectorAll('span, p, div')].some(node =>
        node.childElementCount === 0 && node.getClientRects().length
        && /^[-—–\s]*(?:你到底啦[！!~～]?|没有更多(?:作品|笔记)?(?:了)?|已经到底了|THE\s+END)[-—–\s]*$/i.test(textOf(node)));
    if (advance && records.length) scroller.scrollTop += Math.max(1, Math.floor(scroller.clientHeight * 0.8));
    return {records, count, accountName: accountName || null, end, endText};
}

function playerEvidence(platform, targetHost, expectedId) {
    if (location.protocol !== 'https:' || location.hostname !== targetHost
        || !location.pathname.replace(/\/$/, '').endsWith('/' + expectedId)) return null;
    const players = [...document.querySelectorAll('video')].filter(video => Number.isFinite(video.duration)
        && video.duration > 0 && video.getBoundingClientRect().height >= 80);
    if (players.length !== 1) return null;
    const player = players[0];
    try { player.muted = true; player.volume = 0; } catch {}
    const videos = [{src: player.currentSrc, duration: player.duration, active: !player.paused,
        sources: [...player.querySelectorAll('source[src]')].map(source => source.src)}];
    const resourceHosts = platform === 'douyin' ? /(?:^|\.)(?:douyinvod\.com|douyin\.com)$/
        : /(?:^|\.)(?:xhscdn\.com|xiaohongshu\.com)$/;
    const paths = new Map();
    for (const resource of performance.getEntriesByType('resource')) {
        const url = new URL(resource.name);
        if (url.protocol !== 'https:' || !resourceHosts.test(url.hostname)) continue;
        if (platform === 'douyin' ? !/media-audio|\/aweme\/v1\/play\//.test(url.href) : !/\/stream\/|\.mp4(?:$|\?)/.test(url.href)) continue;
        if (!paths.has(url.pathname)) paths.set(url.pathname, url.href);
    }
    const direct = [player.currentSrc, ...videos[0].sources].filter(url => url.startsWith('https:'));
    if (!direct.length && paths.size !== 1) return null;
    const bound = direct.length ? direct : [...paths.values()];
    const textOf = sel => (document.querySelector(sel)?.textContent || '').trim();
    const metric = v => { const m = /(?:^|\s)(\d+(?:\.\d+)?\s*[万亿wWkK]?)(?:\s|$)/.exec(String(v || '')); return m ? m[1].replace(/\s+/g, '') : ''; };
    const bodyText = document.body?.innerText || '';
    const meta = {};
    if (platform === 'douyin') {
        const rawTitle = textOf('[data-e2e="detail-video-info"] h1, [data-e2e="video-desc"], h1') || document.title.replace(/\s*[-_|｜]\s*抖音\s*$/, '').trim();
        if (rawTitle) meta.title = rawTitle;
        const authorEl = document.querySelector('[data-e2e="detail-video-author-name"], [data-e2e="user-info"] a[href*="/user/"], [data-e2e="user-info"] [data-e2e="user-nickname"]')
            || [...document.querySelectorAll('a[href*="/user/"]')].find(a => /粉丝|获赞/.test(a.parentElement?.parentElement?.innerText || '') && a.textContent.trim());
        const metaDesc = document.querySelector('meta[name="description"]')?.getAttribute('content') || '';
        const beforePub = /([\s\S]+?)于\d{8}发布在抖音/.exec(metaDesc)?.[1] || '';
        const metaSegs = beforePub.split(/\s+-\s+/).map(s => s.trim()).filter(Boolean);
        const metaTail = metaSegs.length >= 2 ? metaSegs[metaSegs.length - 1] : '';
        const metaAuthor = (metaTail && metaTail.length <= 40 && !/[，。！？!?：:；;、]/.test(metaTail)) ? metaTail : '';
        const author = ((authorEl?.textContent || '').replace(/^@/, '').trim().split(/\r?\n/)[0].trim()) || metaAuthor;
        if (author) meta.author = author;
        const pubRaw = textOf('[data-e2e="detail-video-publish-time"], [data-e2e="video-publish-time"]')
            || (/发布时间[：:]\s*(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?(?:\s+\d{1,2}:\d{2})?)/.exec(bodyText)?.[1] || '');
        const pubMatch = /(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})/.exec(pubRaw);
        if (pubMatch) meta.published = `${pubMatch[1]}-${pubMatch[2].padStart(2, '0')}-${pubMatch[3].padStart(2, '0')}`;
        const likeEl = document.querySelector('[data-e2e="detail-video-digg-count"], [data-e2e="video-like-count"], [data-e2e="video-player-digg"], [aria-label^="点赞"]');
        const likes = metric(likeEl?.textContent) || metric(likeEl?.getAttribute('aria-label')?.replace(/^点赞\s*/, ''));
        if (likes) meta.like_count = likes;
    } else {
        const noteScope = document.querySelector('#noteContainer') || document.querySelector('.note-container') || document.querySelector('.note-detail-mask') || document;
        const firstText = (...sels) => {
            for (const sel of sels) {
                const txt = (noteScope.querySelector(sel)?.textContent || '').trim();
                if (txt) return txt;
            }
            return '';
        };
        const rawTitle = firstText('#detail-title', '.note-content .title', 'h1') || document.title.replace(/\s*[-_|｜]\s*小红书\s*$/, '').trim();
        if (rawTitle) meta.title = rawTitle;
        const desc = firstText('#detail-desc', '.note-content .desc');
        if (desc) meta.text = desc;
        const author = firstText('.author-wrapper .username', '.author-container .username', '.user-info .username');
        if (author) meta.author = author;
        const pubRaw = firstText('.bottom-container .date', '.note-content .date');
        if (pubRaw) {
            meta.published_display = pubRaw;
            const isEdited = /^编辑于(?:\s|$)/.test(pubRaw);
            const stripped = pubRaw.replace(/^(?:编辑于|发布于)\s*/, '').trim();
            const dm = /^(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}-\d{1,2})(?:\s+[\u4e00-\u9fa5A-Za-z]+)?$/.exec(stripped);
            if (dm) meta.published = dm[1];
            meta.date_kind = isEdited ? 'edited' : (dm ? 'published' : 'unknown');
        }
        const likes = metric(firstText('.engage-bar .like-wrapper .count', '.interact-container .like-wrapper .count', '.engage-bar-container .like-wrapper .count'));
        if (likes) meta.like_count = likes;
    }
    return {url: location.href, ...meta, videos, duration: player.duration,
        ...(platform === 'douyin' ? {audioUrls: direct.length ? [] : bound} : {stream_urls: bound})};
}

function save(path, result) {
    mkdirSync(dirname(path), {recursive: true});
    writeFileSync(path, JSON.stringify(result, null, 2) + '\n', {mode: 0o600});
}

async function gateReply(tab, gate, extra = {}) {
    await tab.call('Page.bringToFront').catch(() => {});
    const isLogin = gate.gate === 'needs_login';
    return {
        status: gate.gate,
        browser_connected: true,
        page_accessible: false,
        platform_logged_in: isLogin ? false : null,
        tab_id: tab.id,
        tab_kept_open: true,
        url: gate.href,
        message: isLogin ? '请在刚打开的页面完成登录，确认后再带原标签页继续' : '需要你完成平台验证，完成后再带原标签页继续',
        ...extra,
    };
}

async function verifyBrowser(tab, endpointInfo, output, customUrl) {
    const targetUrl = customUrl || defaultVerifyUrl;
    if (customUrl) {
        const parsed = new URL(customUrl);
        if (parsed.protocol !== 'https:' || parsed.username || parsed.password) {
            throw new Error('校验链接仅支持正常 HTTPS 网页');
        }
    }
    const nav = await tab.call('Page.navigate', {url: targetUrl});
    if (nav.errorText) throw new Error('浏览器校验页未能加载：' + nav.errorText);
    let read = null;
    for (let attempt = 0; attempt < 10; attempt++) {
        await wait(350);
        const snap = await tab.evaluate(() => ({
            readyState: document.readyState,
            href: location.href,
            title: document.title || '',
            text: (document.body?.innerText || '').trim().slice(0, 120),
        }));
        const matched = customUrl ? Boolean(snap.title || snap.text) : (snap.title === 'hongshu-env-verify' && snap.text.includes('READY'));
        if (matched && snap.readyState !== 'loading') {
            read = snap;
            break;
        }
    }
    if (!read) throw new Error('浏览器未能读回校验页内容');
    const proof = {
        status: 'verified',
        channel: 'cdp-script',
        browser_connected: true,
        page_read_ok: true,
        file_write_ok: true,
        endpoint: endpointInfo.origin,
        browser: endpointInfo.browser,
        url_checked: customUrl || 'self-contained-html',
        page_title: read.title,
        verified_at: new Date().toISOString(),
    };
    save(output, proof);
    const readback = JSON.parse(readFileSync(output, 'utf8'));
    if (readback.status !== 'verified' || readback.page_title !== proof.page_title) {
        throw new Error('校验文件写回核对失败');
    }
    return proof;
}

async function collect(tab, address, platform, mode, output, limit) {
    const expectedPath = address.pathname.replace(/\/$/, '');
    if (mode === 'media') {
        for (let attempt = 0; attempt < 16; attempt++) {
            const result = await tab.evaluate(playerEvidence, platform, address.hostname, workId(address, platform));
            if (result && workId(new URL(result.url), platform) === workId(address, platform)) {
                save(output, result);
                return {status: 'ready', browser_connected: true, page_accessible: true, platform_logged_in: null, path: output};
            }
            if (attempt >= 5) {
                const gated = await tab.evaluate(pageGate);
                if (gated.gate === 'site_restricted') throw new Error('页面被平台限制访问：' + (gated.detail || '安全限制'));
                if (gated.gate === 'needs_login' || gated.gate === 'needs_verification') {
                    return await gateReply(tab, gated);
                }
            }
            await wait(500);
        }
        const finalGate = await tab.evaluate(pageGate);
        if (finalGate.gate === 'site_restricted') throw new Error('页面被平台限制访问：' + (finalGate.detail || '安全限制'));
        if (finalGate.gate === 'blank_page') throw new Error('页面为空白页，未能加载目标作品');
        throw new Error('该页未确认唯一主播放器或同篇播放资源');
    }
    let batch;
    try {
        batch = JSON.parse(readFileSync(output, 'utf8'));
        if (batch.source?.url !== address.href || !Array.isArray(batch.records)) {
            throw new Error('过程文件属于其他采集任务，请另选路径');
        }
    } catch (error) {
        if (error.code !== 'ENOENT') throw error;
        batch = {source: {url: address.href, column: '账号作品', observed_at: new Date().toISOString(), evidence: '主页作品卡片'}, records: []};
    }
    const captured = new Map(batch.records.map(item => [item.id, item]));
    let stableEnd = 0;
    let stale = 0;
    let reached = false;
    for (let step = 0; step < 350; step++) {
        const page = await tab.evaluate(accountStep, platform, {host: address.hostname, path: expectedPath}, true);
        let changed = false;
        for (const item of page.records || []) {
            const old = captured.get(item.id);
            const current = {...old, ...item, title: item.title || old?.title || ''};
            if (JSON.stringify(old) !== JSON.stringify(current)) changed = true;
            captured.set(item.id, current);
        }
        if (page.accountName && !batch.source.account_name) batch.source.account_name = page.accountName;
        if (page.count) batch.coverage = {...batch.coverage, displayed: Number(page.count)};
        stableEnd = !changed && page.end && page.records?.length ? stableEnd + 1 : 0;
        stale = changed ? 0 : stale + 1;
        reached = Boolean(limit && captured.size >= limit) || stableEnd >= 3 && (
            batch.coverage?.displayed ? captured.size >= batch.coverage.displayed : page.endText
        );
        if (changed || reached) {
            batch.records = [...captured.values()].slice(0, limit || undefined);
            batch.coverage = {...batch.coverage, complete: reached, observed: batch.records.length};
            save(output, batch);
        }
        if (reached) break;
        if (stale >= 4) {
            const gated = await tab.evaluate(pageGate);
            if (gated.gate === 'site_restricted' && !captured.size) throw new Error('页面被平台限制访问：' + (gated.detail || '安全限制'));
            if (gated.gate === 'needs_login' || gated.gate === 'needs_verification') {
                if (captured.size) {
                    batch.records = [...captured.values()].slice(0, limit || undefined);
                    batch.coverage = {...batch.coverage, complete: false, observed: batch.records.length};
                    save(output, batch);
                }
                return await gateReply(tab, gated, captured.size ? {partial_count: batch.records.length, path: output} : {});
            }
        }
        if (stale >= 12) break;
        await wait(changed ? 550 : 750);
    }
    if (!captured.size) {
        const finalGate = await tab.evaluate(pageGate);
        if (finalGate.gate === 'site_restricted') throw new Error('页面被平台限制访问：' + (finalGate.detail || '安全限制'));
        if (finalGate.gate === 'blank_page') throw new Error('页面为空白页，未能加载目标主页');
        throw new Error('账号作品栏未加载或无法确认主页身份');
    }
    batch.coverage = {...batch.coverage, complete: reached, observed: batch.records.length};
    save(output, batch);
    return {
        status: reached ? 'complete' : 'partial', browser_connected: true, page_accessible: true, platform_logged_in: null,
        count: batch.records.length, ...(batch.source.account_name ? {account_name: batch.source.account_name} : {}), path: output,
    };
}

function zhihuPage(input) {
    const url = new URL(input);
    if (url.protocol !== 'https:' || url.username || url.password) {
        throw new Error('请使用正常桌面网页里的知乎回答或专栏 HTTPS 直链');
    }
    const ans = /^\/question\/(\d+)\/answer\/(\d+)\/?$/.exec(url.pathname);
    if (/(?:^|\.)zhihu\.com$/.test(url.hostname) && ans) {
        return {url, kind: 'answer', questionId: ans[1], itemId: ans[2]};
    }
    const col = /^\/p\/(\d+)\/?$/.exec(url.pathname);
    if (url.hostname === 'zhuanlan.zhihu.com' && col) {
        return {url, kind: 'zhuanlan', itemId: col[1]};
    }
    throw new Error('知乎仅支持具体回答链接（/question/<问题ID>/answer/<回答ID>）或专栏文章链接（zhuanlan.zhihu.com/p/<ID>）');
}

function zhihuArticleEvidence(kind, expectedId) {
    const bodyText = (document.body?.innerText || '').trim();
    if (bodyText.startsWith('{') && bodyText.includes('"error"')) {
        try {
            const parsed = JSON.parse(bodyText);
            if (parsed?.error) {
                return {error_code: String(parsed.error.code || ''), error_message: String(parsed.error.message || '')};
            }
        } catch {}
    }
    const extractBody = rich => {
        if (!rich) return '';
        const clone = rich.cloneNode(true);
        for (const el of clone.querySelectorAll('script, style, noscript, .LinkCard-backdrop')) el.remove();
        for (const fig of clone.querySelectorAll('figure')) {
            const cap = (fig.querySelector('figcaption')?.textContent || '').trim();
            const p = document.createElement('p');
            p.textContent = cap ? `[此处原文有图片：${cap}]` : '[此处原文有图片]';
            fig.replaceWith(p);
        }
        for (const img of clone.querySelectorAll('img')) {
            const alt = (img.getAttribute('alt') || '').trim();
            img.replaceWith(document.createTextNode(alt ? `[${alt}]` : '[此处原文有图片]'));
        }
        const blockTags = new Set(['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'ul', 'ol', 'pre', 'figure', 'section', 'article', 'hr', 'table']);
        const blocks = [];
        let inlineBuf = '';
        const flushInline = () => {
            const cleaned = inlineBuf.replace(/\r/g, '').replace(/[ \t]+\n/g, '\n').trim();
            if (cleaned) blocks.push(cleaned);
            inlineBuf = '';
        };
        for (const node of clone.childNodes) {
            if (node.nodeType === 3) {
                inlineBuf += node.nodeValue || '';
                continue;
            }
            if (node.nodeType !== 1) continue;
            const tag = node.tagName.toLowerCase();
            if (!blockTags.has(tag)) {
                inlineBuf += tag === 'br' ? '\n' : (node.innerText || node.textContent || '');
                continue;
            }
            flushInline();
            if (tag === 'ul' || tag === 'ol') {
                const items = [...node.querySelectorAll(':scope > li')].map((li, idx) =>
                    (tag === 'ol' ? `${idx + 1}. ` : '- ') + (li.innerText || li.textContent || '').replace(/\s+/g, ' ').trim()
                ).filter(s => s.length > 2);
                if (items.length) blocks.push(items.join('\n'));
            } else {
                const txt = (node.innerText || node.textContent || '').replace(/\r/g, '').replace(/[ \t]+\n/g, '\n').trim();
                if (txt) blocks.push(txt);
            }
        }
        flushInline();
        return (blocks.length ? blocks.join('\n\n') : (clone.innerText || clone.textContent || '').trim()).replace(/\n{3,}/g, '\n\n').trim();
    };
    const parseDate = (isoMeta, timeText) => {
        const mIso = /^(\d{4}-\d{2}-\d{2})/.exec(isoMeta || '');
        const pubMatch = /发布于\s*(\d{4}-\d{2}-\d{2})/.exec(timeText || '');
        if (pubMatch) return {published: pubMatch[1], date_kind: 'published'};
        if (mIso) return {published: mIso[1], date_kind: 'published'};
        const editMatch = /编辑于\s*(\d{4}-\d{2}-\d{2})/.exec(timeText || '');
        if (editMatch) return {published: '', date_kind: 'edited', edited_display: editMatch[1]};
        return {published: '', date_kind: 'unknown'};
    };
    const parseVotes = (metaVal, btnText) => {
        if (metaVal && /^\d+$/.test(metaVal.trim())) return metaVal.trim();
        const m = /(\d+(?:\.\d+)?\s*[万亿wWkK]?)/.exec((btnText || '').replace(/,/g, ''));
        return m ? m[1].replace(/\s+/g, '') : '';
    };
    if (kind === 'zhuanlan') {
        if (!location.pathname.replace(/\/$/, '').endsWith('/p/' + expectedId)) return null;
        const root = document.querySelector('.Post-Main, article');
        if (!root) return null;
        const rich = root.querySelector('.Post-RichTextContainer .RichText, .Post-RichText, .RichText');
        const body = extractBody(rich);
        if (!body) return null;
        const cleanInline = s => String(s || '').replace(/[\u200b-\u200d\ufeff]/g, '').trim();
        const title = cleanInline((root.querySelector('h1.Post-Title, h1')?.textContent || '')
            || document.title.replace(/\s*[-_|｜]\s*知乎\s*$/, ''));
        const author = cleanInline(root.querySelector('.AuthorInfo-name, .Post-Author .UserLink-link, meta[itemprop="name"]')?.textContent
            || root.querySelector('meta[itemprop="name"]')?.getAttribute('content') || '');
        const timeText = (root.querySelector('.ContentItem-time, .Post-NormalSub')?.textContent || '').trim();
        const dateInfo = parseDate(root.querySelector('meta[itemprop="dateCreated"]')?.getAttribute('content'), timeText);
        const likeCount = parseVotes(
            root.querySelector('meta[itemprop="upvoteCount"]')?.getAttribute('content'),
            root.querySelector('.VoteButton--up, button[aria-label*="赞同"]')?.textContent || '',
        );
        return {
            url: location.href, platform: '知乎', content_type: '图文', item_id: expectedId,
            title, author, ...dateInfo, like_count: likeCount, body,
        };
    }
    const candidates = [...document.querySelectorAll('.AnswerItem, .ContentItem')];
    const container = candidates.find(el => {
        if (el.getAttribute('name') === expectedId) return true;
        const metaUrl = el.querySelector('meta[itemprop="url"]')?.getAttribute('content') || '';
        if (metaUrl.replace(/\/$/, '').endsWith('/answer/' + expectedId)) return true;
        try {
            const zop = JSON.parse(el.getAttribute('data-zop') || '{}');
            if (String(zop.itemId || '') === expectedId) return true;
        } catch {}
        return false;
    });
    if (!container) return null;
    const expandBtn = [...container.querySelectorAll('button')].find(b => /阅读全文|展开阅读全文/.test((b.textContent || '').trim()));
    if (expandBtn) {
        expandBtn.click();
        return {expanding: true};
    }
    const rich = container.querySelector('.RichContent-inner .RichText, .RichText');
    const body = extractBody(rich);
    if (!body) return null;
    const cleanInline = s => String(s || '').replace(/[\u200b-\u200d\ufeff]/g, '').trim();
    const title = cleanInline((document.querySelector('h1.QuestionHeader-title, .QuestionHeader-title')?.textContent || '')
        || document.title.replace(/\s*-\s*知乎\s*$/, ''));
    const authorEl = container.querySelector('.AuthorInfo-name .UserLink-link, .AuthorInfo-name');
    const author = cleanInline(authorEl?.textContent || container.querySelector('.AuthorInfo meta[itemprop="name"]')?.getAttribute('content') || '');
    const timeText = (container.querySelector('.ContentItem-time')?.textContent || '').trim();
    const dateInfo = parseDate(container.querySelector('meta[itemprop="dateCreated"]')?.getAttribute('content'), timeText);
    const likeCount = parseVotes(
        container.querySelector('meta[itemprop="upvoteCount"]')?.getAttribute('content'),
        container.querySelector('.VoteButton--up, button[aria-label*="赞同"]')?.textContent || '',
    );
    return {
        url: location.href.split(/[?#]/)[0], platform: '知乎', content_type: '图文', item_id: expectedId,
        title, author, ...dateInfo, like_count: likeCount, body,
    };
}

async function collectZhihuArticle(tab, target, output) {
    for (let attempt = 0; attempt < 16; attempt++) {
        const result = await tab.evaluate(zhihuArticleEvidence, target.kind, target.itemId);
        if (result?.expanding) {
            await wait(600);
            continue;
        }
        if (result?.error_code) {
            return {
                status: 'site_restricted',
                browser_connected: true,
                page_accessible: false,
                error_code: result.error_code,
                detail: result.error_message || `知乎返回错误码 ${result.error_code}`,
                signin_url: 'https://www.zhihu.com/signin?next=' + encodeURIComponent(target.url.pathname),
                url: target.url.href,
            };
        }
        if (result?.body && result.item_id === target.itemId) {
            save(output, result);
            return {
                status: 'ready', browser_connected: true, page_accessible: true,
                item_id: result.item_id, title: result.title, author: result.author,
                published: result.published, like_count: result.like_count, body_length: result.body.length,
                path: output,
            };
        }
        if (attempt >= 5) {
            const gated = await tab.evaluate(pageGate);
            if (gated.gate === 'site_restricted') throw new Error('页面被平台限制访问：' + (gated.detail || '安全限制'));
            if (gated.gate === 'needs_login' || gated.gate === 'needs_verification') {
                return await gateReply(tab, gated);
            }
        }
        await wait(500);
    }
    const finalGate = await tab.evaluate(pageGate);
    if (finalGate.gate === 'needs_login' || finalGate.gate === 'needs_verification') {
        return await gateReply(tab, finalGate);
    }
    if (finalGate.gate === 'blank_page') throw new Error('页面为空白页，未能加载目标知乎页面');
    throw new Error('未能锁定目标知乎回答/专栏正文（未匹配指定 ID）');
}

async function renderCoverSheets(tab, batchPath, outDir, ids, batchSize = 16) {
    const raw = JSON.parse(readFileSync(resolve(batchPath), 'utf8'));
    const records = Array.isArray(raw?.records) ? raw.records : (Array.isArray(raw?.payload?.records) ? raw.payload.records : []);
    const byId = new Map(records.map(r => [String(r.id), r]));
    const selected = [];
    const missingIds = [];
    for (const id of ids) {
        const rec = byId.get(id);
        if (!rec || !rec.cover_url || !/^https:\/\//.test(rec.cover_url)) {
            missingIds.push(id);
        } else {
            selected.push({id, cover_url: rec.cover_url});
        }
    }
    mkdirSync(resolve(outDir), {recursive: true});
    const sheets = [];
    const esc = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
    for (let offset = 0; offset < selected.length; offset += batchSize) {
        const chunk = selected.slice(offset, offset + batchSize);
        const tilesHtml = chunk.map((item, i) => {
            const idx = offset + i + 1;
            return `<div class="tile" data-id="${esc(item.id)}"><div class="hdr">#${idx} · ${esc(item.id)}</div><div class="box"><img src="${esc(item.cover_url)}" referrerpolicy="no-referrer" /><div class="err">封面加载失败</div></div></div>`;
        }).join('');
        const sheetKey = '__coversDone_' + (sheets.length + 1);
        const html = `<!doctype html><html><head><meta charset="utf-8"><style>
            body{margin:0;padding:12px;background:#111;font:12px/1.3 -apple-system,BlinkMacSystemFont,sans-serif;color:#fff;}
            .grid{display:grid;grid-template-columns:repeat(4,280px);gap:10px;}
            .tile{background:#222;border:1px solid #444;border-radius:6px;overflow:hidden;display:flex;flex-direction:column;}
            .hdr{padding:5px 8px;background:#d92d20;color:#fff;font-weight:700;font-size:12px;word-break:break-all;}
            .box{position:relative;width:280px;height:360px;background:#1a1a1a;display:flex;align-items:center;justify-content:center;}
            .box img{max-width:100%;max-height:100%;object-fit:contain;display:block;}
            .box .err{display:none;color:#fca5a5;font-size:13px;padding:12px;text-align:center;}
            .box.failed img{display:none;}
            .box.failed .err{display:block;}
        </style></head><body><div class="grid">${tilesHtml}</div><script>
            (() => {
                const key = ${JSON.stringify(sheetKey)};
                window[key] = false;
                const imgs = [...document.querySelectorAll('img')];
                let left = imgs.length;
                const finish = (img, ok) => {
                    if (img.dataset.settled) return;
                    img.dataset.settled = '1';
                    img.dataset.ok = ok ? '1' : '0';
                    if (!ok) img.parentElement.classList.add('failed');
                    if (--left <= 0) window[key] = true;
                };
                if (!left) window[key] = true;
                for (const img of imgs) {
                    img.addEventListener('load', () => finish(img, img.naturalWidth > 0), {once: true});
                    img.addEventListener('error', () => finish(img, false), {once: true});
                    if (img.complete) finish(img, img.naturalWidth > 0);
                }
                setTimeout(() => {
                    for (const img of imgs) finish(img, img.complete && img.naturalWidth > 0);
                    window[key] = true;
                }, 10000);
            })();
        </script></body></html>`;
        const frameTree = await tab.call('Page.getFrameTree');
        await tab.call('Page.setDocumentContent', {frameId: frameTree.frameTree.frame.id, html});
        for (let t = 0; t < 26; t++) {
            const done = await tab.evaluate(k => Boolean(window[k]), sheetKey);
            if (done) break;
            await wait(450);
        }
        const states = await tab.evaluate(() => [...document.querySelectorAll('.tile')].map(el => {
            const img = el.querySelector('img');
            return {
                id: el.getAttribute('data-id'),
                loaded: Boolean(img && img.complete && img.naturalWidth > 0),
            };
        }));
        const shot = await tab.call('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
        const sheetNum = String(sheets.length + 1).padStart(2, '0');
        const sheetPath = join(resolve(outDir), `covers-${sheetNum}.png`);
        writeFileSync(sheetPath, Buffer.from(shot.data, 'base64'));
        sheets.push({
            path: sheetPath,
            items: chunk.map((item, i) => ({
                index: offset + i + 1,
                id: item.id,
                loaded: Boolean(states[i]?.loaded),
            })),
        });
    }
    return {status: 'ready', sheets, missing_ids: missingIds};
}

function parseCli(argv) {
    let tabId = '';
    let ids = [];
    let batchSize = 16;
    let strictBackground = process.env.REACH_STRICT_BACKGROUND === '1';
    const positional = [];
    for (let i = 0; i < argv.length; i++) {
        if (argv[i] === '--tab') {
            if (!argv[i + 1]) throw new Error('--tab 缺少标签页 ID');
            tabId = argv[++i];
        } else if (argv[i] === '--ids') {
            if (!argv[i + 1]) throw new Error('--ids 缺少作品 ID 列表');
            ids = argv[++i].split(/[\s,]+/).map(s => s.trim()).filter(Boolean);
        } else if (argv[i] === '--batch-size') {
            const n = Number(argv[++i]);
            if (!Number.isInteger(n) || n < 1 || n > 24) throw new Error('--batch-size 须为 1–24 的整数');
            batchSize = n;
        } else if (argv[i] === '--strict-background') {
            strictBackground = true;
        } else {
            positional.push(argv[i]);
        }
    }
    return {positional, tabId, ids, batchSize, strictBackground};
}

async function acquireActiveTabLock(mode) {
    const uid = typeof process.getuid === 'function' ? process.getuid() : 'user';
    const lockName = `hongshu-reach-chrome-active-tab-${uid}.lock`;
    const dirs = [...new Set(
        process.platform === 'win32'
            ? [tmpdir(), join(homedir(), '.cache', 'reach-tools')]
            : ['/tmp', tmpdir(), join(homedir(), '.cache', 'reach-tools')]
    )];
    const deadline = Date.now() + 180000;
    const isAlive = pid => {
        if (!Number.isInteger(pid) || pid <= 0) return false;
        try { process.kill(pid, 0); return true; }
        catch (err) { return err?.code === 'EPERM'; }
    };
    for (const lockDir of dirs) {
        const lockPath = join(lockDir, lockName);
        try { mkdirSync(lockDir, {recursive: true}); } catch { continue; }
        while (Date.now() < deadline) {
            try {
                writeFileSync(lockPath, JSON.stringify({pid: process.pid, mode, started_at: Date.now()}) + '\n', {flag: 'wx', mode: 0o600});
                return () => {
                    try {
                        const cur = JSON.parse(readFileSync(lockPath, 'utf8'));
                        if (cur?.pid === process.pid) unlinkSync(lockPath);
                    } catch {}
                };
            } catch (err) {
                if (err?.code !== 'EEXIST') break;
                let stale = false;
                try {
                    const holder = JSON.parse(readFileSync(lockPath, 'utf8'));
                    const age = Date.now() - Number(holder?.started_at || 0);
                    if (!isAlive(Number(holder?.pid)) || age > 600000) stale = true;
                } catch {
                    try { if (Date.now() - statSync(lockPath).mtimeMs > 15000) stale = true; } catch { stale = true; }
                }
                if (stale) { try { unlinkSync(lockPath); } catch {} continue; }
                await wait(400);
            }
        }
        if (Date.now() >= deadline) throw new Error('等待其他浏览器采集任务释放活动标签页超时，请稍后重试');
    }
    return () => {};
}

async function main() {
    if (typeof WebSocket !== 'function') throw new Error('直连桌面 Chrome 需要支持 WebSocket 的 Node.js 22+');
    const {positional, tabId, ids, batchSize, strictBackground} = parseCli(process.argv.slice(2));
    const [mode, arg1, arg2, arg3] = positional;
    if (mode === 'probe') {
        try {
            const info = await chromeEndpoint();
            console.log(JSON.stringify({status: 'connected', browser_connected: true, endpoint: info.origin, browser: info.browser}));
            return;
        } catch (error) {
            const status = ['needs_permission', 'port_occupied'].includes(error.code) ? error.code : 'needs_launch';
            console.log(JSON.stringify({status, browser_connected: false, message: error.message}));
            process.exitCode = 1;
            return;
        }
    }
    if (mode === 'verify') {
        if (!arg1) throw new Error('用法：browser_collect.js verify <校验凭证.json> [HTTPS校验页]');
        const info = await chromeEndpoint();
        const tab = await chromeTab(info.origin, '', info.wsUrl, true, strictBackground);
        try {
            console.log(JSON.stringify(await verifyBrowser(tab, info, resolve(arg1), arg2 || '')));
        } finally { await tab.close(); }
        return;
    }
    if (mode === 'covers') {
        if (!arg1 || !arg2 || !ids.length) {
            throw new Error('用法：browser_collect.js covers <批次JSON> <输出目录> --ids <id1,id2,...> [--batch-size 16]');
        }
        const info = await chromeEndpoint();
        const releaseLock = strictBackground ? () => {} : await acquireActiveTabLock('covers');
        try {
            const tab = await chromeTab(info.origin, tabId, info.wsUrl, strictBackground, strictBackground);
            try {
                console.log(JSON.stringify(await renderCoverSheets(tab, arg1, arg2, ids, batchSize)));
            } finally { await tab.close(); }
        } finally { releaseLock(); }
        return;
    }
    if (mode === 'article') {
        if (!arg1 || !arg2) {
            throw new Error('用法：browser_collect.js article <知乎回答或专栏 HTTPS 链接> <输出 JSON> [--tab <tabId>]');
        }
        const notReady = requireMachineReady();
        if (notReady) {
            console.log(JSON.stringify(notReady));
            process.exitCode = 2;
            return;
        }
        const info = await chromeEndpoint();
        const target = zhihuPage(arg1);
        const tab = await chromeTab(info.origin, tabId, info.wsUrl, true, strictBackground);
        let keepOpen = false;
        try {
            let shouldNavigate = true;
            if (tab.reused) {
                try {
                    const currentHref = await tab.evaluate(() => location.href);
                    const cur = new URL(currentHref);
                    if (cur.protocol === 'https:' && cur.hostname === target.url.hostname
                        && cur.pathname.replace(/\/$/, '') === target.url.pathname.replace(/\/$/, '')) {
                        shouldNavigate = false;
                    }
                } catch {}
            }
            if (shouldNavigate) {
                const result = await tab.call('Page.navigate', {url: target.url.href});
                if (result.errorText) throw new Error('指定网页未能在桌面打开：' + result.errorText);
                await wait(750);
            }
            const outcome = await collectZhihuArticle(tab, target, resolve(arg2));
            if (outcome.tab_kept_open) keepOpen = true;
            console.log(JSON.stringify(outcome));
        } finally {
            if (keepOpen) tab.disconnect();
            else await tab.close();
        }
        return;
    }
    if (!['list', 'media'].includes(mode) || !arg1 || !arg2 || (arg3 && (mode !== 'list' || !/^[1-9]\d*$/.test(arg3)))) {
        throw new Error('用法：browser_collect.js probe | verify <凭证.json> [URL] | list|media|article <网页链接> <输出 JSON> [条数] [--tab <tabId>] | covers <批次JSON> <输出目录> --ids <id1,id2>');
    }
    const notReady = requireMachineReady();
    if (notReady) {
        console.log(JSON.stringify(notReady));
        process.exitCode = 2;
        return;
    }
    const info = await chromeEndpoint();
    const {url, platform} = await webPage(arg1, mode);
    const useBackground = mode === 'list' && strictBackground;
    const releaseLock = useBackground ? () => {} : await acquireActiveTabLock(mode);
    try {
        const tab = await chromeTab(info.origin, tabId, info.wsUrl, useBackground, strictBackground);
        let keepOpen = false;
        try {
            let shouldNavigate = true;
            if (tab.reused) {
                try {
                    const currentHref = await tab.evaluate(() => location.href);
                    const cur = new URL(currentHref);
                    if (cur.protocol === 'https:' && cur.hostname === url.hostname
                        && cur.pathname.replace(/\/$/, '') === url.pathname.replace(/\/$/, '')) {
                        shouldNavigate = false;
                    }
                } catch {}
            }
            if (shouldNavigate) {
                const result = await tab.call('Page.navigate', {url: url.href});
                if (result.errorText) throw new Error('指定网页未能在桌面打开：' + result.errorText);
                await wait(650);
            }
            const outcome = await collect(tab, url, platform, mode, resolve(arg2), Number(arg3) || null);
            if (outcome.tab_kept_open) keepOpen = true;
            console.log(JSON.stringify(outcome));
        } finally {
            if (keepOpen) tab.disconnect();
            else await tab.close();
        }
    } finally { releaseLock(); }
}

main().catch(error => {
    console.error(error.message);
    process.exitCode = 1;
});
