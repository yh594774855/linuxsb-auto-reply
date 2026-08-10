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
STATE_PATH = os.environ.get("LINUXSB_STATE", os.path.expanduser("~/.config/linuxsb/state.json"))
STATE_TTL_DAYS = int(os.environ.get("LINUXSB_STATE_TTL_DAYS", "3"))
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


def load_state():
    """读取已回帖抽奖帖状态 / Load replied-lottery tracking state."""
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"replies": {}}


def save_state(state):
    """原子写状态文件 / Atomically persist state."""
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_PATH)
    except Exception as e:
        log(f"保存状态失败 / save state failed: {e}")


def cleanup_state(state):
    """清理超过 TTL 的记录 / Drop records older than TTL days."""
    now = datetime.now()
    for tid in list(state.get("replies", {})):
        rec = state["replies"][tid]
        try:
            replied = datetime.strptime(rec.get("replied_at", ""), "%Y-%m-%d %H:%M")
        except (ValueError, KeyError):
            del state["replies"][tid]
            continue
        if (now - replied).days >= STATE_TTL_DAYS:
            log(f"[{tid}] 清理记录(>{STATE_TTL_DAYS}天) / cleanup: {rec.get('title','')[:40]}")
            del state["replies"][tid]


def track_reply(state, tid, title, body):
    """记录已回帖的抽奖帖 / Record a replied lottery topic."""
    replies = state.setdefault("replies", {})
    if tid not in replies:
        replies[tid] = {
            "title": title[:70],
            "body": body,
            "replied_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "result": "pending",   # pending / won / lost
            "notified": False,
        }
        save_state(state)


def check_winners(page, uid, state):
    """检查已回帖帖子的开奖结果，返回新出现的开奖结果 / Check lottery results of tracked topics."""
    results = []
    replies = state.get("replies", {})
    for tid in list(replies):
        rec = replies[tid]
        if rec.get("notified"):
            continue
        try:
            page.goto(f"https://linux.sb/topic/{tid}", wait_until="domcontentloaded", timeout=20000)
            time.sleep(2)
            info = page.evaluate("""() => {
                const st = document.querySelector('.lottery-title-status');
                const status = st ? st.innerText.trim() : '';
                const uids = [];
                document.querySelectorAll('.lottery-winners a[href^="/user/"]').forEach(a => {
                    const m = a.href.match(/\\/user\\/(\\d+)/);
                    if (m) uids.push(m[1]);
                });
                return {status: status, winnerUids: uids};
            }""")
            if "已开奖" in info["status"]:
                won = str(uid) in info["winnerUids"]
                rec["result"] = "won" if won else "lost"
                rec["notified"] = True
                results.append({"tid": tid, "title": rec.get("title", ""), "won": won, "winnerUids": info["winnerUids"]})
                log(f"[{tid}] 已开奖 {'中奖!' if won else '未中'} / opened {'WON' if won else 'not won'}: {rec.get('title','')[:40]}")
            # 未开奖则保留等待下次
        except Exception as e:
            log(f"[{tid}] 开奖检查异常 / winner check error: {e}")
    return results


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


def daily_checkin(page):
    """每日签到 / daily_checkin: POST /daily_checkin with _csrf. Idempotent (today signed -> skip)."""
    page.goto("https://linux.sb/daily_checkin", wait_until="domcontentloaded", timeout=20000)
    time.sleep(2)
    state = page.evaluate("""() => ({
        already: /今天已签到/.test(document.body.innerText),
        csrf: (document.querySelector('form.post-action-form input[name=_csrf]')||{}).value || '',
        hasBtn: !!document.querySelector('button.daily-checkin-btn')
    })""")
    if state["already"]:
        return {"ok": True, "already": True}
    if not state["csrf"] or not state["hasBtn"]:
        return {"ok": False, "already": False, "reason": "no-form"}
    resp = page.evaluate("""async () => {
        const fd = new FormData();
        fd.append('_csrf', document.querySelector('form.post-action-form input[name=_csrf]').value);
        const r = await fetch('/daily_checkin', {method:'POST', body: fd, headers:{'X-Requested-With':'XMLHttpRequest'}});
        return {status: r.status, head: (await r.text()).substring(0, 150)};
    }""")
    time.sleep(2)
    page.goto("https://linux.sb/daily_checkin", wait_until="domcontentloaded", timeout=20000)
    time.sleep(2)
    ok = page.evaluate("() => /今天已签到/.test(document.body.innerText)")
    return {"ok": ok, "already": False, "status": resp.get("status"), "head": resp.get("head")}


