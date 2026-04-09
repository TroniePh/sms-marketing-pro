import time
from typing import Dict, List, Optional, Tuple

import requests


def _normalize_base_url(url: str) -> str:
    return url.rstrip("/")


def ping_gateway(
    gateway_url: str, username: str, password: str, timeout: int = 8
) -> Tuple[bool, str]:
    """Kiểm tra gateway có phản hồi và thông tin Basic Auth hợp lệ hay không."""
    if not gateway_url:
        return False, "Gateway URL chưa được cấu hình."

    base = _normalize_base_url(gateway_url)
    candidate_paths = ["", "/message"]
    last_error = "Không thể kết nối gateway."

    for path in candidate_paths:
        url = f"{base}{path}"
        try:
            res = requests.get(url, auth=(username, password), timeout=timeout)
            if 200 <= res.status_code < 300:
                return True, f"Kết nối thành công: {url}"
            if res.status_code in (401, 403):
                return False, "Sai Username/Password (Basic Auth)."
            last_error = f"{url} trả về HTTP {res.status_code}: {res.text[:200]}"
        except requests.RequestException as ex:
            last_error = f"Lỗi khi gọi {url}: {ex}"

    return False, last_error


def _extract_message_id(data: Optional[Dict]) -> Optional[str]:
    """Trích xuất message ID từ JSON response của POST /message."""
    if not data or not isinstance(data, dict):
        return None
    for key in ("id", "ID", "messageId", "message_id"):
        val = data.get(key)
        if val is not None:
            return str(val)
    return None


def _resolve_effective_state(data: Dict) -> Tuple[str, str]:
    """
    Xác định trạng thái tổng hợp từ response GET /message/{id}.
    Ưu tiên recipient-level state, fallback top-level state.
    """
    recipients: List[Dict] = data.get("recipients") or data.get("results") or []
    if recipients:
        states: List[str] = []
        errors: List[str] = []
        for r in recipients:
            s = str(r.get("state") or r.get("status") or "").lower()
            states.append(s)
            err = r.get("error") or r.get("errorMessage") or ""
            if err:
                errors.append(str(err))
        detail = "; ".join(errors) if errors else ", ".join(states)
        if all(s in ("delivered", "sent") for s in states):
            return "delivered", detail
        if any(s == "failed" for s in states):
            return "failed", detail
        return ", ".join(states), detail

    state = str(data.get("state") or data.get("status") or "").lower()
    return state, str(data.get("error") or data.get("errorMessage") or "")


def poll_message_status(
    gateway_url: str,
    username: str,
    password: str,
    message_id: str,
    max_wait: int = 20,
    poll_interval: int = 2,
    stop_event=None,
) -> Tuple[bool, str, Optional[Dict]]:
    """
    Poll GET /message/{id} hoặc /messages/{id} để xác nhận SIM đã thực sự gửi.
    stop_event: threading.Event tùy chọn, nếu set thì dừng poll sớm.
    """
    base = _normalize_base_url(gateway_url)
    candidate_paths = [f"/message/{message_id}", f"/messages/{message_id}"]

    elapsed = 0
    working_path: Optional[str] = None
    last_state = "unknown"
    last_detail = ""
    last_data: Optional[Dict] = None
    no_endpoint_attempts = 0

    while elapsed < max_wait:
        if stop_event is not None and stop_event.is_set():
            return True, "HTTP OK (polling bị dừng sớm)", last_data

        time.sleep(poll_interval)
        elapsed += poll_interval

        paths = [working_path] if working_path else candidate_paths
        found_valid = False

        for path in paths:
            url = f"{base}{path}"
            try:
                res = requests.get(url, auth=(username, password), timeout=8)
                if res.status_code == 404:
                    continue
                found_valid = True
                working_path = path
                if 200 <= res.status_code < 300:
                    try:
                        data = res.json()
                    except Exception:
                        continue
                    last_data = data
                    eff_state, detail = _resolve_effective_state(data)
                    last_state = eff_state
                    last_detail = detail

                    if eff_state in ("delivered", "sent"):
                        return True, f"Xác nhận thiết bị: {eff_state.upper()}", data
                    if eff_state == "failed":
                        return False, f"LỖI THIẾT BỊ (poll): {detail}", data
                    break
            except requests.RequestException:
                continue

        if not found_valid:
            no_endpoint_attempts += 1
            if no_endpoint_attempts >= 2:
                return True, "HTTP OK (API không hỗ trợ polling trạng thái)", None

    if last_state in ("pending", "processed", "queued", "unknown", ""):
        return False, (
            f"TIMEOUT ({max_wait}s): thiết bị chưa xác nhận (state={last_state})"
        ), last_data
    return False, (
        f"TIMEOUT ({max_wait}s): state={last_state}, chi tiết={last_detail}"
    ), last_data


def send_sms(
    gateway_url: str,
    username: str,
    password: str,
    phone: str,
    message: str,
    timeout: int = 15,
    verify_delivery: bool = True,
    poll_max_wait: int = 20,
    poll_interval: int = 2,
    stop_event=None,
) -> Tuple[bool, str, Optional[Dict]]:
    """
    Gửi SMS qua android-sms-gateway (POST /message).
    verify_delivery=True sẽ poll GET /message/{id} để xác nhận SIM đã gửi thực sự.
    stop_event: threading.Event tùy chọn để dừng poll sớm khi user nhấn Dừng.
    """
    base = _normalize_base_url(gateway_url)
    url = f"{base}/message"
    payload = {"message": message, "phoneNumbers": [phone]}

    try:
        res = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            auth=(username, password),
            timeout=timeout,
        )
        if 200 <= res.status_code < 300:
            try:
                data = res.json()
            except Exception:
                data = {"raw": res.text[:500]}

            if not verify_delivery:
                return True, "HTTP OK (không verify)", data

            msg_id = _extract_message_id(data)
            if not msg_id:
                return True, "HTTP OK (không có ID để verify)", data

            poll_ok, poll_msg, poll_data = poll_message_status(
                gateway_url, username, password, msg_id,
                max_wait=poll_max_wait, poll_interval=poll_interval,
                stop_event=stop_event,
            )
            merged = {**(data or {}), "poll": poll_data}
            return poll_ok, poll_msg, merged

        if res.status_code in (401, 403):
            return False, "Sai Username/Password (Basic Auth).", None
        return False, f"HTTP {res.status_code}: {res.text[:300]}", None
    except requests.RequestException as ex:
        return False, f"Lỗi request: {ex}", None
