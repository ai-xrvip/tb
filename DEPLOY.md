# Telegram AI 角色扮演 Bot — Railway 部署指南

## 文件树

```
roleplay-bot/
├── bot.py                 # 入口：多 Bot 并发启动（polling / webhook 自适应）
├── config.py              # 配置管理（多 Bot Token + DeepSeek）
├── database.py            # SQLite 数据库（6 张表，自动建表）
├── roles.py               # 4 个角色定义（system_prompt + media_manifest）
├── import_codes.py        # 激活码批量导入
├── railway.toml           # Railway 部署配置
├── railway.env            # Railway 环境变量清单（粘贴到 Dashboard）
├── requirements.txt       # Python 依赖
├── .env.example           # 本地开发环境变量模板
├── .gitignore             # Git 忽略规则
├── codes.txt              # 激活码源文件
├── utils/
│   ├── __init__.py
│   └── logger.py          # 日志（RotatingFileHandler, 10MB×5）
├── services/
│   ├── __init__.py
│   ├── deepseek.py        # DeepSeek API + 去括号 + 媒体标记解析
│   ├── chat.py            # prompt 构建 + 历史管理 + 摘要 + 分级解锁
│   └── image_gen.py       # AI 照片描述生成（无本地文件时自动回退）
├── handlers/
│   ├── __init__.py
│   ├── commands.py        # /start /redeem /gencode /gifts
│   ├── messages.py        # 核心对话 + 媒体发送 + 礼物里程碑 + 自然延迟 + /upload
│   └── pay.py             # 礼物进度 + 回调（支付待接入）
├── media/                 # 照片文件（可选，无文件时 AI 自动生成文字描述）
│   ├── xiaolu/{日常,通勤,表情,姿势,性感,亲密}/
│   ├── linxi/{日常,通勤,表情,姿势,性感,亲密}/
│   ├── mia/{日常,通勤,表情,姿势,性感,亲密}/
│   └── sunian/{日常,通勤,表情,姿势,性感,亲密}/
└── logs/                  # 自动创建
```

## 一、前置准备

### 1.1 创建 4 个 Telegram Bot

在 [@BotFather](https://t.me/BotFather) 中分别创建：

```
/newbot → 小鹿 → @your_xiaolu_bot
/newbot → 林夕 → @your_linxi_bot
/newbot → Mia  → @your_mia_bot
/newbot → 苏念 → @your_sunian_bot
```

记下每个 Bot 的 Token。

### 1.2 获取 DeepSeek API Key

在 [platform.deepseek.com](https://platform.deepseek.com) 注册并获取 API Key。

### 1.3 获取你的 Telegram ID

向 [@userinfobot](https://t.me/userinfobot) 发消息，复制你的数字 ID。

## 二、推送到 GitHub

```bash
cd roleplay-bot
git init
git add .
git commit -m "init: roleplay bot v2"
git remote add origin https://github.com/你的用户名/roleplay-bot.git
git push -u origin main
```

## 三、Railway 部署

### 3.1 创建项目

1. 打开 [railway.com](https://railway.com)，用 GitHub 登录
2. 点击 **New Project → Deploy from GitHub Repo**
3. 选择刚才推送的 `roleplay-bot` 仓库
4. Railway 自动检测 `railway.toml`，开始构建

### 3.2 设置环境变量

在 Railway Dashboard → 项目 → **Variables** 中，粘贴以下变量：

```
XIAOLU_BOT_TOKEN=你的小鹿Bot_Token
LINXI_BOT_TOKEN=你的林夕Bot_Token
MIA_BOT_TOKEN=你的MiaBot_Token
SUNIAN_BOT_TOKEN=你的苏念Bot_Token
DEEPSEEK_API_KEY=你的DeepSeek_API_Key
ADMIN_IDS=你的Telegram_ID
```

### 3.3 设置 Webhook URL

1. Railway 部署成功后，会分配一个域名，如 `xxx.up.railway.app`
2. 在 Railway Variables 中添加：
   ```
   WEBHOOK_URL=https://xxx.up.railway.app
   ```
3. **Redeploy** 项目使 webhook 模式生效

### 3.4 导入激活码

Railway 没有持久化的 shell，所以需要通过本地导入后重新推送数据库，或者直接用 `/gencode` 命令在 Bot 中生成。

管理员在任意角色 Bot 中发送：
```
/gencode month 10    # 生成 10 个月卡
/gencode quarter 5   # 生成 5 个季卡
/gencode year 3      # 生成 3 个年卡
```

## 四、保活设置

Railway 免费额度每月 $5，项目不使用时进入休眠。用 UptimeRobot 防止休眠：

1. 注册 [uptimerobot.com](https://uptimerobot.com)（免费）
2. 添加 Monitor → HTTP(s) → URL: `https://xxx.up.railway.app/health`
3. 监控间隔设为 **5 分钟**

## 五、验证部署

在 Telegram 中分别搜索你的 4 个 Bot 并发送 `/start`，应该收到对应角色的欢迎消息。

## 六、项目特性

| 功能 | 说明 |
|------|------|
| 多 Bot 独立运行 | 每个角色一个 Bot Token，数据共享 SQLite |
| 照片发送 | 优先从 media/ 读真实文件，无文件时 AI 生成文字描述 |
| 分级解锁 | 0条解锁日常/通勤/表情，30条解锁姿势，50条解锁性感，100条解锁亲密 |
| 自然延迟 | 模拟真人打字节奏（时间段+亲密度+字数） |
| 对话摘要 | 每 20 条消息调用 DeepSeek 生成压缩摘要 |
| 去括号过滤 | 自动清理 AI 回复中的 (动作描述) |
| 日志轮转 | RotatingFileHandler, 10MB × 5 个备份 |
| 礼物里程碑 | 聊到特定消息数触发礼物请求（VIP 免费解锁） |
| /upload | 管理员在 Bot 中直接上传照片到对应分类 |
| /gencode | 管理员在 Bot 中生成激活码 |

## 七、后续接入真实图片生成

编辑 `services/image_gen.py`，替换 `generate_scene_image()` 函数，调用图片生成 API：

```python
# 示例：接入 Replicate / Stable Diffusion
async def generate_scene_image(role_id, category):
    import replicate
    output = replicate.run("stability-ai/...", input={"prompt": ...})
    return output[0]  # 返回图片 URL
```

## 八、命令速查

| 命令 | 说明 | 权限 |
|------|------|------|
| /start | 查看状态 | 所有人 |
| /redeem CODE | 兑换激活码 | 所有人 |
| /gifts | 查看礼物进度 | 所有人 |
| /gencode TYPE N | 生成激活码 | 管理员 |
| /upload | 上传照片/视频 | 管理员 |