def check_login(page, uid):
    """检测当前 cookie 登录态是否有效 / Check whether the session cookie is still valid."""
    return page.evaluate("""(uid) => {
        const loginLinks = document.querySelectorAll('a[href="/login"]');
        const myLinks = document.querySelectorAll('a[href^="/user/' + uid + '"], .nav-mine, a.user-name');
        return {hasLogin: loginLinks.length > 0, hasUser: myLinks.length > 0, loggedIn: myLinks.length > 0};
    }""", uid)


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
    checkin_info = None
    state = load_state()
    winner_results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"])
        ctx = browser.new_context(user_agent=ua, viewport={"width": 1280, "height": 800}, locale="zh-CN")
        ctx.add_cookies(parse_cookies(cookie, ".linux.sb"))
        page = ctx.new_page()
        try:
            checkin_info = daily_checkin(page)
            if checkin_info.get("already"):
                log("签到 / checkin: 今日已签到 / already checked in today")
            elif checkin_info.get("ok"):
                log("签到 / checkin: 签到成功 / checkin success")
            else:
                log(f"签到 / checkin: 失败 {checkin_info}")
        except Exception as e:
            checkin_info = {"ok": False, "error": str(e)}
            log(f"签到异常 / checkin error: {e}")
        topics = get_lottery_topics(page)
        log(f"首页抽奖帖(未结束) / open lottery topics: {len(topics)}")
        try:
            auth = check_login(page, uid)
            log(f"登录态 / login state: logged_in={auth['loggedIn']} hasUser={auth['hasUser']} hasLogin={auth['hasLogin']}")
        except Exception as e:
            auth = {"loggedIn": True}
            log(f"登录态检测异常 / login check error: {e}")
        if not auth.get("loggedIn", True):
            log("!!! cookie 已失效 / session cookie expired, aborting")
            if ptoken:
                send_pushplus(ptoken, "[cookie失效] linux.sb 会话过期", "linuxsb 脚本检测到 cookie 已失效，请用油猴脚本重新提取 cookie 并更新 ~/.config/linuxsb/config.json，然后手动运行一次验证。")
            browser.close()
            return
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
                        if tid in state.get("replies", {}) and state["replies"][tid].get("body"):
                            log(f"[{tid}] skip=tracked(state) {title}")
                            skip += 1
                            detail.append(f"跳过(已记录) #{tid} {title[:24]}")
                            time.sleep(3)
                            continue
                        r = process_topic(page, tid, title, uid)
                        if r in ("ended", "no-form", "not-lottery"):
                            log(f"[{tid}] skip={r} {title}")
                            skip += 1
                            detail.append(f"跳过({r}) #{tid} {title[:24]}")
                        elif r == "replied":
                            log(f"[{tid}] skip=replied {title}")
                            skip += 1
                            detail.append(f"跳过(replied) #{tid} {title[:24]}")
                            track_reply(state, tid, title, "")
                        elif isinstance(r, dict) and r.get("ok"):
                            log(f"[{tid}] OK '{r['body']}' {title}")
                            ok += 1
                            detail.append(f"回帖成功 #{tid} {r['body']} | {title[:24]}")
                            track_reply(state, tid, title, r["body"])
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
        # 开奖结果检查（夜间也执行，只读页面）
        try:
            winner_results = check_winners(page, uid, state)
            cleanup_state(state)
            save_state(state)
        except Exception as e:
            log(f"开奖检查/状态保存异常 / winner check error: {e}")
        browser.close()
    won_list = [w for w in winner_results if w["won"]]
    lost_list = [w for w in winner_results if not w["won"]]
    if won_list:
        log(">>> 中奖! / WON: " + "; ".join(f"#{w['tid']} {w['title'][:30]}" for w in won_list))
    summary = (
        f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"签到: {('今日已签到' if checkin_info and checkin_info.get('already') else ('成功' if checkin_info and checkin_info.get('ok') else '失败'))}\n"
        f"抽奖帖数: {len(topics)} | 成功: {ok} | 跳过: {skip} | 失败: {fail}\n"
    )
    if night:
        summary = "夜间守护中，本次仅巡检未回帖\n" + summary
    if winner_results:
        wlines = []
        for w in winner_results:
            wlines.append(f"{'中奖' if w['won'] else '未中'} #{w['tid']} {w['title'][:30]}")
        summary += "\n开奖结果 / lottery results:\n" + "\n".join(wlines)
    log(f"汇总 / summary: 签到={summary.splitlines()[1]} 成功 ok={ok} 跳过 skip={skip} 失败 fail={fail} 开奖={len(winner_results)}")
    if ptoken:
        title = f"linuxsb 签到{'成功' if checkin_info and checkin_info.get('ok') else '失败'} 回帖 成功{ok} 跳过{skip} 失败{fail}"
        if won_list:
            title = f"[中奖] linuxsb 抽奖中了 {len(won_list)} 个!" 
        content = summary + ("\n" + "\n".join(detail[-15:]) if detail else "")
        send_pushplus(ptoken, title, content)
    log("=== 结束 / finished ===")


if __name__ == "__main__":
    main()
