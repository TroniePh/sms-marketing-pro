"""
Quản lý cập nhật tự động — kiểm tra GitHub Releases và tải bản mới.

Quy ước đặt tag trên GitHub:
  - Tag phải có dạng: v1.0.0, v1.2.3, v2.0.0-beta ...
  - Phần so sánh chỉ lấy chuỗi số (bỏ tiền tố 'v').
  - Release phải đính kèm (attach) file .exe trong mục Assets.
"""

import os
import re
import subprocess
import tempfile
from typing import Optional, Tuple

import requests

GITHUB_OWNER = "TroniePh"
GITHUB_REPO = "sms-marketing-pro"

RELEASES_API = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)

REQUEST_TIMEOUT = 10


def _normalize_version(tag: str) -> str:
    """Bỏ tiền tố 'v' hoặc 'V' và khoảng trắng: 'v1.2.3' -> '1.2.3'."""
    return re.sub(r"^[vV]?\s*", "", tag.strip())


def _version_tuple(version_str: str) -> Tuple[int, ...]:
    """'1.2.3' -> (1, 2, 3) để so sánh số học."""
    parts = _normalize_version(version_str).split(".")
    result = []
    for p in parts:
        digits = re.match(r"(\d+)", p)
        result.append(int(digits.group(1)) if digits else 0)
    return tuple(result)


def check_for_update(
    current_version: str,
) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """
    Kiểm tra bản mới trên GitHub Releases.

    Returns:
        (has_update, latest_version, download_url, release_notes)
        Nếu lỗi mạng / API -> (False, None, None, None), không crash.
    """
    try:
        resp = requests.get(
            RELEASES_API,
            headers={"Accept": "application/vnd.github+json"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return False, None, None, None

        data = resp.json()
        tag = str(data.get("tag_name") or "")
        if not tag:
            return False, None, None, None

        latest = _normalize_version(tag)
        current = _normalize_version(current_version)

        if _version_tuple(latest) <= _version_tuple(current):
            return False, latest, None, None

        download_url = _find_exe_asset(data.get("assets") or [])
        notes = str(data.get("body") or "")[:500]

        return True, latest, download_url, notes

    except Exception:
        return False, None, None, None


def _find_exe_asset(assets: list) -> Optional[str]:
    """Tìm file .exe đầu tiên trong danh sách assets của release."""
    for asset in assets:
        name = str(asset.get("name") or "").lower()
        if name.endswith(".exe"):
            return str(asset.get("browser_download_url") or "")
    return None


def download_and_run_update(download_url: str) -> Tuple[bool, str]:
    """
    Tải file Setup .exe về thư mục tạm rồi chạy nó.

    Returns:
        (success, message)
    """
    try:
        resp = requests.get(download_url, stream=True, timeout=120)
        resp.raise_for_status()

        tmp_dir = tempfile.gettempdir()
        filename = download_url.split("/")[-1] or "Setup_SMS_Marketing.exe"
        filepath = os.path.join(tmp_dir, filename)

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        subprocess.Popen(
            [filepath],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )

        return True, filepath

    except Exception as e:
        return False, str(e)
