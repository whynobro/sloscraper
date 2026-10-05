"""Publish the rendered site to the gh-pages branch via ghp-import (no force push)."""
from __future__ import annotations

import logging
import subprocess
import sys
from datetime import datetime

log = logging.getLogger(__name__)


def publish(site_dir: str = "site", dry_run: bool = False) -> bool:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    cmd = [sys.executable, "-m", "ghp_import", "-n", "-m", f"Update events {stamp}", "-p", str(site_dir)]
    if dry_run:
        print("DRY RUN:", subprocess.list2cmdline(cmd))
        return True
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception as e:
        log.error("publish failed to run: %s", e)
        return False
    if res.returncode != 0:
        log.error("publish failed (exit %s): %s", res.returncode, (res.stderr or res.stdout).strip())
        return False
    log.info("published %s to gh-pages", site_dir)
    return True
