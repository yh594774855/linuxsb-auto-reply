// ==UserScript==
// @name         linux.sb 提取登录 cookie（给 linuxsb-auto-reply 用）
// @namespace    yh594774855
// @version      1.0.0
// @description  在 linux.sb 页面一键提取完整 document.cookie 与 UID，复制后填入 linuxsb-auto-reply 的 config.json。登录后打开任意 linux.sb 页面即可。
// @match        *://linux.sb/*
// @run-at       document-idle
// @grant        GM_setClipboard
// ==/UserScript==

(function () {
  'use strict';

  const PANEL_ID = 'lsb-ck-panel';

  function getCookieString() {
    const keys = ['Hm_lvt_776be676456910a7be2cc5097678152e', 'HMACCOUNT', 'bbs_auth', '__daily_checkin_stats', 'bbs_csrf', '__recent_forums'];
    const parts = [];
    for (const k of keys) {
      const m = document.cookie.split('; ').find(c => c.startsWith(k + '='));
      if (m) parts.push(m);
    }
    return parts.join('; ');
  }

  function getUid() {
    const a = document.querySelector('a[href*="/user/"]');
    if (!a) return '';
    const m = a.href.match(/\/user\/(\d+)/);
    return m ? m[1] : '';
  }

  function buildConfigBlock(cookie, uid) {
    return JSON.stringify({
      cookie: cookie,
      uid: uid ? Number(uid) : 0,
      pushplus_token: "YOUR_PUSHPLUS_TOKEN_OPTIONAL"
    }, null, 2);
  }

  function ensurePanel() {
    if (document.getElementById(PANEL_ID)) return;
    const panel = document.createElement('div');
    panel.id = PANEL_ID;
    panel.style.cssText = [
      'position:fixed;right:16px;bottom:16px;z-index:99999;width:340px;',
      'background:#1f2937;color:#f3f4f6;border:1px solid #374151;border-radius:10px;',
      'box-shadow:0 8px 24px rgba(0,0,0,.4);font:13px/1.5 "Segoe UI",system-ui,sans-serif;',
      'padding:12px 14px;'
    ].join('');

    const header = document.createElement('div');
    header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;font-weight:600;';
    header.innerHTML = '<span>linux.sb Cookie 提取</span>';
    const close = document.createElement('button');
    close.textContent = '×';
    close.style.cssText = 'background:none;border:none;color:#9ca3af;font-size:16px;cursor:pointer;';
    close.onclick = () => panel.remove();
    header.appendChild(close);
    panel.appendChild(header);

    const status = document.createElement('div');
    status.style.cssText = 'margin-bottom:8px;color:#6ee7b7;';
    panel.appendChild(status);

    const ta = document.createElement('textarea');
    ta.readOnly = true;
    ta.style.cssText = 'width:100%;height:150px;box-sizing:border-box;background:#111827;color:#e5e7eb;border:1px solid #374151;border-radius:6px;padding:8px;font:12px/1.4 monospace;resize:vertical;';
    panel.appendChild(ta);

    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:8px;margin-top:8px;';
    const copyCookie = document.createElement('button');
    copyCookie.textContent = '复制 cookie';
    const copyConfig = document.createElement('button');
    copyConfig.textContent = '复制 config.json';
    const refresh = document.createElement('button');
    refresh.textContent = '刷新';
    for (const btn of [copyCookie, copyConfig, refresh]) {
      btn.style.cssText = 'flex:1;padding:6px 0;background:#374151;color:#fff;border:none;border-radius:6px;cursor:pointer;';
    }
    row.appendChild(copyCookie);
    row.appendChild(copyConfig);
    row.appendChild(refresh);
    panel.appendChild(row);

    const tip = document.createElement('div');
    tip.style.cssText = 'margin-top:8px;color:#9ca3af;font-size:11px;';
    tip.textContent = '需已登录 linux.sb。复制后写入 ~/.config/linuxsb/config.json（uid 填数字）。';
    panel.appendChild(tip);

    document.body.appendChild(panel);

    function refreshAll() {
      const cookie = getCookieString();
      const uid = getUid();
      const ok = cookie.includes('bbs_auth=') && uid;
      status.textContent = ok ? `已登录（uid=${uid}）` : '未登录或未检测到 bbs_auth，请先登录';
      status.style.color = ok ? '#6ee7b7' : '#fca5a5';
      ta.value = buildConfigBlock(cookie, uid);
      copyCookie.onclick = () => { GM_setClipboard(cookie); status.textContent = '已复制 cookie'; };
      copyConfig.onclick = () => { GM_setClipboard(buildConfigBlock(cookie, uid)); status.textContent = '已复制 config.json'; };
    }

    refresh.onclick = refreshAll;
    refreshAll();
  }

  window.addEventListener('load', ensurePanel);
  if (document.readyState === 'complete' || document.readyState === 'interactive') ensurePanel();
})();
