#!/usr/bin/env python3
"""
AlgoDesk MarketX - One-Click Automated Deployment Script
=========================================================
Pulls the latest code changes and deploys them to the production server.

Usage:
    python3 deploy.py                  # Deploy latest commits to production VPS
    python3 deploy.py --commit "msg"   # Stage, commit, push, and deploy
    python3 deploy.py --help           # Show all options

When run locally:
    1. Optionally commits & pushes local changes to GitHub (origin/main).
    2. Connects to the VPS (72.61.255.43) via SSH.
    3. Runs `git pull origin main` on the server.
    4. Restarts PM2 (`pm2 restart stock-analyser`).
    5. Performs an automated health check to confirm server is online.

When run on the VPS directly:
    1. Detects local server environment.
    2. Runs `git pull origin main`.
    3. Restarts PM2 and verifies health status.
"""

import os
import sys
import subprocess
import time
import argparse
from pathlib import Path

# ---------------------------------------------------------------------------
# Virtual Environment Bootstrap (Auto-switch to .venv if running system python)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent

if sys.prefix == sys.base_prefix:
    for venv_candidate in [".venv", "venv", "stock_venv"]:
        venv_python = PROJECT_ROOT / venv_candidate / "bin" / "python"
        if venv_python.is_file() and os.access(venv_python, os.X_OK):
            os.execv(str(venv_python), [str(venv_python)] + sys.argv)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Default VPS Configuration
DEFAULT_HOST = os.environ.get("VPS_HOST", "72.61.255.43")
DEFAULT_USER = os.environ.get("VPS_USER", "stock")
DEFAULT_PASS = os.environ.get("VPS_PASS", "stock")
DEFAULT_PORT = int(os.environ.get("VPS_PORT", "22"))
DEFAULT_REMOTE_DIR = os.environ.get("VPS_DIR", "/home/stock/stock-analyser")
DEFAULT_APP_NAME = os.environ.get("PM2_APP", "stock-analyser")
HEALTH_CHECK_URL = "http://127.0.0.1:8500/api/automation/status"

BANNER = r"""
========================================================================
   ___   __             ___            __   ___             __            
  / _ | / /__ ____  ___/ _ \___ ___   / /__/ _ \___ ___  / /__  __ _____ 
 / __ |/ / _ `/ _ \/ _  / // / -_|_-< /  '_/ // / -_) _ \/ / _ \/ // / -_)
/_/ |_/_/\_, /\___/\_,_/____/\__/___//_/\_\/____/\__/ .__/_/\___/\_, /\__/ 
        /___/        Auto-Deploy & Live Sync Engine /_/         /___/      
========================================================================
"""

def print_step(icon: str, text: str):
    print(f"\n{icon} \033[1;36m{text}\033[0m")

def print_success(text: str):
    print(f"✅ \033[1;32m{text}\033[0m")

def print_error(text: str):
    print(f"❌ \033[1;31m{text}\033[0m", file=sys.stderr)

def run_local(cmd: str, check: bool = True) -> str:
    res = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if check and res.returncode != 0:
        print_error(f"Command failed: {cmd}\n{res.stderr.strip()}")
        sys.exit(res.returncode)
    return res.stdout.strip()


def deploy_local_mode(args):
    """Executes deployment steps when run directly on the VPS."""
    print_step("🔄", f"Deploying directly on local server ({args.remote_dir})...")
    
    # 1. Git pull
    print_step("📥", "Pulling latest changes from origin/main...")
    pull_out = run_local(f"cd {args.remote_dir} && git pull origin main", check=True)
    print(pull_out)

    # 2. Restart PM2
    if not args.no_restart:
        print_step("🚀", f"Restarting PM2 process '{args.app_name}'...")
        pm2_out = run_local(f"pm2 restart {args.app_name}", check=True)
        print(pm2_out)
        time.sleep(3)

    # 3. Health check
    print_step("🩺", "Running health verification...")
    health_out = run_local(f"curl -s {HEALTH_CHECK_URL}", check=False)
    if "today_date" in health_out or "status" in health_out:
        print_success("Service is online and responding healthy!")
    else:
        print("Notice: Health check output: " + health_out[:200])

    print_success("Local deployment complete!")


