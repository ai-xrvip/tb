"""display.py — Gallery detail display functions."""
from bot_utils import (
    now_ts, store_url, get_url, clean_title, parse_count_from_title,
    is_vip, get_download_sem, send_or_edit, parse_date_for_sort,
    EH_ENABLED, RESULTS_PER_PAGE, user_search_state, url_store,
)
from scraper import get_gallery_images, download_image, track_click, get_xchina_gallery
from scraper_eh import get_eh_gallery, get_eh_magnet
from pre_cache import track_pre_clicked
from config import config
import asyncio, html, logging, re, traceback, httpx
from io import BytesIO
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto,
)
logger = logging.getLogger(__name__)

# ========== Display ==========

async def _show_results_page(msg_or_query, user_id, is_update=False):
    state = user_search_state.get(user_id)
    if not state: return
    results = state["results"]
    page = state["page"]
    keyword = state["keyword"]
    total = len(results)
    full_pages = max(1, (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)
    is_vip_user = is_vip(user_id)
    max_accessible_pages = full_pages if is_vip_user else min(full_pages, 2)
    start = page * RESULTS_PER_PAGE
    end = min(start + RESULTS_PER_PAGE, total)
    page_results = results[start:end]
    if not is_vip_user and full_pages > 2:
        text = f"🔍 <b>{html.escape(keyword)}</b> 共 {total} 个结果（第{page+1}/{full_pages}页）\n\n👑 开通VIP可查看全部{total}条结果\n\n"
    else:
        text = f"🔍 <b>{html.escape(keyword)}</b> 共 {total} 个结果（第{page+1}/{full_pages}页）\n\n"
    buttons = []
    for i, r in enumerate(page_results):
        idx = start + i + 1
        raw_title = r["title"]
        author = r.get("author", "")
        publish_date = r.get("publish_date", "")
        if author and author not in raw_title:
            display_title = f"{author} - {clean_title(raw_title)}"
        else:
            display_title = clean_title(raw_title)
        text += f"{idx}. 📷 {html.escape(display_title)}\n"
        btn_label = display_title[:32] + ".." if len(display_title) > 35 else display_title[:35]
        url_key = await store_url(r["url"], author=author, publish_date=publish_date,
            title=display_title, source=r.get("source", ""))
        prefix = "e_" if r.get("source") == "ehentai" else ("x_" if r.get("source") == "xchina" else "d_")
        buttons.append([InlineKeyboardButton(f"📷 {idx}. {btn_label}", callback_data=prefix + url_key)])
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"p_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"📋 {page+1}/{full_pages}", callback_data="noop"))
    if page < max_accessible_pages - 1:
        nav_buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"p_{page+1}"))
    buttons.append(nav_buttons)
    if not is_vip_user and full_pages > 2:
        buttons.append([InlineKeyboardButton("👑 VIP查看全部搜索结果", callback_data="menu_vip")])
    buttons.append([
        InlineKeyboardButton("👑 开通VIP", callback_data="menu_vip"),
        InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home"),
    ])
    # Progressive indicator for updates
    if is_update:
        text += "\n📡 <i>正在获取更多来源...</i>"
    await send_or_edit(msg_or_query, text, reply_markup=InlineKeyboardMarkup(buttons))

