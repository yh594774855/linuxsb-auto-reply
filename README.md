# linuxsb-auto-reply | linux.sb 抽奖帖自动回帖

> 自动参与 linux.sb 论坛抽奖帖的回帖脚本（白天定时运行，夜间自动跳过）。
>
> Auto-reply script for linux.sb lottery topics — runs on a daytime schedule, auto-skips at night.

---

## 简介 / Overview

**中文**：本脚本自动抓取 linux.sb 论坛首页的抽奖帖，对「抽奖中且未结束、自己未回过」的帖子生成符合主题的回复（≥5 字）并提交。仅在你账号的登录态下运行，回帖内容符合帖子「回复满 5 字即参与」的要求。

**English**: This script scrapes lottery topics from the linux.sb homepage and, for those that are open, not ended, and not yet replied to by you, generates an on-topic reply (≥5 chars) and submits it. It runs under your own logged-in account; replies meet the "reply with 5+ characters to enter" requirement.

---

## 工作原理 / How It Works

1. 抓取首页所有含抽奖关键词且未结束的帖子 / Scrape homepage for open lottery topics
2. 检测夜间守护（Cloudflare Turnstile）/ Detect night-guard (Cloudflare Turnstile)
3. **夜间 → 跳过本次**（白天才回帖）/ **Night → skip** (daytime only)
4. **白天 → 逐个帖子**：检查状态/已回帖 → 生成内容 → fetch 提交 / **Day → per topic**: check status/replied → generate → fetch submit
5. 回帖 API：`POST /reply_edit`，字段 `_csrf` + `topic_id` + `body` → `{"ok":1}` / Reply API: `POST /reply_edit`

---

## 安装 / Installation

**中文**：需要 Python 3.10+ 和 Playwright + Chromium。
**English**: Requires Python 3.10+ and Playwright + Chromium.

```bash
pip install playwright
playwright install --with-deps chromium
```

---

## 配置 / Configuration

**中文**：凭据从环境变量或 `config.json` 读取，**不硬编码**任何个人信息。复制 `config.example.json` 为 `config.json`，填入你的 cookie 和 UID。
**English**: Credentials are read from env vars or `config.json` — **never hardcoded**. Copy `config.example.json` to `config.json` and fill in your cookie and UID.

环境变量 / Env vars:
- `LINUXSB_COOKIE` — 完整 cookie 字符串 / full cookie string
- `LINUXSB_UID` — 你的数字用户 ID / your numeric user ID
- `LINUXSB_PUSHPLUS_TOKEN` — PushPlus 推送 token（可选，青龙面板同款）/ PushPlus token, optional (Qinglong-style)

或 `config.json`（默认 `~/.config/linuxsb/config.json`）/ Or `config.json` (default `~/.config/linuxsb/config.json`):

```json
{
  "cookie": "<your full cookie string here>",
  "uid": 12345,
  "pushplus_token": "<your PushPlus token, optional>"
}
```

> ⚠️ `config.json` 已在 `.gitignore` 中，切勿提交凭据。 / `config.json` is gitignored — never commit credentials.

---

## 使用 / Usage

手动运行 / Manual run:
```bash
python linuxsb_daily.py
```

定时（cron，北京白天每 2 小时）/ Schedule (cron, every 2h Beijing daytime):
```
0 8,10,12,14,16,18,20 * * * /usr/bin/python3 /path/to/linuxsb_daily.py > /dev/null 2>&1
```

日志 / Log: 默认 `/root/linuxsb_reply.log`（可设 `LINUXSB_LOG`）/ Default `/root/linuxsb_reply.log` (set `LINUXSB_LOG`).

## 推送通知 / Notifications

**中文**：每次运行结束会生成运行总结（抽奖帖数 / 成功 / 跳过 / 失败 + 明细），参考青龙面板的 PushPlus 推送方式发送到你的微信。配置 `LINUXSB_PUSHPLUS_TOKEN` 或 config.json 的 `pushplus_token` 即启用；未配置则跳过推送。
**English**: After each run, a summary (topics / ok / skip / fail + details) is pushed to your WeChat via PushPlus, the same way Qinglong does it. Set `LINUXSB_PUSHPLUS_TOKEN` or `pushplus_token` in config.json to enable; skipped if not set.

---

## 限制 / Limitations

**中文**：夜间（北京约 21:00 起）论坛启用 Cloudflare Turnstile 人机验证。在无 GPU 的服务器上（headless / headless+xvfb / stealth）均无法自动通过 —— Cloudflare 检测到虚拟显示无真实 GPU 而拒绝发放 token。因此脚本策略：**白天回帖，夜间自动跳过**。

**English**: At night (~21:00 Beijing) the forum enables Cloudflare Turnstile. On a GPU-less server (headless / headless+xvfb / stealth) it cannot be solved automatically — Cloudflare detects the virtual display lacks a real GPU and refuses to issue a token. So the strategy: **reply by day, auto-skip by night**.

---

## 合规声明 / Disclaimer

**中文**：本脚本仅供你在自己账号下自动化参与抽奖回帖，回帖内容符合帖子要求（≥5 字、贴合主题）。请勿用于刷量、灌水或绕过论坛风控。

**English**: This script is for automating your own lottery replies under your own account, with on-topic replies meeting topic rules (≥5 chars). Do not use for spamming, astroturfing, or evading forum controls.

---

## License

MIT
