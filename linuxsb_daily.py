#!/usr/bin/env python3
"""
linux.sb 论坛抽奖帖自动回帖脚本（脱敏版）
Auto-reply script for linux.sb lottery topics (sanitized version)

凭据（cookie / UID）从环境变量或 config.json 读取，不硬编码个人信息。
Credentials (cookie / UID) are read from env vars or config.json, no hardcoded personal info.
"""
import os, sys, time, json, random
from datetime import datetime
from playwright.sync_api import sync_playwright

CONFIG_PATH = os.environ.get("LINUXSB_CONFIG", os.path.expanduser("~/.config/linuxsb/config.json"))
LOG_FILE = os.environ.get("LINUXSB_LOG", "/root/linuxsb_reply.log")
DEFAULT_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def load_config():
    """读取凭据：优先环境变量，其次 config.json / Read creds: env vars first, then config.json."""
    cookie = os.environ.get("LINUXSB_COOKIE")
    uid = os.environ.get("LINUXSB_UID")
    ua = os.environ.get("LINUXSB_UA", DEFAULT_UA)
    if not cookie or not uid:
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
            cookie = cookie or cfg.get("cookie")
            uid = uid or str(cfg.get("uid", ""))
            ua = cfg.get("user_agent", ua)
        except FileNotFoundError:
            pass
    if not cookie or not uid:
        print("ERROR: 需要 LINUXSB_COOKIE 和 LINUXSB_UID 环境变量，或 config.json", flush=True)
        print(f"       config path: {CONFIG_PATH}", flush=True)
        print("       See config.example.json for format / 配置格式见 config.example.json", flush=True)
        sys.exit(1)
    return cookie, uid, ua


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def parse_cookies(s, domain):
    out = []
    for kv in s.split("; "):
        if "=" in kv:
            k, v = kv.split("=", 1)
            out.append({"name": k, "value": v, "domain": domain, "path": "/"})
    return out


def gen_reply(title):
    """根据标题生成 ≥5 字的回复 / Generate a reply (>=5 chars) based on title."""
    t = title
    if "抽奖" in t or "抽" in t:
        return random.choice(["参与抽奖，感谢分享", "感谢分享，参与抽奖", "支持活动，参与抽奖"])
    elif "送" in t or "福利" in t:
        return random.choice(["感谢福利，支持一下", "感谢分享，支持活动"])
    elif "注册" in t or "入驻" in t:
        return random.choice(["支持入驻，参与一下", "感谢分享，支持入驻"])
    else:
        return random.choice(["感谢分享，参与一下", "支持一下，感谢分享"])


def get_lottery_topics(page):
    """抓取首页所有「抽奖中且未结束」的帖子 / Scrape homepage for open lottery topics."""
    page.goto("https://linux.sb/", wait_until="domcontentloaded", timeout=20000)
    time.sleep(2)
    return page.evaluate(r"""() => {
        const links = document.querySelectorAll('a[href*="/topic/"]');
        const seen = new Set();
        const items = [];
        links.forEach(a => {
            const m = a.href.match(/\/topic\/(\d+)/);
            if (!m || seen.has(m[1])) return;
            seen.add(m[1]);
            let p = a;
            for (let i=0;i<6;i++){ p=p.parentElement; if(!p) break; if(p.innerText && p.innerText.length>30) break; }
            const ct = p ? p.innerText : a.innerText;
            const isLot = /抽奖|抽\s*\d|送\s*\d|兑换码|抽中|福利|抽[一十百千万]/.test(ct);
            const ended = /已结束|已开奖|ended|closed/.test(ct);
            if (isLot && !ended) items.push({tid:m[1], title:a.innerText.trim().substring(0,70)});
        });
        return items;
    }""")


