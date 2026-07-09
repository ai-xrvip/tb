"""Flask web admin dashboard — runs alongside the Telegram bot, sharing the HTTP port.

Routes:
  GET  /admin             — login page (token-based)
  GET  /admin/dashboard   — main dashboard (requires valid token)
  GET  /admin/api/stats   — JSON API for dashboard data
  GET  /health/db         — DB ping
  GET  /health/ready      — full readiness check
  GET  /                  — OK

Authentication: a simple shared secret token (ADMIN_WEB_TOKEN in .env).
Set it to a random string; share it with admins via the /admin URL param.
Example: https://your-app.up.railway.app/admin?token=YOUR_SECRET
"""
from __future__ import annotations

import atexit
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, render_template_string, request, redirect

from config import config

logger = logging.getLogger(__name__)

ADMIN_WEB_TOKEN: str = config.ADMIN_WEB_TOKEN
DB_PATH: str = config.DB_PATH

app = Flask(__name__, template_folder=None)

# ---------------------------------------------------------------------------
# Templates (inline — no external files needed)
# ---------------------------------------------------------------------------

LOGIN_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin Login — 4KHD Bot</title>
<style>
:root { color-scheme: light; --bg: #f5f5f7; --card: #fff; --text: #1d1d1f; --muted: #6e6e73; --accent: #0071e3; --border: #d2d2d7; --green: #34c759; --red: #ff3b30; --orange: #ff9500; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); display: flex; justify-content: center; align-items: center; min-height: 100vh; }
.card { background: var(--card); border-radius: 18px; padding: 40px; max-width: 400px; width: 90%; box-shadow: 0 2px 12px rgba(0,0,0,0.08); text-align: center; }
h1 { font-size: 24px; font-weight: 600; margin-bottom: 8px; }
p.desc { color: var(--muted); font-size: 14px; margin-bottom: 24px; }
input { width: 100%; padding: 12px 16px; border: 1px solid var(--border); border-radius: 10px; font-size: 15px; outline: none; transition: border .2s; }
input:focus { border-color: var(--accent); }
button { width: 100%; padding: 12px; background: var(--accent); color: #fff; border: none; border-radius: 10px; font-size: 15px; font-weight: 500; cursor: pointer; margin-top: 16px; }
.error { color: var(--red); font-size: 13px; margin-top: 12px; }
</style>
</head>
<body>
<div class="card">
<h1>📊 管理后台</h1>
<p class="desc">请输入访问令牌</p>
<form method="get" action="/admin/dashboard">
<input name="token" type="password" placeholder="输入 Token..." value="{{ token }}">
<button type="submit">登录</button>
</form>
{% if error %}<div class="error">{{ error }}</div>{% endif %}
</div>
</body>
</html>"""

DASHBOARD_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin Dashboard — 4KHD Bot</title>
<style>
:root { color-scheme: light; --bg: #f5f5f7; --card: #fff; --text: #1d1d1f; --muted: #6e6e73; --accent: #0071e3; --border: #d2d2d7; --green: #34c759; --red: #ff3b30; --orange: #ff9500; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); padding: 24px; max-width: 960px; margin: 0 auto; }
h1 { font-size: 26px; font-weight: 700; margin-bottom: 4px; }
.subtitle { color: var(--muted); font-size: 14px; margin-bottom: 24px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
.stat-card { background: var(--card); border-radius: 14px; padding: 20px; box-shadow: 0 1px 6px rgba(0,0,0,0.06); }
.stat-label { font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--muted); margin-bottom: 6px; }
.stat-value { font-size: 28px; font-weight: 700; }
.stat-sub { font-size: 12px; color: var(--muted); margin-top: 2px; }
.green { color: var(--green); }
.red { color: var(--red); }
.orange { color: var(--orange); }
.card { background: var(--card); border-radius: 14px; padding: 24px; box-shadow: 0 1px 6px rgba(0,0,0,0.06); margin-bottom: 16px; }
.card h2 { font-size: 17px; font-weight: 600; margin-bottom: 16px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-weight: 500; font-size: 12px; text-transform: uppercase; }
.meter { height: 8px; border-radius: 4px; background: var(--border); overflow: hidden; }
.meter-fill { height: 100%; border-radius: 4px; background: var(--accent); transition: width .3s; }
.refresh { color: var(--muted); font-size: 12px; margin-top: 16px; }
</style>
</head>
<body>
<h1>📊 4KHD Bot 管理后台</h1>
<p class="subtitle">{{ now }} · 数据每 30 秒自动刷新</p>

<div class="grid">
<div class="stat-card">
<div class="stat-label">总用户</div>
<div class="stat-value">{{ data.total_users }}</div>
<div class="stat-sub">VIP {{ data.vip_total }} ({{ data.vip_permanent }}永久)</div>
</div>
<div class="stat-card">
<div class="stat-label">今日新增</div>
<div class="stat-value green">{{ data.today_new_users }}</div>
<div class="stat-sub">昨日 +{{ data.yesterday_new_users }}</div>
</div>
<div class="stat-card">
<div class="stat-label">今日搜索</div>
<div class="stat-value">{{ data.today_searches }}</div>
<div class="stat-sub">昨日 {{ data.yesterday_searches }}</div>
</div>
<div class="stat-card">
<div class="stat-label">卡密使用率</div>
<div class="stat-value">{{ data.card_usage }}%</div>
<div class="stat-sub">{{ data.cards_used }} / {{ data.cards_total }}</div>
<div class="meter" style="margin-top:8px"><div class="meter-fill" style="width:{{ data.card_usage }}%"></div></div>
</div>
</div>

<div class="grid">
<div class="stat-card">
<div class="stat-label">今日激活</div>
<div class="stat-value orange">{{ data.today_activations }}</div>
<div class="stat-sub">昨日 {{ data.yesterday_activations }}</div>
</div>
<div class="stat-card">
<div class="stat-label">预缓存</div>
<div class="stat-value">{{ data.pre_cache_size }}</div>
<div class="stat-sub">/random 备用池</div>
</div>
<div class="stat-card">
<div class="stat-label">数据库健康</div>
<div class="stat-value green">{{ data.db_status }}</div>
<div class="stat-sub">{{ data.db_size }}</div>
</div>
<div class="stat-card">
<div class="stat-label">订阅数量</div>
<div class="stat-value">{{ data.subscription_count }}</div>
<div class="stat-sub">活跃推送中</div>
</div>
</div>

<div class="card">
<h2>📈 最近 7 天趋势</h2>
<table>
<tr><th>日期</th><th>新增用户</th><th>卡密激活</th><th>搜索次数</th><th>点击次数</th></tr>
{% for r in data.daily_stats %}
<tr>
<td>{{ r.date }}</td>
<td>{{ r.new_users }}</td>
<td>{{ r.card_activations }}</td>
<td>{{ r.searches }}</td>
<td>{{ r.clicks }}</td>
</tr>
{% endfor %}
{% if not data.daily_stats %}
<tr><td colspan="5" style="color:var(--muted);text-align:center">暂无数据</td></tr>
{% endif %}
</table>
</div>

<div class="card">
<h2>👑 VIP 用户 (到期临近)</h2>
<table>
<tr><th>用户 ID</th><th>到期时间</th><th>剩余天数</th></tr>
{% for v in data.expiring_vip %}
<tr>
<td><code>{{ v.user_id }}</code></td>
<td>{{ v.expiry_date }}</td>
<td class="{% if v.days_left <= 1 %}red{% elif v.days_left <= 3 %}orange{% else %}green{% endif %}">{{ v.days_left }} 天</td>
</tr>
{% endfor %}
{% if not data.expiring_vip %}
<tr><td colspan="3" style="color:var(--muted);text-align:center">暂无即将到期的 VIP</td></tr>
{% endif %}
</table>
</div>

<p class="refresh">🔄 页面会自动刷新</p>
<script>
setTimeout(function(){ location.reload(); }, 30000);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _check_token() -> bool:
    if not ADMIN_WEB_TOKEN:
        return True  # no token configured — open access
    return request.args.get("token", "") == ADMIN_WEB_TOKEN


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def root():
    return "OK", 200, {"Content-Type": "text/plain"}


@app.route("/health/db")
def health_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("SELECT 1")
        conn.close()
        return jsonify({"database": "ok"})
    except Exception:
        return jsonify({"database": "error"}), 500


@app.route("/health/ready")
def health_ready():
    db_ok = True
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("SELECT 1")
        conn.close()
    except Exception:
        db_ok = False

    # Proxy pool size (import from bot module may fail if not started yet)
    pool_size = 0
    try:
        from proxy_pool import _proxy_pool
        pool_size = len(_proxy_pool)
    except Exception:
        pass

    # Pre-cache size
    cache_size = 0
    try:
        from pre_cache import _pre_cache
        cache_size = len(_pre_cache)
    except Exception:
        pass

    return jsonify({
        "status": "ready" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "proxy_pool_size": pool_size,
        "pre_cache_size": cache_size,
    })


@app.route("/admin")
def admin_login():
    token = request.args.get("token", "")
    error = None
    if token:
        if ADMIN_WEB_TOKEN and token != ADMIN_WEB_TOKEN:
            error = "令牌无效"
        else:
            return redirect(f"/admin/dashboard?token={token}")
    return render_template_string(LOGIN_PAGE, token=token, error=error)


@app.route("/admin/dashboard")
def admin_dashboard():
    if not _check_token():
        return render_template_string(LOGIN_PAGE, token="", error="令牌无效")

    token = request.args.get("token", "")
    data = _gather_data()
    return render_template_string(
        DASHBOARD_PAGE,
        now=datetime.now().strftime("%Y-%m-%d %H:%M"),
        data=data,
        token=token,
    )


@app.route("/admin/api/stats")
def admin_api_stats():
    if not _check_token():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(_gather_data())


# ---------------------------------------------------------------------------
# Data gathering
# ---------------------------------------------------------------------------

def _gather_data() -> dict:
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))

    # Totals
    total_users = conn.execute("SELECT COUNT(*) as c FROM all_users").fetchone()["c"]
    vip_total = conn.execute("SELECT COUNT(*) as c FROM vip_users").fetchone()["c"]
    vip_permanent = conn.execute("SELECT COUNT(*) as c FROM vip_users WHERE expiry IS NULL").fetchone()["c"]
    cards_total = conn.execute("SELECT COUNT(*) as c FROM cards").fetchone()["c"]
    cards_used = conn.execute("SELECT COUNT(*) as c FROM cards WHERE used=1").fetchone()["c"]
    card_usage = round(cards_used / cards_total * 100, 1) if cards_total > 0 else 0
    sub_count = conn.execute("SELECT COUNT(*) as c FROM subscriptions").fetchone()["c"]

    # Today stats
    today_row = conn.execute("SELECT * FROM stats_daily WHERE date=?", (today_str,)).fetchone() or {}
    yesterday_row = conn.execute("SELECT * FROM stats_daily WHERE date=?", (yesterday_str,)).fetchone() or {}

    # Daily stats for last 7 days
    seven_days_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    daily = conn.execute(
        "SELECT * FROM stats_daily WHERE date >= ? ORDER BY date DESC",
        (seven_days_ago,),
    ).fetchall()

    # Expiring VIPs (next 30 days)
    cutoff = time.time() + 30 * 86400
    expiring = conn.execute(
        "SELECT user_id, expiry FROM vip_users WHERE expiry IS NOT NULL AND expiry < ? ORDER BY expiry LIMIT 20",
        (cutoff,),
    ).fetchall()
    expiring_vip = []
    for e in expiring:
        days_left = max(0, int((e["expiry"] - time.time()) / 86400))
        expiring_vip.append({
            "user_id": e["user_id"],
            "expiry_date": datetime.fromtimestamp(e["expiry"]).strftime("%Y-%m-%d"),
            "days_left": days_left,
        })

    # DB file size
    db_path = Path(DB_PATH)
    db_size = f"{db_path.stat().st_size / 1024 / 1024:.1f} MB" if db_path.exists() else "N/A"
    db_status = "正常" if db_path.exists() else "异常"

    # Pre-cache size
    pre_cache_size = 0
    try:
        from pre_cache import _pre_cache
        pre_cache_size = len(_pre_cache)
    except Exception:
        pass

    conn.close()

    return {
        "total_users": total_users,
        "vip_total": vip_total,
        "vip_permanent": vip_permanent,
        "cards_total": cards_total,
        "cards_used": cards_used,
        "card_usage": card_usage,
        "subscription_count": sub_count,
        "today_new_users": today_row.get("new_users", 0),
        "today_searches": today_row.get("searches", 0),
        "today_activations": today_row.get("card_activations", 0),
        "today_clicks": today_row.get("clicks", 0),
        "yesterday_new_users": yesterday_row.get("new_users", 0),
        "yesterday_searches": yesterday_row.get("searches", 0),
        "yesterday_activations": yesterday_row.get("card_activations", 0),
        "yesterday_clicks": yesterday_row.get("clicks", 0),
        "daily_stats": daily,
        "expiring_vip": expiring_vip,
        "pre_cache_size": pre_cache_size,
        "db_status": db_status,
        "db_size": db_size,
    }


# ---------------------------------------------------------------------------
# Embedded WSGI runner (shared with bot polling mode)
# ---------------------------------------------------------------------------

def run_flask(port: int = 8000):
    """Run Flask in a daemon thread. Returns after the server is listening."""
    ready = threading.Event()

    def _serve():
        try:
            ready.set()
            from waitress import serve
            serve(app, host="0.0.0.0", port=port, _quiet=True)
        except ImportError:
            ready.set()
            app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

    t = threading.Thread(target=_serve, daemon=True, name="flask-admin")
    t.start()
    ready.wait(timeout=5)
    logger.info(f"Flask admin dashboard on port {port}")
    return t
