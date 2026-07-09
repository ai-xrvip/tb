"""
Railway One-Click Deploy for tb-bot
====================================
Run:  python deploy_railway.py

What it does:
  1. Query Railway project/services/environments
  2. Set BOT_TOKEN + ADMIN_IDS env vars
  3. Create persistent volume at /app/data
  4. Trigger deployment
  5. Wait for domain → set WEBHOOK_URL → re-deploy

No pip install needed — uses only urllib (stdlib).
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

# ===== CONFIG =====
RAILWAY_TOKEN = "d9599893-dcb4-4a3d-af19-c0e53ca89804"
RAILWAY_API = "https://backboard.railway.com/graphql/v2"
PROJECT_ID = "d9e62341-f0a7-4313-a456-5d2e19487577"

# ⚠️ FILL THESE IN ⚠️
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
ADMIN_IDS = "YOUR_TELEGRAM_USER_ID"

HEADERS = {
    "Authorization": f"Bearer {RAILWAY_TOKEN}",
    "Content-Type": "application/json",
}


def graphql(query, variables=None):
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    data = json.dumps(payload).encode()
    req = urllib.request.Request(RAILWAY_API, data=data, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = json.loads(e.read())
    if "errors" in body:
        print(f"  [ERR] {json.dumps(body['errors'], indent=2)}")
        return None
    return body.get("data")


def check_project():
    """Step 1: Get project info, services, environments."""
    print("\n=== Step 1: Fetch Project Info ===")
    q = """
    query($id: String!) {
      project(id: $id) {
        id name
        services { edges { node { id name serviceInstances { edges { node { id environmentId latestDeployment { id status domain staticUrl meta { commitHash } } } } } } } }
        environments { edges { node { id name } } }
      }
    }
    """
    data = graphql(q, {"id": PROJECT_ID})
    if not data:
        print("[FAIL] Cannot fetch project. Check token.")
        sys.exit(1)
    p = data["project"]
    print(f"  Project: {p['name']} ({p['id']})")
    svcs = [e["node"] for e in p["services"]["edges"]]
    if not svcs:
        print("[FAIL] No services. Connect GitHub repo in Railway dashboard first.")
        sys.exit(1)
    svc = svcs[0]
    svc_id = svc["id"]
    svc_name = svc["name"]
    print(f"  Service: {svc_name} ({svc_id})")
    insts = [e["node"] for e in svc["serviceInstances"]["edges"]]
    env_id = insts[0]["environmentId"] if insts else None
    last_deploy = insts[0].get("latestDeployment") if insts else None
    envs = [e["node"] for e in p["environments"]["edges"]]
    env_name = next((e["name"] for e in envs if e["id"] == env_id), "unknown")
    print(f"  Environment: {env_name} ({env_id})")
    if last_deploy:
        print(f"  Last Deploy: {last_deploy.get('status')} | {last_deploy.get('domain', 'no domain')}")
    return svc_id, env_id


def set_vars(env_id):
    """Step 2: Set environment variables."""
    print("\n=== Step 2: Set Environment Variables ===")
    if BOT_TOKEN.startswith("YOUR_"):
        print("[FATAL] BOT_TOKEN not set! Edit this script.")
        sys.exit(1)
    if ADMIN_IDS.startswith("YOUR_"):
        print("[FATAL] ADMIN_IDS not set! Edit this script.")
        sys.exit(1)

    q = """
    mutation($input: VariableCollectionUpsertInput!) {
      variableCollectionUpsert(input: $input)
    }
    """
    variables = {
        "BOT_TOKEN": BOT_TOKEN,
        "ADMIN_IDS": ADMIN_IDS,
        "DB_PATH": "/app/data/bot.db",
    }
    inp = {
        "projectId": PROJECT_ID,
        "environmentId": env_id,
        "variables": variables,
    }
    data = graphql(q, {"input": inp})
    if data is not None:
        print(f"  ✅ Vars set: BOT_TOKEN, ADMIN_IDS, DB_PATH")
    else:
        print("[WARN] Vars may have failed.")


def ensure_volume(env_id, service_id):
    """Step 3: Check/create persistent volume at /app/data."""
    print("\n=== Step 3: Ensure Persistent Volume ===")
    q = """
    query($projectId: String!) {
      volumes(projectId: $projectId) {
        edges { node { id mountPath service { id } } }
      }
    }
    """
    data = graphql(q, {"projectId": PROJECT_ID})
    vols = [e["node"] for e in data["volumes"]["edges"]] if data else []
    for v in vols:
        if v["mountPath"] == "/app/data" and v["service"]["id"] == service_id:
            print(f"  ✅ Volume already exists at /app/data (id={v['id']})")
            return

    # Create volume
    q = """
    mutation($input: VolumeCreateInput!) {
      volumeCreate(input: $input) { id mountPath sizeMB }
    }
    """
    inp = {
        "projectId": PROJECT_ID,
        "serviceId": service_id,
        "environmentId": env_id,
        "mountPath": "/app/data",
    }
    data = graphql(q, {"input": inp})
    if data:
        vol = data["volumeCreate"]
        print(f"  ✅ Volume created: {vol['mountPath']} (id={vol['id']})")
    else:
        print("[WARN] Volume creation may have failed.")


def deploy(env_id, service_id):
    """Step 4: Trigger deployment and wait."""
    print("\n=== Step 4: Trigger Deployment ===")
    q = """
    mutation($input: DeploymentTriggerInput!) {
      deploymentTrigger(input: $input) { id status }
    }
    """
    inp = {
        "projectId": PROJECT_ID,
        "serviceId": service_id,
        "environmentId": env_id,
    }
    data = graphql(q, {"input": inp})
    if not data:
        print("[FAIL] Cannot trigger deployment.")
        sys.exit(1)
    dep = data["deploymentTrigger"]
    dep_id = dep["id"]
    print(f"  Deployment: {dep_id} (status: {dep['status']})")

    # Wait
    q2 = """
    query($id: String!) {
      deployment(id: $id) {
        id status meta domain
        service { domains { serviceDomains { domain } } }
      }
    }
    """
    print("  Waiting for deployment...")
    for i in range(60):
        time.sleep(10)
        d = graphql(q2, {"id": dep_id})
        if not d:
            continue
        dd = d["deployment"]
        s = dd.get("status", "?")
        mins = (i + 1) * 10 // 60
        secs = (i + 1) * 10 % 60
        print(f"  [{mins}m{secs}s] {s}")
        if s in ("SUCCESS",):
            print("\n  ✅ Deployment SUCCESS!")
            domains = dd.get("service", {}).get("domains", {}).get("serviceDomains", [])
            if domains:
                domain = domains[0]["domain"]
                print(f"  🌐 Domain: https://{domain}")
            else:
                domain = dd.get("domain")
                if domain:
                    print(f"  🌐 Domain: https://{domain}")
            return domain
        elif s in ("FAILED", "CRASHED", "REMOVED"):
            print(f"\n[FAIL] Deployment {s}. Check Railway logs.")
            sys.exit(1)
    print("\n[WARN] Timed out. Check https://railway.app/dashboard")
    return None


def set_webhook(env_id, domain):
    """Step 5: Set WEBHOOK_URL and re-deploy."""
    print("\n=== Step 5: Set WEBHOOK_URL ===")
    webhook_url = f"https://{domain}"
    q = """
    mutation($input: VariableCollectionUpsertInput!) {
      variableCollectionUpsert(input: $input)
    }
    """
    inp = {
        "projectId": PROJECT_ID,
        "environmentId": env_id,
        "variables": {"WEBHOOK_URL": webhook_url},
    }
    data = graphql(q, {"input": inp})
    if data is not None:
        print(f"  ✅ WEBHOOK_URL = {webhook_url}")
        print("  (Railway auto-redeploys on variable change)")
    else:
        print("[WARN] Could not set WEBHOOK_URL.")


def main():
    print("=" * 50)
    print("  Railway Deploy — tb-bot")
    print("=" * 50)

    service_id, env_id = check_project()
    set_vars(env_id)
    ensure_volume(env_id, service_id)
    domain = deploy(env_id, service_id)
    if domain:
        set_webhook(env_id, domain)

    print("\n" + "=" * 50)
    print("  DONE! Check: https://railway.app/project/" + PROJECT_ID)
    print("  Send /start to your bot on Telegram to verify.")
    print("=" * 50)


if __name__ == "__main__":
    main()