def check_night(page, tid):
    """检测夜间守护是否触发 / Detect whether night-guard captcha is active."""
    page.goto(f"https://linux.sb/topic/{tid}", wait_until="domcontentloaded", timeout=20000)
    time.sleep(2)
    return page.evaluate("""() => {
        const ng = document.querySelector('.night-guard-captcha-notice');
        const ts = document.querySelector('.cf-turnstile');
        return {night: !!(ng && ng.offsetParent !== null), turnstile: !!ts};
    }""")


def process_topic(page, tid, title, uid):
    """处理单个帖子：检查状态/已回帖 → 生成内容 → fetch 提交 / Process one topic."""
    page.goto(f"https://linux.sb/topic/{tid}", wait_until="domcontentloaded", timeout=20000)
    time.sleep(2)
    info = page.evaluate(r"""(uid) => {
        const status = document.querySelector('.lottery-title-status');
        const card = document.querySelector('.lottery-card');
        const myReplies = document.querySelectorAll(`.post-item a[href="/user/${uid}"], .post-entry a[href="/user/${uid}"]`);
        const st = status ? status.innerText.trim() : '';
        return {
            hasLottery: !!card, status: st, ended: /已开奖|已结束/.test(st),
            replied: myReplies.length > 0,
            csrf: (document.querySelector('input[name=_csrf]')||{}).value,
            topicId: (document.querySelector('input[name=topic_id]')||{}).value,
            hasTextarea: !!document.querySelector('textarea[name=body]')
        };
    }""", uid)
    if not info["hasLottery"]:
        return "not-lottery"
    if info["ended"]:
        return "ended"
    if info["replied"]:
        return "replied"
    if not info["hasTextarea"] or not info["csrf"]:
        return "no-form"
    body = gen_reply(title)
    result = page.evaluate("""async (args) => {
        const fd = new FormData();
        fd.append('_csrf', args.csrf); fd.append('topic_id', args.topicId); fd.append('body', args.body);
        const r = await fetch('/reply_edit', {method:'POST', body: fd, headers:{'X-Requested-With':'XMLHttpRequest'}});
        const text = await r.text();
        return {status: r.status, ok: text.indexOf('"ok":1')>=0, head: text.substring(0,120)};
    }""", {"csrf": info["csrf"], "topicId": info["topicId"], "body": body})
    return {"body": body, "ok": result["ok"], "status": result["status"], "head": result["head"]}


def main():
    cookie, uid, ua = load_config()
    log("=== 开始运行 / run started ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"])
        ctx = browser.new_context(user_agent=ua, viewport={"width": 1280, "height": 800}, locale="zh-CN")
        ctx.add_cookies(parse_cookies(cookie, ".linux.sb"))
        page = ctx.new_page()
        topics = get_lottery_topics(page)
        log(f"首页抽奖帖(未结束) / open lottery topics: {len(topics)}")
        if not topics:
            log("无抽奖帖，退出 / no lottery topics, exit")
            browser.close()
            return
        ng = check_night(page, topics[0]["tid"])
        log(f"夜间守护 / night guard: night={ng['night']} turnstile={ng['turnstile']}")
        if ng["night"] or ng["turnstile"]:
            log("夜间守护中，跳过本次（白天才回帖）/ night guard active, skipping (daytime only)")
            browser.close()
            return
        ok = 0; skip = 0; fail = 0
        for t in topics:
            tid = t["tid"]; title = t["title"][:50]
            try:
                r = process_topic(page, tid, title, uid)
                if r in ("ended", "replied", "no-form", "not-lottery"):
                    log(f"[{tid}] skip={r} {title}")
                    skip += 1
                elif isinstance(r, dict) and r.get("ok"):
                    log(f"[{tid}] OK '{r['body']}' {title}")
                    ok += 1
                else:
                    log(f"[{tid}] FAIL {r} {title}")
                    fail += 1
                time.sleep(3)
            except Exception as e:
                log(f"[{tid}] ERROR {e}")
                fail += 1
        log(f"汇总 / summary: 成功 ok={ok} 跳过 skip={skip} 失败 fail={fail}")
        browser.close()
    log("=== 结束 / finished ===")


if __name__ == "__main__":
    main()
