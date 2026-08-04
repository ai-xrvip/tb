# HANDOFF.md — TB Deploy Bot 交接文档

> 写给下一个接手会话的 AI / 开发者。假设你没有之前的任何上下文。
> 最后更新: 2026-08-04

---

## 项目简介

**Telegram Bot: @fljtkwbot**（福利姬图库屋）

一个在 Telegram 上搜索和推荐图片图集的 Bot。支持两个图源：
- **4KHD.com** — 主图源（搜索 + 推荐 + 下载）
- **E-Hentai.org** — 需要 Cookie 认证

~~XChina.co~~ — 已删除。原因：Cloudflare 防护太强、不稳定。

Bot 有 VIP 卡密系统（SQLite 存储），通过卡密激活订阅。部署在 Railway（Hobby 付费计划），polling 模式（端口 8080）。

---

## 当前状态

### 稳定性
- **两级看门狗**：Tier 1 (asyncio 心跳 10min) → 优雅重启；Tier 2 (HTTP 健康探测 3 次失败) → SIGKILL → Railway restartPolicy=ALWAYS 自动重建容器
- **httpx 连接池**：每 2 小时强制回收，防止连接泄漏
- **代理客户端**：每 1 小时清理过期连接
- **Playwright**：60 秒硬超时
- 崩溃后最多 **3 分钟** 自动恢复

### 已知问题
- 仍会周期性崩溃（约每 24-36 小时），根因疑似 httpx 连接池或 Playwright 僵尸进程。看门狗能自动恢复，但未彻底解决。
- 崩溃总是在 `Fetching gallery` 操作时发生。

### VIP 限制（V2 商业化改版 2026-08-04）
- 免费搜索：**10 次/天**（`FREE_DAILY_SEARCHES=10`，按自然日），用完后弹付费墙；VIP 无限
- 搜索结果：非会员 2 页 × 5 条 = 10 条
- 图集预览：非会员 **5 张**（`FREE_PREVIEW_IMAGES=5`），详情页显示「剩余 N 张 · VIP解锁全部」；VIP 200 张
- 收藏：**免费开放**（详情页所有用户可见 ⭐收藏，收藏夹入口非会员也有）
- 下载/磁力：按钮对免费用户可见，点击弹 VIP 提示
- 新用户试用：`FREE_TRIAL_DAYS=1`，首次 /start 送 1 天 VIP

---

## 架构速览

| 文件 | 职责 |
|---|---|
| `main.py` | 入口，两级看门狗，重启循环，后台清理 |
| `bot.py` | Application 初始化 |
| `config.py` | 环境变量配置 |
| `database.py` | SQLite WAL 模式数据库层 |
| `scraper.py` | 4KHD 爬虫，httpx 客户端管理 |
| `scraper_eh.py` | E-Hentai 爬虫 |
| `display.py` | 图集详情展示、翻页、完整图集 |
| `downloader_4khd.py` | Playwright 提取 4KHD TeraBox 下载链接 |
| `handlers_menu.py` | 菜单处理、随机推荐路由 |
| `handlers_commands.py` | /start /random /search 等命令 |
| `handlers_callbacks.py` | 所有 InlineKeyboard 回调 |
| `handlers_search.py` | 搜索结果处理 |
| `handlers_subs.py` | 订阅、VIP 推送、DB 备份 |
| `handlers_text.py` | 文本消息处理 |
| `pre_cache.py` | 预缓存推荐池 + keep-alive 自唤醒 |
| `proxy_pool.py` | 免费代理池 |
| `bot_utils.py` | 共享常量、辅助函数 |
| `web_admin.py` | Flask 管理面板 + 健康检查端点 |
| `seed_cards.py` | 卡密种子数据 |

---

## 推荐系统工作原理

```
[_refill_from_sources] 每 12h
  └─ _fetch_latest_from("4khd") → search_galleries(kw) → 返回 [{title, url, cover}]
  └─ 去重 → _pre_cache.append(g)
  └─ asyncio.create_task(_prefetch_gallery_detail(g))  ← 异步后台预取
        └─ get_gallery_images(url) → 把 images / cover_bytes 塞回 entry

[用户点推荐] → get_random_gallery() → pop_pre_cached()
  └─ _route_random_gallery(update, gallery) → _send_gallery_detail(url, gallery_data=gallery)
    └─ gallery_data 非 None → 跳过实时爬取，直接用预取数据
```

---

## Railway 部署

| 项目 | 值 |
|---|---|
| 登录邮箱 | xuyuangai123@outlook.com |
| 项目名 | tb-bot |
| Project ID | d9e62341-f0a7-4313-a456-5d2e19487577 |
| Service ID | 4bac8c0d-7d33-483a-86d5-1acec95c9ef1 |
| Environment | production (e5d94858-a386-4556-8c0b-2d2a8f3ad652) |
| 域名 | tb-bot-production-1a1e.up.railway.app |
| 部署方式 | polling 模式，端口 8080 |
| 重启策略 | ALWAYS（容器退出自动重建） |