def deploy_remote_mode(args):
    """Deploys to VPS over SSH using Paramiko."""
    # Step 1: Git commit & push if requested or if unpushed commits exist
    if args.commit:
        print_step("📦", f"Staging and committing changes with message: '{args.commit}'...")
        run_local("git add -A", check=True)
        run_local(f'git commit -m "{args.commit}"', check=False)

    if args.push:
        print_step("📤", "Pushing local commits to GitHub origin/main...")
        push_res = run_local("git push origin main", check=False)
        print(push_res or "Already pushed or up to date.")

    # Step 2: Connect to VPS
    print_step("🔌", f"Connecting to {args.user}@{args.host}:{args.port}...")
    try:
        import paramiko
    except ImportError:
        print_error("Paramiko is not installed. Installing paramiko...")
        run_local("pip install paramiko", check=True)
        import paramiko

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(
            hostname=args.host,
            port=args.port,
            username=args.user,
            password=args.password,
            timeout=15
        )
        print_success(f"Connected to {args.host} successfully.")
    except Exception as e:
        print_error(f"Failed to connect to VPS: {e}")
        sys.exit(1)

    # Step 3: Run git pull on remote VPS
    print_step("📥", f"Executing 'git pull origin main' on remote server ({args.remote_dir})...")
    pull_cmd = f"cd {args.remote_dir} && git pull origin main"
    stdin, stdout, stderr = ssh.exec_command(pull_cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    print(out)
    if err and "error" in err.lower():
        print_error(f"Notice from git: {err}")

    # Step 4: Restart PM2
    if not args.no_restart:
        print_step("🚀", f"Restarting PM2 application '{args.app_name}'...")
        restart_cmd = f"cd {args.remote_dir} && pm2 restart {args.app_name}"
        stdin, stdout, stderr = ssh.exec_command(restart_cmd)
        print(stdout.read().decode().strip())
        time.sleep(3)

    # Step 5: Verify Health
    print_step("🩺", "Verifying service health on VPS...")
    check_cmd = f"curl -s http://127.0.0.1:8500/api/automation/capital/verify"
    stdin, stdout, stderr = ssh.exec_command(check_cmd)
    res_text = stdout.read().decode().strip()

    if "success" in res_text or "capital_summary" in res_text:
        print_success("Service is verified ONLINE and capital gate is active!")
        print(f"Server response: {res_text[:160]}...")
    else:
        print(f"Health response: {res_text}")

    ssh.close()
    print("\n" + "=" * 72)
    print_success(f"🎉 Deployment to {args.host} successfully completed!")
    print(f"🌐 Live Dashboard: http://{args.host}:8500")
    print("=" * 72 + "\n")


def main():
    print(BANNER)

    parser = argparse.ArgumentParser(description="AlgoDesk MarketX Automated Deployer")
    parser.add_argument("--commit", "-m", type=str, default=None, help="Commit message to stage and commit locally before deploy")
    parser.add_argument("--no-push", dest="push", action="store_false", default=True, help="Skip pushing to GitHub origin")
    parser.add_argument("--no-restart", action="store_true", help="Skip restarting PM2 after pull")
    parser.add_argument("--host", type=str, default=DEFAULT_HOST, help="VPS host address (default: 72.61.255.43)")
    parser.add_argument("--user", type=str, default=DEFAULT_USER, help="SSH username (default: stock)")
    parser.add_argument("--password", type=str, default=DEFAULT_PASS, help="SSH password")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="SSH port (default: 22)")
    parser.add_argument("--remote-dir", type=str, default=DEFAULT_REMOTE_DIR, help="Remote project directory")
    parser.add_argument("--app-name", type=str, default=DEFAULT_APP_NAME, help="PM2 application name")
    
    args = parser.parse_args()

    # Check if we are running directly on the VPS
    hostname = subprocess.run("hostname", shell=True, text=True, capture_output=True).stdout.strip()
    is_on_vps = (Path(args.remote_dir).is_dir() and (hostname != "DESKTOP" and os.path.exists("/home/stock")))

    if is_on_vps:
        deploy_local_mode(args)
    else:
        deploy_remote_mode(args)


if __name__ == "__main__":
    main()
