"""
Web Admin Panel — Gradio-based dashboard for bot management.
"""
import gradio as gr
from database import db
from config import config
from roles import ROLES
from utils.logger import logger
from datetime import datetime, timezone

CSS = """
.gradio-container { max-width: 1200px !important; }
"""


def get_dashboard_stats():
    """Return dashboard statistics"""
    users = db.get_all_users()
    total = len(users)
    total_msgs = sum(u.get("total_messages", 0) for u in users)
    vip_count = sum(1 for u in users if db.is_vip(u.get("user_id", 0)))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_active = sum(
        1 for u in users
        if db.get_last_message_time(u.get("user_id", 0))
        and (datetime.now().timestamp() - db.get_last_message_time(u.get("user_id", 0))) < 86400
    )

    codes = db.get_all_codes()
    unused_codes = sum(1 for c in codes if not c.get("is_used"))
    active_bots = list(config.get_active_bots().keys())

    result = "### Dashboard\n\n"
    result += "| Metric | Value |\n|--------|-------|\n"
    result += "| Total Users | " + str(total) + " |\n"
    result += "| Active Today | " + str(today_active) + " |\n"
    result += "| Total Messages | " + str(total_msgs) + " |\n"
    result += "| VIP Users | " + str(vip_count) + " |\n"
    result += "| Unused Codes | " + str(unused_codes) + " |\n"
    result += "| Active Bots | " + str(len(active_bots)) + " (" + ", ".join(active_bots) + ") |"
    return result


def search_user(user_query):
    """Search user by ID or get list of recent users"""
    try:
        uid = int(user_query.strip())
        u = db.get_user(uid)
        if not u:
            return "User " + str(uid) + " not found"
        vip = db.is_vip(uid)
        history = db.get_chat_history(uid)
        unlocks = db.get_unlock_tier(uid, u.get("current_role", "xiaolu"))
        result = "### User " + str(uid) + "\n\n"
        result += "| Field | Value |\n|--------|-------|\n"
        result += "| Role | " + str(u.get("current_role", "N/A")) + " |\n"
        result += "| Messages | " + str(u.get("total_messages", 0)) + " |\n"
        result += "| Free Left | " + str(u.get("free_count", 0)) + " |\n"
        result += "| VIP | " + str(vip) + " |\n"
        result += "| Unlock Tier | " + str(unlocks) + " |\n"
        result += "| History Msgs | " + str(len(history) if history else 0) + " |\n"
        result += "| Expire | " + str(u.get("vip_expire", "N/A")) + " |"
        return result
    except ValueError:
        users = db.get_all_users()
        recent = sorted(
            users,
            key=lambda u: db.get_last_message_time(u.get("user_id", 0)) or 0,
            reverse=True
        )[:20]
        lines = ["### Recent Users\n\n| ID | Role | Msgs | Last Active |"]
        lines.append("|-----|------|------|-------------|")
        for u in recent:
            uid = u.get("user_id", 0)
            last = db.get_last_message_time(uid)
            last_str = datetime.fromtimestamp(last).strftime("%m-%d %H:%M") if last else "N/A"
            lines.append("| " + str(uid) + " | " + str(u.get("current_role", "?")) + " | " + str(u.get("total_messages", 0)) + " | " + last_str + " |")
        return "\n".join(lines)


def broadcast_preview(message, role_filter):
    """Preview broadcast"""
    if not message.strip():
        return "Please enter a message"
    users = db.get_all_users()
    if role_filter and role_filter != "all":
        users = [u for u in users if u.get("current_role") == role_filter]
    return "Broadcast preview:\n\nTarget: " + str(len(users)) + " users\nMessage: " + message[:200] + "...\n\nUse /broadcast in Telegram for actual delivery."


def set_user_vip(user_id_str, days_str):
    """Set VIP for user"""
    try:
        uid = int(user_id_str.strip())
        days = int(days_str.strip())
        db.create_user(uid)
        db.set_vip(uid, days)
        return "OK: user " + str(uid) + " VIP for " + str(days) + " days"
    except ValueError:
        return "Error: Invalid user ID or days"


def get_order_list(order_type):
    """Get orders list"""
    if order_type == "yuanwei":
        orders = db.get_all_yuanwei_orders()
    elif order_type == "keepsake":
        orders = db.get_all_keepsake_orders()
    else:
        orders = []
    if not orders:
        return "No orders found"
    lines = ["| Order ID | User | Role | Item | Amount | Status |"]
    lines.append("|----------|------|------|------|--------|--------|")
    for o in orders[:30]:
        lines.append(
            "| " + str(o.get("order_id", "?"))[:12] + " | " + str(o.get("user_id", "?")) + " | "
            + str(o.get("role_id", "?")) + " | " + str(o.get("item_name", "?")) + " | "
            + str(o.get("amount", 0)) + " | " + str(o.get("status", "?")) + " |"
        )
    return "\n".join(lines)


# Build Gradio UI
with gr.Blocks(css=CSS, title="AI GF Bot Admin") as demo:
    gr.Markdown("# AI Girlfriend Bot — Admin Panel")

    with gr.Tabs():
        with gr.TabItem("Dashboard"):
            refresh_btn = gr.Button("Refresh")
            dashboard_out = gr.Markdown()
            refresh_btn.click(fn=get_dashboard_stats, outputs=dashboard_out)

        with gr.TabItem("Users"):
            user_input = gr.Textbox(label="User ID (or empty for list)")
            user_search_btn = gr.Button("Search")
            user_out = gr.Markdown()
            user_search_btn.click(fn=search_user, inputs=user_input, outputs=user_out)

            gr.Markdown("---\n### Set VIP")
            with gr.Row():
                vip_user = gr.Textbox(label="User ID")
                vip_days = gr.Textbox(label="Days", value="30")
            vip_btn = gr.Button("Set VIP")
            vip_out = gr.Markdown()
            vip_btn.click(fn=set_user_vip, inputs=[vip_user, vip_days], outputs=vip_out)

        with gr.TabItem("Broadcast"):
            broadcast_text = gr.Textbox(label="Message", lines=3)
            role_select = gr.Dropdown(
                choices=["all"] + list(ROLES.keys()),
                label="Role Filter",
                value="all"
            )
            broadcast_btn = gr.Button("Preview")
            broadcast_out = gr.Markdown()
            broadcast_btn.click(fn=broadcast_preview, inputs=[broadcast_text, role_select], outputs=broadcast_out)

        with gr.TabItem("Orders"):
            order_type = gr.Dropdown(
                choices=["yuanwei", "keepsake"],
                label="Order Type",
                value="yuanwei"
            )
            order_btn = gr.Button("View Orders")
            order_out = gr.Markdown()
            order_btn.click(fn=get_order_list, inputs=order_type, outputs=order_out)


def start_admin_panel(port: int = 7860):
    """Start the admin panel with password auth."""
    # Use environment variable for admin password, default to a random token
    admin_user = os.getenv("ADMIN_USER", "admin")
    admin_pass = os.getenv("ADMIN_PASSWORD", "")
    if not admin_pass:
        import secrets
        admin_pass = secrets.token_urlsafe(16)
        logger.warning(f"ADMIN_PASSWORD not set, using random: {admin_pass}")
        logger.warning("Set ADMIN_PASSWORD env var for a fixed password.")

    logger.info("Admin panel starting on http://0.0.0.0:" + str(port))
    demo.queue(default_concurrency_limit=5).launch(
        server_name="0.0.0.0",
        server_port=port,
        share=False,
        show_error=True,
        auth=(admin_user, admin_pass),
    )


if __name__ == "__main__":
    start_admin_panel()