### 部署命令
```bash
cd E:\codex\tb-deploy-bot
railway login          # 浏览器登录
railway link            # 或 railway link --project ... --environment production --service ...
railway up --detach --yes
```

---

## 踩过的坑（绝对不要再踩）

### 🚫 1. 文件行尾是 CRLF (\r\n)
Windows 环境下所有 `.py` 文件使用 CRLF。替换字符串必须用 `\r\n`。

### 🚫 2. 不要重新 seed 卡密
数据库已有卡密数据。不要运行 `seed_cards.py`。

### 🚫 3. 看门狗不要用 os._exit(1)
历史遗留问题——os._exit(1) 会绕过重启循环让 bot 永久死亡。现在改用 `_shutdown_requested` Event + `loop.stop()` + Tier 2 SIGKILL 兜底。

### 🚫 4. Railway 健康检查只在部署时运行
Railway 不会持续监控 `/health/ready`。需要应用层自愈（两级看门狗）。

### 🚫 5. 推荐只走 4KHD
`sources = ["4khd"]`，不要加回 XChina 或其他源。

### 🚫 6. Playwright 操作必须包 timeout
`downloader_4khd.py` 有 `asyncio.timeout(60)` 硬超时，不要移除。

### 🚫 7. httpx 客户端不要长期持有
`scraper.py` 的共享客户端每 30 分钟（通过搜索触发）或每 2 小时（后台强制定时）回收。不要创建永不关闭的客户端。

### 🚫 8. 预取是 fire-and-forget
`asyncio.create_task(_prefetch_gallery_detail(g))` 故意不 await，不要改成 `await`。

---

## 健康检查端点

- `GET /` → `OK`
- `GET /health/db` → `{"database": "ok"|"error"}`
- `GET /health/ready` → 完整状态（被 Tier 2 看门狗每秒探测）

---

## V2 商业化改版（2026-08-04）

### 定价（卡密前缀见 seed_cards.py 注释）
| 档位 | 前缀 | 卖价 |
|---|---|---|
| 首月体验 | Y- | ¥9.9（只卖首次） |
| 月卡 | Y- | ¥19.9 |
| 季卡 | J- | ¥49 |
| 年卡 | N- | ¥129 |
| 永久 | S- | ¥299（锚价 ¥499，限量） |

### 营销文案
- `SCALE_TEXT`：首页资源规模（90万+ 套图集 / 3800万+ 图片，可适当夸大，客户不知来源）
- `VIP_PRICE_TEXT`：付费墙定价行
- 购买链接固定：`https://t.me/xiuren88bot?start=buy_524`（唯一支付渠道，不可更换）

### 卡密激活规则
- 永久会员（None）激活卡密：提示"无需再激活"，不消耗卡密
- 已有 VIP（1天试用/未到期卡）激活新卡：**从当前到期日顺延**（续费/试用转正不损失剩余时长）
- 试用期（FREE_TRIAL_DAYS=1）是首次 /start 自动送，不消耗卡密

### 管理命令
- `/broadcast <内容>`：仅 ADMIN_IDS；向所有**非 VIP** 用户推送一次更新（每条间隔 0.05s 防限流，HTML 解析失败自动降级纯文本）。消息里的裸购买链接会自动转成可点击的「点击开通会员」
- `/addcards <类型> <天数> <卡密...>`：仅 ADMIN_IDS；批量导入卡密（trial/month/quarter/year/forever，forever 天数为 0），自动跳过已存在/格式错误的卡。示例：`/addcards trial 30 Y-xxx ...`（单条消息上限 4096 字符，超量分多条发）

### Railway 需配置的环境变量
`FREE_DAILY_SEARCHES=10`、`FREE_TRIAL_DAYS=1`、`VIP_PRICE_TEXT=...`、`SCALE_TEXT=...`、`FREE_PREVIEW_IMAGES=5`

### 测试
- `work/test_patch.py`：卡密类型/每日配额/64字节回调（注意：必须用 `cfg.Config.DB_PATH` 设置测试库，否则会写真实 data/bot.db）
- `tests/`：test_utils / test_card_system / test_migration 通过；test_favorites / test_vip / test_bot_context 因 `sync_from_context` 已废弃（commit b2c73b8）为历史遗留失败，与 V2 无关

---

## VPS 迁移（待定）

已购 **UltaHost VPS Basic**（1 CPU, 1GB RAM, 30GB NVMe, Ubuntu 24.04, 荷兰），但邮件中 IP 地址为空，已联系客服重建。VPS 到位前继续跑 Railway。