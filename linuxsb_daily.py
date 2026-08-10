#!/usr/bin/env python3
"""
linux.sb 论坛抽奖帖自动回帖脚本（脱敏版）
Auto-reply script for linux.sb lottery topics (sanitized version)

凭据（cookie / UID / PushPlus token）从环境变量或 config.json 读取，不硬编码个人信息。
Credentials (cookie / UID / PushPlus token) are read from env vars or config.json, no hardcoded personal info.

推送方式参考青龙面板（Qinglong-style PushPlus notification）。
"""
import os, sys, time, json, random
import urllib.request
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
    ptoken = os.environ.get("LINUXSB_PUSHPLUS_TOKEN")
    if not cookie or not uid:
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
            cookie = cookie or cfg.get("cookie")
            uid = uid or str(cfg.get("uid", ""))
            ua = cfg.get("user_agent", ua)
            ptoken = ptoken or cfg.get("pushplus_token")
        except FileNotFoundError:
            pass
    if not cookie or not uid:
        print("ERROR: 需要 LINUXSB_COOKIE 和 LINUXSB_UID 环境变量，或 config.json", flush=True)
        print(f"       config path: {CONFIG_PATH}", flush=True)
        print("       See config.example.json for format / 配置格式见 config.example.json", flush=True)
        sys.exit(1)
    return cookie, uid, ua, ptoken


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def send_pushplus(token, title, content):
    """参考青龙面板推送方式：PushPlus 推送 / Qinglong-style PushPlus notification."""
    if not token:
        log("无 PushPlus token，跳过推送 / no PushPlus token, skip notification")
        return False
    payload = json.dumps({"token": token, "title": title, "content": content, "template": "txt"}).encode("utf-8")
    req = urllib.request.Request(
        "https://www.pushplus.plus/send", data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = r.read().decode("utf-8")
            log(f"推送结果 / push result: {resp[:120]}")
            return '"code":200' in resp or '请求成功' in resp
    except Exception as e:
        log(f"推送失败 / push failed: {e}")
        return False


def parse_cookies(s, domain):
    out = []
    for kv in s.split("; "):
        if "=" in kv:
            k, v = kv.split("=", 1)
            out.append({"name": k, "value": v, "domain": domain, "path": "/"})
    return out


REPLY_POOL = {
    "lottery": [
        "参与抽奖，感谢分享",
        "感谢分享，参与抽奖",
        "支持活动，参与抽奖",
        "参与一下期待中奖",
        "期待一下中奖，我来参与",
        "支持楼主，我也来参与抽奖",
        "前排占楼，希望中彩票",
        "抽奖必须参与一下",
        "这个抽奖太给力了，必须参加",
        "抽奖不封号太棒了",
        "已经严肃参与抽奖",
        "我来参与了，祝老板发财",
        "非必要不抽奖，但这个必须参与",
    ],
    "welfare": [
        "感谢福利，支持一下",
        "感谢分享，支持活动",
        "感谢大佬的支持",
        "感谢老板的福利",
        "谢谢大佬，参与一下",
        "我来支持一下",
        "支持楼主，感谢分享",
        "福利不错，感谢楼主",
    ],
    "register": [
        "支持入驻，参与一下",
        "感谢分享，支持入驻",
        "抽中就来注册啦，感谢感谢",
        "已注册，支持一下",
        "注册参与，感谢分享",
    ],
    "default": [
        "感谢分享，参与一下",
        "支持一下，感谢分享",
        "我来看看什么水平",
        "参与一下，支持",
        "感谢分享，支持一下",
    ],
}


def gen_reply(title):
    """根据标题生成 ≥5 字的回复 / Generate a reply (>=5 chars) based on title."""
    t = title
    if "抽奖" in t or "抽" in t:
        return random.choice(REPLY_POOL["lottery"])
    elif "送" in t or "福利" in t:
        return random.choice(REPLY_POOL["welfare"])
    elif "注册" in t or "入驻" in t:
        return random.choice(REPLY_POOL["register"])
    else:
        return random.choice(REPLY_POOL["default"])


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
    cookie, uid, ua, ptoken = load_config()
    log("=== 开始运行 / run started ===")
    detail = []
    ok = skip = fail = 0
    topics = []
    night = False
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"])
        ctx = browser.new_context(user_agent=ua, viewport={"width": 1280, "height": 800}, locale="zh-CN")
        ctx.add_cookies(parse_cookies(cookie, ".linux.sb"))
        page = ctx.new_page()
        topics = get_lottery_topics(page)
        log(f"首页抽奖帖(未结束) / open lottery topics: {len(topics)}")
        if topics:
            ng = check_night(page, topics[0]["tid"])
            night = ng["night"] or ng["turnstile"]
            log(f"夜间守护 / night guard: night={ng['night']} turnstile={ng['turnstile']}")
            if night:
                log("夜间守护中，跳过本次（白天才回帖）/ night guard active, skipping (daytime only)")
            else:
                for t in topics:
                    tid = t["tid"]; title = t["title"][:50]
                    try:
                        r = process_topic(page, tid, title, uid)
                        if r in ("ended", "replied", "no-form", "not-lottery"):
                            log(f"[{tid}] skip={r} {title}")
                            skip += 1
                            detail.append(f"跳过({r}) #{tid} {title[:24]}")
                        elif isinstance(r, dict) and r.get("ok"):
                            log(f"[{tid}] OK '{r['body']}' {title}")
                            ok += 1
                            detail.append(f"回帖成功 #{tid} {r['body']} | {title[:24]}")
                        else:
                            log(f"[{tid}] FAIL {r} {title}")
                            fail += 1
                            detail.append(f"失败 #{tid} {title[:24]}")
                        time.sleep(3)
                    except Exception as e:
                        log(f"[{tid}] ERROR {e}")
                        fail += 1
                        detail.append(f"异常 #{tid} {e}")
        else:
            log("无抽奖帖 / no lottery topics")
        browser.close()
    summary = (
        f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"抽奖帖数: {len(topics)} | 成功: {ok} | 跳过: {skip} | 失败: {fail}\n"
    )
    if night:
        summary = "夜间守护中，本次仅巡检未回帖\n" + summary
    log(f"汇总 / summary: 成功 ok={ok} 跳过 skip={skip} 失败 fail={fail}")
    if ptoken:
        title = f"linuxsb回帖 成功{ok} 跳过{skip} 失败{fail}"
        content = summary + ("\n".join(detail[-15:]) if detail else "")
        send_pushplus(ptoken, title, content)
    log("=== 结束 / finished ===")


if __name__ == "__main__":
    main()
