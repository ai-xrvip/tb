
"""
DB Sync: GitHub-based database persistence.
On startup: download latest bot.db from GitHub Releases.
Every 30 min: upload bot.db to GitHub Releases as an asset.
No Railway Volume needed.
"""
import os
import json
import urllib.request
import urllib.error
from pathlib import Path
from utils.logger import logger

GITHUB_API = "https://api.github.com"
REPO = "ai-xrvip/tb"
RELEASE_TAG = "db-backup"
ASSET_NAME = "bot.db"


def _get_token():
    token = os.getenv("GITHUB_TOKEN", "")
    if token:
        return token
    try:
        import subprocess
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, cwd=Path(__file__).parent
        )
        url = result.stdout.strip()
        if "oauth2:" in url and "@github.com" in url:
            return url.split("oauth2:")[1].split("@")[0]
    except Exception:
        pass
    return os.getenv("GITHUB_TOKEN", "")


def _api_request(method, endpoint, data=None, accept=None):
    token = _get_token()
    if not token:
        logger.error("DB Sync: No GitHub token available")
        return None
    url = GITHUB_API + endpoint
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": accept or "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = json.dumps(data).encode() if data else None
    if body:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        logger.error("DB Sync API error: " + str(e.code) + " " + str(e.reason))
        return None
    except Exception as e:
        logger.error("DB Sync error: " + str(e))
        return None


def _get_or_create_release():
    release = _api_request("GET", "/repos/" + REPO + "/releases/tags/" + RELEASE_TAG)
    if release:
        return release
    data = {
        "tag_name": RELEASE_TAG,
        "name": "Database Backup",
        "body": "Auto-generated database backup. Do not delete.",
        "draft": False,
        "prerelease": True,
    }
    return _api_request("POST", "/repos/" + REPO + "/releases", data=data)


def _delete_old_assets(release_id):
    assets = _api_request("GET", "/repos/" + REPO + "/releases/" + str(release_id) + "/assets")
    if not assets:
        return
    for asset in assets:
        _api_request("DELETE", "/repos/" + REPO + "/releases/assets/" + str(asset["id"]))


def upload_db(db_path):
    """Upload database to GitHub release."""
    if not os.path.exists(db_path):
        logger.warning("DB Sync: " + db_path + " not found, skipping upload")
        return False
    token = _get_token()
    if not token:
        return False
    try:
        release = _get_or_create_release()
        if not release:
            logger.error("DB Sync: Cannot get/create release")
            return False
        release_id = release["id"]
        _delete_old_assets(release_id)

        with open(db_path, "rb") as f:
            db_data = f.read()

        upload_url = (
            "https://uploads.github.com/repos/" + REPO +
            "/releases/" + str(release_id) +
            "/assets?name=" + ASSET_NAME
        )

        boundary = "----DbSyncBoundary"
        body_lines = [
            "--" + boundary,
            'Content-Disposition: form-data; name="file"; filename="' + ASSET_NAME + '"',
            "Content-Type: application/octet-stream",
            "",
        ]
        body = ("\r\n".join(body_lines)).encode() + b"\r\n" + db_data + b"\r\n--" + boundary.encode() + b"--\r\n"

        req = urllib.request.Request(
            upload_url,
            data=body,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/vnd.github+json",
                "Content-Type": "multipart/form-data; boundary=" + boundary,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            json.loads(resp.read())
            logger.info("DB Sync: Uploaded " + str(len(db_data)) + " bytes to GitHub")
            return True
    except Exception as e:
        logger.error("DB Sync upload failed: " + str(e))
        return False


def download_db(save_path):
    """Download database from GitHub release."""
    token = _get_token()
    if not token:
        return False
    try:
        release = _api_request("GET", "/repos/" + REPO + "/releases/tags/" + RELEASE_TAG)
        if not release:
            logger.info("DB Sync: No backup release found (first run?)")
            return False
        assets = release.get("assets", [])
        if not assets:
            logger.info("DB Sync: Release has no assets yet")
            return False
        asset = assets[0]
        download_url = asset["url"]
        req = urllib.request.Request(
            download_url,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/octet-stream",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
            save_dir = os.path.dirname(save_path) or "."
            os.makedirs(save_dir, exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(data)
            logger.info("DB Sync: Downloaded " + str(len(data)) + " bytes from GitHub")
            return True
    except Exception as e:
        logger.error("DB Sync download failed: " + str(e))
        return False


async def sync_loop(db_path, interval_sec=1800):
    """Background task: periodically upload DB to GitHub."""
    import asyncio
    while True:
        await asyncio.sleep(interval_sec)
        try:
            upload_db(db_path)
        except Exception as e:
            logger.error("DB Sync loop error: " + str(e))