async def _send_xchina_detail(update, url, author="", publish_date="", from_random=False):
    user_id = update.effective_user.id
    await track_pre_clicked(user_id)
    try:
        detail = await get_xchina_gallery(url)
    except Exception as e:
        logger.error(f"XC detail error: {traceback.format_exc()}")
        await update.effective_message.reply_text("❌ 获取图集失败，请稍后再试。")
        return
    title = detail.get("title", "Unknown")
    cover = detail.get("cover")
    cover_bytes = detail.get("cover_bytes")
    count = detail.get("count", 0)
    images = detail.get("images", [])
    final_author = author
    final_date = detail.get("publish_date", "") or publish_date
    clean_title_str = clean_title(title)
    clean_title_str = re.sub(r"\s*[-|]\s*XChina.*$", "", clean_title_str, flags=re.IGNORECASE)
    clean_title_str = re.sub(r"\s*\([^)]*免费[^)]*\)", "", clean_title_str)
    clean_title_str = clean_title_str.strip()
    display_title = f"{final_author} - {clean_title_str}" if final_author else clean_title_str
    text = f"🎀 {html.escape(display_title)}"
    if count: text += f"\n📸 {count}P"
    if final_date: text += f"\n🕐 {final_date}"
    # 只有在非随机推荐（从搜索结果点进来）时才显示原链接
    if not from_random:
        text += f"\n🔗 {html.escape(url)}"
    url_key = await store_url(url, title=display_title, source="xchina")
    buttons = []
    if images:
        buttons.append([InlineKeyboardButton("🖼️ 查看完整图集", callback_data="f_" + url_key)])
    if from_random:
        buttons.append([InlineKeyboardButton("🔄 换一个", callback_data="random_next")])
    if is_vip(user_id):
        buttons.append([InlineKeyboardButton("⭐ 收藏", callback_data="fav_add_" + url_key)])
    buttons.append([InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")])
    keyboard = InlineKeyboardMarkup(buttons)
    sent = False
    if cover_bytes:
        img_data, img_ct = cover_bytes
        try:
            img_data.seek(0)
            await update.effective_message.reply_photo(photo=img_data, caption=text, reply_markup=keyboard, parse_mode="HTML")
            sent = True
        except Exception:
            logger.error("XC cover send failed: " + traceback.format_exc())
    if not sent and cover:
        try:
            await update.effective_message.reply_photo(photo=cover, caption=text, reply_markup=keyboard, parse_mode="HTML")
            sent = True
        except Exception:
            logger.error("XC cover url send failed: " + traceback.format_exc())
    if not sent:
        await update.effective_message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")

async def _send_eh_detail(update, url, publish_date="", from_random=False):
    user_id = update.effective_user.id
    await track_pre_clicked(user_id)
    try:
        detail = await get_eh_gallery(url)
    except Exception:
        logger.error("EH detail error: " + traceback.format_exc())
        await update.effective_message.reply_text("❌ 获取EH图集失败")
        return
    title = detail.get("title", "Unknown")
    cover = detail.get("cover")
    images = detail.get("images", [])
    count = detail.get("count", 0)
    tags = detail.get("tags", [])
    clean_title_str = clean_title(title)
    text = f"📖 {html.escape(clean_title_str)}"
    if count: text += f"\n📸 {count}P"
    if publish_date: text += f"\n🕐 {publish_date}"
    if tags: text += "\n🏷 " + ", ".join(tags[:8])
    # 只有在非随机推荐（从搜索结果点进来）时才显示原链接
    if not from_random:
        text += f"\n🔗 {html.escape(url)}"
    url_key = await store_url(url, title=clean_title_str, source="ehentai")
    buttons = []
    if images:
        buttons.append([InlineKeyboardButton("🖼️ 查看图集预览", callback_data="f_" + url_key)])
    if from_random:
        buttons.append([InlineKeyboardButton("🔄 换一个", callback_data="random_next")])
    if is_vip(user_id):
        buttons.append([InlineKeyboardButton("🧲 获取磁力链", callback_data="m_" + url_key)])
        buttons.append([InlineKeyboardButton("⭐ 收藏", callback_data="fav_add_" + url_key)])
    buttons.append([InlineKeyboardButton("🏠 返回主菜单", callback_data="menu_home")])
    keyboard = InlineKeyboardMarkup(buttons)
    cover_bytes = None
    if cover:
        try:
            async with httpx.AsyncClient(timeout=20, verify=False, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://e-hentai.org/"}) as cl:
                cr = await cl.get(cover)
                if cr.status_code == 200 and len(cr.content) > 1000:
                    cover_bytes = cr.content
                else:
                    logger.warning(f"EH cover bad: status={cr.status_code} size={len(cr.content)}")
        except Exception as ex:
            logger.warning(f"EH cover download failed: {ex}")
    sent = False
    if cover_bytes:
        try:
            await update.effective_message.reply_photo(photo=cover_bytes, caption=text, reply_markup=keyboard, parse_mode="HTML")
            sent = True
        except Exception:
            logger.debug("EH cover send failed (maybe Telegram rejected the photo)")
    if not sent and cover:
        try:
            await update.effective_message.reply_photo(photo=cover, caption=text, reply_markup=keyboard, parse_mode="HTML")
            sent = True
        except Exception:
            logger.debug("EH cover send failed (maybe Telegram rejected the photo)")
    if not sent:
        await update.effective_message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")

async def _send_gallery_detail(update, url, gallery_data=None, from_random=False):
    user_id = update.effective_user.id
    await track_pre_clicked(user_id)
    logger.info("Fetching gallery: " + url[:80])
    if gallery_data is None:
        try:
            gallery_data = await get_gallery_images(url)
        except Exception:
            logger.error("Gallery fetch error: " + traceback.format_exc())
            await update.effective_message.reply_text("😔 获取图集详情失败，请稍后再试。")
            return
    title = gallery_data["title"]
    cover = gallery_data["cover"]
    cover_bytes = gallery_data.get("cover_bytes")
    publish_date = gallery_data.get("publish_date", "")
    all_images = gallery_data["images"]
    await track_click(url, title)
    original_count = parse_count_from_title(title)
    display_count = original_count if original_count > 0 else len(all_images)
    clean_title_str = clean_title(title)
    text = f"🎀 {html.escape(clean_title_str)}\n📸 {display_count}张"
    if publish_date: text += f"\n🕐 {publish_date}"
    # 只有在非随机推荐（从搜索结果点进来）时才显示原链接
    if not from_random:
        text += f"\n🔗 {html.escape(url)}"
    url_key = await store_url(url, title=clean_title_str, source="4khd")
    buttons = [[InlineKeyboardButton("🖼️ 查看完整图集", callback_data="f_" + url_key)]]
    if from_random:
        buttons.append([InlineKeyboardButton("🔄 换一个", callback_data="random_next")])
    if is_vip(user_id):
        buttons.append([InlineKeyboardButton("⭐ 收藏", callback_data="fav_add_" + url_key)])
    buttons.append([InlineKeyboardButton("🏠 主菜单", callback_data="menu_home")])
    keyboard = InlineKeyboardMarkup(buttons)
    sent = False
    if cover_bytes:
        img_data, img_ct = cover_bytes
        try:
            img_data.seek(0)
            await update.effective_message.reply_photo(photo=img_data, caption=text, reply_markup=keyboard, parse_mode="HTML")
            sent = True
        except Exception:
            logger.error("Cover send failed: " + traceback.format_exc())
    if not sent and cover:
        try:
            await update.effective_message.reply_photo(photo=cover, caption=text, reply_markup=keyboard, parse_mode="HTML")
            sent = True
        except Exception:
            logger.error("Cover url send failed: " + traceback.format_exc())
    if not sent:
        await update.effective_message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")

async def _send_gallery_full(update, url):
    user_id = update.effective_user.id
    is_ehentai = "e-hentai.org" in url
    is_xchina = "/photo/id-" in url
    if is_ehentai:
        try:
            max_imgs = 200 if is_vip(user_id) else config.MAX_IMAGES_PER_POST
            eh_data = await get_eh_gallery(url, max_images=max_imgs)
        except Exception:
            logger.error("EH full gallery error: " + traceback.format_exc())
            await update.effective_message.reply_text("❌ 加载EH图集失败")
            return
        all_images = eh_data["images"]
    elif is_xchina:
        gid = re.search(r"/id-([a-f0-9]+)", url)
        if gid:
            gallery_id = gid.group(1)
            # Fetch the gallery first to know the actual image count
            try:
                detail = await get_xchina_gallery(url)
                actual_count = detail.get("count", 0)
                actual_images = detail.get("images", [])
            except Exception:
                logger.warning("XC full gallery: failed to get detail, using default gen")
                actual_count = 0
                actual_images = []
            max_imgs = min(
                200 if is_vip(user_id) else config.MAX_IMAGES_PER_POST,
                actual_count if actual_count > 0 else (200 if is_vip(user_id) else config.MAX_IMAGES_PER_POST),
            )
            if actual_images:
                all_images = actual_images[:max_imgs]
            else:
                all_images = [f"https://img.xchina.io/photos/{gallery_id}/{i:05d}_600x0.webp" for i in range(1, max_imgs + 1)]
        else:
            await update.effective_message.reply_text("😔 加载失败，请稍后再试。")
            return
    else:
        try:
            max_imgs = 200 if is_vip(user_id) else config.MAX_IMAGES_PER_POST
            gallery_data = await get_gallery_images(url, max_pages=20, max_images=max_imgs)
        except Exception:
            logger.error("Full gallery error: " + traceback.format_exc())
            await update.effective_message.reply_text("😔 加载失败，请稍后再试。")
            return
        all_images = gallery_data["images"]
    total_pages = (len(all_images) + 9) // 10
    preview = all_images[:10]
    media = []
    downloaded = 0
    sem = get_download_sem()
    async def _dl_one(img_url):
        async with sem:
            return await download_image(img_url, referer=url)
    tasks = [_dl_one(u) for u in preview]
    results_list = await asyncio.gather(*tasks)
    for result in results_list:
        if result:
            img_data, ct = result
            img_data.seek(0)
            media.append(InputMediaPhoto(media=img_data))
            downloaded += 1
    if media:
        try:
            await update.effective_message.reply_media_group(media=media)
        except Exception:
            logger.error("Media group failed: " + traceback.format_exc())
    url_key = await store_url(url)
    buttons = []
    if is_vip(user_id):
        if total_pages > 1:
            buttons.append([InlineKeyboardButton("➡️ 下一页", callback_data=f"g_{url_key}_1")])
    else:
        buttons.append([InlineKeyboardButton("👑 VIP查看完整图集", callback_data="vip_upgrade")])
    buttons.append([InlineKeyboardButton("🏠 主菜单", callback_data="menu_home")])
    keyboard = InlineKeyboardMarkup(buttons)
    await update.effective_message.reply_text(f"📸 第1/{total_pages}页（{downloaded}张）", reply_markup=keyboard)

async def _send_gallery_page(update, url, page=0):
    user_id = update.effective_user.id
    if not is_vip(user_id): return
    is_ehentai = "e-hentai.org" in url
    is_xchina = "/photo/id-" in url
    if is_ehentai:
        try:
            max_imgs = 200 if is_vip(user_id) else config.MAX_IMAGES_PER_POST
            eh_data = await get_eh_gallery(url, max_images=max_imgs)
        except Exception:
            await update.effective_message.reply_text("❌ 加载EH图集失败")
            return
        all_images = eh_data["images"]
    elif is_xchina:
        gid = re.search(r"/id-([a-f0-9]+)", url)
        if gid:
            gallery_id = gid.group(1)
            # Fetch the gallery first to know the actual image count
            try:
                detail = await get_xchina_gallery(url)
                actual_count = detail.get("count", 0)
                actual_images = detail.get("images", [])
            except Exception:
                logger.warning("XC gallery page: failed to get detail, using default gen")
                actual_count = 0
                actual_images = []
            max_imgs = min(
                200 if is_vip(user_id) else config.MAX_IMAGES_PER_POST,
                actual_count if actual_count > 0 else (200 if is_vip(user_id) else config.MAX_IMAGES_PER_POST),
            )
            if actual_images:
                all_images = actual_images[:max_imgs]
            else:
                all_images = [f"https://img.xchina.io/photos/{gallery_id}/{i:05d}_600x0.webp" for i in range(1, max_imgs + 1)]
        else:
            await update.effective_message.reply_text("😔 加载失败，请稍后再试。")
            return
    else:
        try:
            max_imgs = 200 if is_vip(user_id) else config.MAX_IMAGES_PER_POST
            gallery_data = await get_gallery_images(url, max_pages=20, max_images=max_imgs)
        except Exception:
            await update.effective_message.reply_text("😔 加载失败，请稍后再试。")
            return
        all_images = gallery_data["images"]
    total_pages = (len(all_images) + 9) // 10
    start = page * 10
    end = start + 10
    page_images = all_images[start:end]
    if not page_images:
        await update.effective_message.reply_text("已经是最后一页了～")
        return
    media = []
    downloaded = 0
    sem = get_download_sem()
    async def _dl_one(img_url):
        async with sem:
            return await download_image(img_url, referer=url)
    tasks = [_dl_one(u) for u in page_images]
    results_list = await asyncio.gather(*tasks)
    for result in results_list:
        if result:
            img_data, ct = result
            img_data.seek(0)
            media.append(InputMediaPhoto(media=img_data))
            downloaded += 1
    if media:
        try:
            await update.effective_message.reply_media_group(media=media)
        except Exception:
            logger.error("Page media failed: " + traceback.format_exc())
    url_key = await store_url(url)
    buttons = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"g_{url_key}_{page-1}"))
    nav.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"g_{url_key}_{page+1}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton("🏠 主菜单", callback_data="menu_home")])
    keyboard = InlineKeyboardMarkup(buttons)
    await update.effective_message.reply_text(f"📸 第{page+1}/{total_pages}页（{downloaded}张）", reply_markup=keyboard)
