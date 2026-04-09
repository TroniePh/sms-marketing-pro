import concurrent.futures
import queue
import random
import threading
import time
from io import BytesIO
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from database import (
    delete_gateway,
    ensure_single_default_gateway,
    get_failed_logs,
    get_gateways,
    get_logs,
    get_success_phones_today,
    get_setting,
    get_setting_int,
    init_db,
    save_log,
    set_setting,
    update_log_after_retry,
    upsert_gateway,
)
from gateway import ping_gateway, send_sms
from update_manager import check_for_update, download_and_run_update
from utils import (
    apply_variables,
    clean_phone_number,
    detect_columns,
    estimate_sms_parts,
    format_row_data,
    get_carrier,
    parse_spintax,
    remove_vietnamese_accents,
    render_message,
    simple_ai_rewrite_to_spintax,
    spintax_templates,
)


st.set_page_config(page_title="SMS Marketing Pro", page_icon="📩", layout="wide")

CURRENT_VERSION = "1.0.0"

init_db()
SELECT_COL = "[x] Chọn gửi"


def load_dataframe(uploaded_file) -> pd.DataFrame:
    filename = uploaded_file.name.lower()
    if filename.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    if filename.endswith(".xlsx"):
        return pd.read_excel(BytesIO(uploaded_file.getvalue()))
    raise ValueError("Chỉ hỗ trợ file .csv hoặc .xlsx")


def get_value(key: str, default: str = "") -> str:
    return get_setting(key, default) or default


def ensure_select_column(df: pd.DataFrame) -> pd.DataFrame:
    if SELECT_COL not in df.columns:
        df.insert(0, SELECT_COL, True)
    else:
        cols = [SELECT_COL] + [c for c in df.columns if c != SELECT_COL]
        df = df[cols]
    return df


def ensure_tracking_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in ["Trạng thái", "Gửi từ", "Phản hồi"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(object)
    return df


def init_state() -> None:
    defaults: Dict[str, Any] = {
        "df": None,
        "detected": {"phone": None, "name": None, "date": None},
        "preview_refresh_counter": 0,
        "last_loaded_file": None,
        "selected_gateway_id": None,
        "message_template_live": get_value(
            "message_template",
            "{Chao|Xin chao|Kinh chao} [Ten khach hang], {nhac ban|thong bao} lich hen vao ngay [Ngay hen]. Cam on!",
        ),
        "is_sending": False,
        "stop_requested": False,
        "current_sending_idx": 0,
        "gateway_statuses": {},
        "gateway_status_last_check": 0.0,
        "sending_queue": [],
        "sending_total": 0,
        "sending_success_count": 0,
        "sending_fail_count": 0,
        "sending_sent_today_set": [],
        "result_queue": None,
        "stop_event": None,
        "send_futures": [],
        "send_executor": None,
        "sending_processed_count": 0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _host_from_url(url: str) -> str:
    try:
        return urlparse(url).hostname or url
    except Exception:
        return url


def refresh_gateway_statuses(force: bool = False) -> Dict[int, bool]:
    now = time.time()
    if (not force) and (now - float(st.session_state.gateway_status_last_check) < 15):
        return st.session_state.gateway_statuses
    statuses: Dict[int, bool] = {}
    for g in get_gateways():
        ok, _ = ping_gateway(
            str(g.get("url") or "").strip(),
            str(g.get("username") or "").strip(),
            str(g.get("password") or "").strip(),
            timeout=3,
        )
        statuses[int(g["id"])] = bool(ok)
    st.session_state.gateway_statuses = statuses
    st.session_state.gateway_status_last_check = now
    return statuses


def is_device_level_error(response_msg: str, response_data: Optional[Dict]) -> Optional[str]:
    error_keywords = [
        "generic failure", "no service", "radio off", "limit exceeded",
        "sim", "blocked", "network rejected", "not allowed",
    ]
    blob = str(response_msg or "").lower()
    if response_data is not None:
        blob += " " + str(response_data).lower()
    for kw in error_keywords:
        if kw in blob:
            return kw
    return None


def selected_rows(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if SELECT_COL not in df.columns:
        return df.copy()
    return df[df[SELECT_COL] == True].copy()


def highlight_status(row: pd.Series):
    stt = str(row.get("Trạng thái", "")).strip()
    if stt == "Đã gửi":
        css = "background-color: #004d00; color: #bbf7d0; font-weight: 700;"
    elif stt == "Lỗi":
        css = "background-color: #4d0000; color: #fecaca; font-weight: 700;"
    elif stt == "Bỏ qua":
        css = "background-color: #333333; color: #e5e7eb; font-weight: 700;"
    else:
        css = ""
    return [css] * len(row)


def build_retry_message(template: str, failed_row: Dict[str, str]) -> str:
    row_data = {
        "Tên khách hàng": str(failed_row.get("customer_name") or ""),
        "Tên": str(failed_row.get("customer_name") or ""),
        "Ngày hẹn": str(failed_row.get("appointment_date") or ""),
        "Số điện thoại": str(failed_row.get("phone") or ""),
    }
    return parse_spintax(apply_variables(template, row_data))


def _gateway_worker(
    gateway: Dict[str, Any],
    items: List[Dict[str, Any]],
    template: str,
    auto_remove_accent: bool,
    delay_min: float,
    delay_max: float,
    sent_today: set,
    result_queue: queue.Queue,
    stop_event: threading.Event,
) -> None:
    """Worker thread: gửi tin qua một gateway, delay độc lập. Bọc try/except chống crash ngầm."""
    gw_name = str(gateway.get("carrier_name") or "")
    gw_url = str(gateway.get("url") or "").strip()
    gw_user = str(gateway.get("username") or "").strip()
    gw_pass = str(gateway.get("password") or "").strip()

    try:
        for idx, item in enumerate(items):
            if stop_event.is_set():
                break

            row_idx = item["row_idx"]
            phone = item["phone"]
            carrier = item["carrier"]
            route_type = item["route_type"]
            row_data = item["row_data"]
            customer_name = item.get("customer_name", "")
            appointment_date = item.get("appointment_date", "")

            if phone and phone in sent_today:
                result_queue.put({
                    "type": "skip", "row_idx": row_idx, "phone": phone,
                    "gateway_name": gw_name, "carrier": carrier,
                    "route_type": route_type, "cost_vnd": 0,
                    "message": "", "response": "Skip: đã gửi thành công hôm nay",
                    "customer_name": customer_name, "appointment_date": appointment_date,
                })
                continue

            if not phone:
                result_queue.put({
                    "type": "invalid", "row_idx": row_idx, "phone": "",
                    "gateway_name": gw_name, "carrier": carrier,
                    "route_type": route_type, "cost_vnd": 0,
                    "message": "", "response": "Số điện thoại rỗng/không hợp lệ",
                    "customer_name": customer_name, "appointment_date": appointment_date,
                })
                save_log(
                    phone="", customer_name=customer_name,
                    appointment_date=appointment_date, message="",
                    status="Failed", response="Số điện thoại rỗng/không hợp lệ",
                )
                continue

            final_message = parse_spintax(apply_variables(template, row_data))
            if auto_remove_accent:
                final_message = remove_vietnamese_accents(final_message)

            cost_vnd = 50 if route_type == "internal" else 300

            ok, msg, resp_data = False, "", None
            try:
                ok, msg, resp_data = send_sms(
                    gateway_url=gw_url, username=gw_user, password=gw_pass,
                    phone=phone, message=final_message,
                    stop_event=stop_event,
                )
            except Exception as ex:
                msg = f"Gateway exception: {ex}"

            deep_err = is_device_level_error(msg, resp_data)
            if ok and deep_err:
                ok = False
                msg = f"LỖI THIẾT BỊ: {deep_err}"

            result_queue.put({
                "type": "sent" if ok else "failed",
                "row_idx": row_idx, "phone": phone,
                "gateway_name": gw_name, "carrier": carrier,
                "route_type": route_type,
                "cost_vnd": cost_vnd if ok else 0,
                "message": final_message, "response": msg,
                "customer_name": customer_name, "appointment_date": appointment_date,
            })

            if ok:
                sent_today.add(phone)

            save_log(
                phone=phone, customer_name=customer_name,
                appointment_date=appointment_date, message=final_message,
                status="Success" if ok else "Failed", response=msg,
                carrier=carrier, gateway_name=gw_name,
                route_type=route_type, cost_vnd=cost_vnd if ok else 0,
            )

            if stop_event.is_set():
                break

            if idx < len(items) - 1:
                time.sleep(random.uniform(delay_min, delay_max))

    except Exception as e:
        result_queue.put({
            "type": "failed", "row_idx": -1, "phone": "",
            "gateway_name": gw_name, "carrier": "",
            "route_type": "", "cost_vnd": 0,
            "message": "", "response": f"WORKER CRASH [{gw_name}]: {e}",
            "customer_name": "", "appointment_date": "",
        })


init_state()

st.title("Hệ thống SMS Marketing")
st.caption("Dashboard một màn hình — quản lý dữ liệu, cấu hình và gửi SMS hàng loạt đa luồng.")

st.sidebar.markdown(
    '📥 [Tải Gateway App cho Android (v1.56.0)]'
    '(https://github.com/capcom6/android-sms-gateway/releases/download/v1.56.0/app-release.apk)'
)

st.sidebar.divider()
st.sidebar.caption(f"Phiên bản hiện tại: **{CURRENT_VERSION}**")

if "update_info" not in st.session_state:
    st.session_state.update_info = None
    st.session_state.update_checked = False

if st.sidebar.button("Kiểm tra cập nhật", width="stretch", key="btn_check_update"):
    with st.sidebar:
        with st.spinner("Đang kiểm tra..."):
            has_update, latest_ver, dl_url, notes = check_for_update(CURRENT_VERSION)
            st.session_state.update_info = {
                "has_update": has_update,
                "latest_ver": latest_ver,
                "dl_url": dl_url,
                "notes": notes,
            }
            st.session_state.update_checked = True

if st.session_state.update_checked and st.session_state.update_info:
    info = st.session_state.update_info
    if info["has_update"]:
        st.sidebar.warning(
            f"Đã có phiên bản mới **v{info['latest_ver']}**! "
            f"(Hiện tại: v{CURRENT_VERSION})"
        )
        if info.get("notes"):
            st.sidebar.caption(info["notes"][:300])
        if info.get("dl_url"):
            if st.sidebar.button(
                "Tải và cài đặt bản mới", type="primary",
                width="stretch", key="btn_do_update",
            ):
                with st.sidebar:
                    with st.spinner("Đang tải bản cập nhật..."):
                        ok, msg = download_and_run_update(info["dl_url"])
                        if ok:
                            st.success("Đã tải xong! Trình cài đặt đang mở...")
                            import os as _os
                            _os._exit(0)
                        else:
                            st.error(f"Lỗi tải cập nhật: {msg}")
        else:
            st.sidebar.info("Không tìm thấy file .exe trong release. Hãy kiểm tra GitHub.")
    else:
        st.sidebar.success("Bạn đang dùng phiên bản mới nhất.")
elif st.session_state.update_checked:
    st.sidebar.info("Không thể kết nối đến máy chủ cập nhật.")

col_left, col_right = st.columns([6, 4])

# ══════════════════════════════════════════════════════════════════════
#  CỘT TRÁI — Dữ liệu khách hàng
# ══════════════════════════════════════════════════════════════════════
with col_left:
    st.subheader("Dữ liệu khách hàng")

    tool_1, tool_2, tool_3, tool_4, tool_5, tool_6, tool_7 = st.columns(7)

    with tool_1:
        uploaded = st.file_uploader(
            "Tải file", type=["csv", "xlsx"], label_visibility="collapsed"
        )

    if uploaded is not None and uploaded.name != st.session_state.last_loaded_file:
        try:
            loaded_df = ensure_select_column(load_dataframe(uploaded))
            loaded_df = ensure_tracking_columns(loaded_df)
            st.session_state.df = loaded_df
            st.session_state.detected = detect_columns(loaded_df)
            st.session_state.last_loaded_file = uploaded.name
            st.success(f"Đã tải file: {len(loaded_df)} dòng, {len(loaded_df.columns)} cột.")
        except Exception as ex:
            st.error(f"Lỗi đọc file: {ex}")

    if st.session_state.df is None:
        with tool_2:
            st.button("Chuẩn hóa SĐT", disabled=True, width="stretch")
        with tool_3:
            st.button("Lọc trùng SĐT", disabled=True, width="stretch")
        with tool_4:
            st.button("Chọn tất cả", disabled=True, width="stretch")
        with tool_5:
            st.button("Bỏ chọn tất cả", disabled=True, width="stretch")
        with tool_6:
            st.button("Xóa file", disabled=True, width="stretch", type="primary")
        with tool_7:
            st.button("Xóa số đã gửi", disabled=True, width="stretch")
        st.info("Hãy tải file Excel/CSV để bắt đầu.")
    else:
        df = ensure_select_column(st.session_state.df.copy())
        st.session_state.df = df

        mapping = st.session_state.detected
        data_cols = [str(c) for c in df.columns if str(c) != SELECT_COL]
        options = [""] + data_cols

        map_col1, map_col2, map_col3, map_col4 = st.columns([2, 2, 2, 1])
        with map_col1:
            phone_col = st.selectbox(
                "Cột SĐT",
                options=options,
                index=options.index(mapping["phone"]) if mapping["phone"] in options else 0,
            )
        with map_col2:
            name_col = st.selectbox(
                "Cột tên KH",
                options=options,
                index=options.index(mapping["name"]) if mapping["name"] in options else 0,
            )
        with map_col3:
            date_col = st.selectbox(
                "Cột ngày hẹn",
                options=options,
                index=options.index(mapping["date"]) if mapping["date"] in options else 0,
            )
        with map_col4:
            if st.button("Lưu mapping", width="stretch"):
                st.session_state.detected = {
                    "phone": phone_col or None,
                    "name": name_col or None,
                    "date": date_col or None,
                }
                st.success("Đã lưu mapping cột.")

        with tool_2:
            if st.button("Chuẩn hóa SĐT", width="stretch"):
                map_phone = st.session_state.detected.get("phone")
                if not map_phone:
                    st.error("Chưa chọn cột SĐT.")
                else:
                    original = df[map_phone].astype(str)
                    cleaned = original.apply(clean_phone_number)
                    changed = int((original != cleaned).sum())
                    df[map_phone] = cleaned
                    df["Nhà mạng"] = df[map_phone].apply(get_carrier)
                    st.session_state.df = df
                    st.success(
                        f"Đã chuẩn hóa {len(df)} số. Thay đổi: {changed} dòng. "
                        "Đã thêm cột 'Nhà mạng'."
                    )

        with tool_3:
            if st.button("Lọc trùng SĐT", width="stretch"):
                map_phone = st.session_state.detected.get("phone")
                if not map_phone:
                    st.error("Chưa chọn cột SĐT.")
                else:
                    before = len(df)
                    dedup = df.drop_duplicates(subset=[map_phone], keep="first").reset_index(drop=True)
                    removed = before - len(dedup)
                    st.session_state.df = dedup
                    if removed > 0:
                        st.success(f"Đã xóa {removed} dòng trùng. Còn lại {len(dedup)} dòng.")
                    else:
                        st.info("Không có dòng trùng lặp theo SĐT.")

        with tool_4:
            if st.button("Chọn tất cả", width="stretch"):
                df[SELECT_COL] = True
                st.session_state.df = df
                st.info(f"Đã chọn {len(df)} dòng.")

        with tool_5:
            if st.button("Bỏ chọn tất cả", width="stretch"):
                df[SELECT_COL] = False
                st.session_state.df = df
                st.info(f"Đã bỏ chọn {len(df)} dòng.")

        with tool_6:
            if st.button("Xóa file", width="stretch", type="primary"):
                st.session_state.df = None
                st.session_state.detected = {"phone": None, "name": None, "date": None}
                st.session_state.last_loaded_file = None
                st.success("Đã xóa dữ liệu hiện tại.")

        with tool_7:
            if st.button("Xóa số đã gửi", width="stretch"):
                if "Trạng thái" not in df.columns:
                    st.info("Chưa có cột 'Trạng thái' để lọc.")
                else:
                    before = len(df)
                    df = df[df["Trạng thái"].astype(str).str.strip() != "Đã gửi"].copy()
                    removed = before - len(df)
                    st.session_state.df = df
                    st.success(f"Đã xóa {removed} dòng đã gửi.")
                    st.rerun()

        if st.session_state.df is not None:
            st.markdown(
                "🟩 **Đã gửi thành công** &nbsp;&nbsp;|&nbsp;&nbsp; "
                "🟥 **Lỗi thiết bị/Mạng** &nbsp;&nbsp;|&nbsp;&nbsp; "
                "🟨 **Bỏ qua (Đã gửi hôm nay)**",
                unsafe_allow_html=True,
            )
            editor_df = st.data_editor(
                ensure_select_column(st.session_state.df),
                width="stretch",
                height=560,
                num_rows="dynamic",
                key="main_data_editor",
            )
            st.session_state.df = ensure_tracking_columns(ensure_select_column(editor_df))

            st.dataframe(
                st.session_state.df.head(250).style.apply(highlight_status, axis=1),
                width="stretch",
                height=220,
            )

# ══════════════════════════════════════════════════════════════════════
#  CỘT PHẢI — Điều khiển và gửi tin
# ══════════════════════════════════════════════════════════════════════
with col_right:
    st.subheader("Điều khiển và gửi tin")

    with st.expander("Cấu hình API & Delay", expanded=False):
        st.markdown("**Quản lý Gateways (đa thiết bị)**")

        gateways_live = get_gateways()
        ensure_single_default_gateway()
        gateways_live = get_gateways()

        carrier_options = ["Viettel", "MobiFone", "VinaPhone", "Vietnamobile", "Default"]
        gateway_choices = ["(Tạo mới)"] + [
            f"#{g['id']} - {g.get('carrier_name')} - {g.get('url')}"
            for g in gateways_live
        ]
        selected_label = st.selectbox("Chọn gateway để sửa", options=gateway_choices, index=0)
        selected_id = None
        if selected_label != "(Tạo mới)":
            try:
                selected_id = int(selected_label.split(" - ")[0].replace("#", "").strip())
            except Exception:
                selected_id = None
        st.session_state.selected_gateway_id = selected_id

        selected_gw = (
            next((g for g in gateways_live if int(g["id"]) == int(selected_id)), None)
            if selected_id
            else None
        )

        with st.form("gateway_form", clear_on_submit=False):
            f_carrier = st.selectbox(
                "Nhà mạng",
                options=carrier_options,
                index=(
                    carrier_options.index(selected_gw["carrier_name"])
                    if selected_gw and selected_gw.get("carrier_name") in carrier_options
                    else carrier_options.index("Default")
                ),
            )
            f_url = st.text_input("URL Gateway", value=str(selected_gw.get("url")) if selected_gw else "")
            f_user = st.text_input("Username", value=str(selected_gw.get("username")) if selected_gw else "")
            f_pass = st.text_input("Password", value=str(selected_gw.get("password")) if selected_gw else "", type="password")
            f_default = st.checkbox(
                "Đặt làm mặc định",
                value=bool(int(selected_gw.get("is_default") or 0)) if selected_gw else (f_carrier == "Default"),
            )

            submit = st.form_submit_button("Thêm / Cập nhật Gateway")
            if submit:
                if not f_url.strip() or not f_user.strip() or not f_pass.strip():
                    st.error("URL / Username / Password là bắt buộc.")
                else:
                    upsert_gateway(
                        gateway_id=selected_id,
                        carrier_name=f_carrier,
                        url=f_url.strip(),
                        username=f_user.strip(),
                        password=f_pass.strip(),
                        is_default=1 if f_default else 0,
                    )
                    ensure_single_default_gateway()
                    st.success("Đã lưu gateway.")
                    st.rerun()

        gateways_live = get_gateways()
        if gateways_live:
            show_df = pd.DataFrame(gateways_live)
            if "password" in show_df.columns:
                show_df["password"] = "********"
            st.dataframe(show_df, width="stretch", height=180)

            del_col1, del_col2 = st.columns(2)
            with del_col1:
                del_id = st.number_input("ID cần xóa", min_value=0, value=0, step=1)
            with del_col2:
                if st.button("Xóa gateway", type="primary", width="stretch", disabled=int(del_id) <= 0):
                    delete_gateway(int(del_id))
                    ensure_single_default_gateway()
                    st.success("Đã xóa gateway.")
                    st.rerun()
        else:
            st.info("Chưa có gateway nào. Hãy thêm ít nhất 1 gateway Default.")

        cfg_col1, cfg_col2 = st.columns(2)
        with cfg_col1:
            delay_min = st.number_input(
                "Delay tối thiểu (giây)", min_value=0,
                value=get_setting_int("delay_min", 30), step=1,
            )
        with cfg_col2:
            delay_max = st.number_input(
                "Delay tối đa (giây)", min_value=0,
                value=get_setting_int("delay_max", 60), step=1,
            )
        max_send_per_session = st.number_input(
            "Giới hạn gửi tối đa mỗi phiên", min_value=1,
            value=get_setting_int("max_send_per_session", 200), step=1,
        )
        b1, b2 = st.columns(2)
        with b1:
            if st.button("Lưu cấu hình", width="stretch"):
                if delay_max < delay_min:
                    st.error("Delay tối đa phải >= delay tối thiểu.")
                else:
                    set_setting("delay_min", str(delay_min))
                    set_setting("delay_max", str(delay_max))
                    set_setting("max_send_per_session", str(max_send_per_session))
                    ensure_single_default_gateway()
                    st.success("Đã lưu cấu hình delay + giới hạn.")
        with b2:
            if st.button("Kiểm tra kết nối", width="stretch"):
                gws = get_gateways()
                if not gws:
                    st.error("Chưa có gateway nào để test.")
                else:
                    for g in gws:
                        title = f"#{g['id']} - {g.get('carrier_name')} - {g.get('url')}"
                        with st.status(title, expanded=False) as s:
                            ok, msg = ping_gateway(
                                str(g.get("url") or "").strip(),
                                str(g.get("username") or "").strip(),
                                str(g.get("password") or "").strip(),
                            )
                            if ok:
                                s.update(label=f"{title}: ONLINE", state="complete")
                                st.success(msg)
                            else:
                                s.update(label=f"{title}: OFFLINE", state="error")
                                st.error(msg)

    # ── Soạn nội dung tin nhắn ────────────────────────────────────────
    variable_df = st.session_state.df
    variable_cols = []
    if variable_df is not None:
        variable_cols = [str(c) for c in variable_df.columns if c != SELECT_COL]

    st.markdown("**Biến khả dụng:**")
    if variable_cols:
        st.markdown(" ".join([f"`[{col}]`" for col in variable_cols]))
    else:
        st.caption("Chưa có biến. Hãy tải file dữ liệu.")

    templates = spintax_templates()
    chosen_template = st.selectbox(
        "Gợi ý mẫu Spintax",
        options=["(Không chọn)"] + list(templates.keys()),
        index=0,
        key="template_picker",
    )
    if chosen_template != "(Không chọn)":
        st.session_state.message_template_live = templates[chosen_template]

    template = st.text_area(
        "Nội dung Spintax",
        value=st.session_state.message_template_live,
        height=150,
        key="message_template_textarea",
    )
    if st.button("Lưu mẫu tin nhắn", width="stretch"):
        set_setting("message_template", template)
        st.success("Đã lưu mẫu tin nhắn.")
        st.session_state.message_template_live = template

    if st.button("AI Rewrite (Tạo biến thể tự động)", width="stretch"):
        rewritten = simple_ai_rewrite_to_spintax(template)
        st.session_state.message_template_live = rewritten
        st.success("Đã tạo biến thể Spintax tự động.")
        st.rerun()

    auto_remove_accent = st.checkbox(
        "Tự động xóa dấu tiếng Việt (tiết kiệm SMS)",
        value=get_value("remove_accent", "0") == "1",
    )
    set_setting("remove_accent", "1" if auto_remove_accent else "0")

    # ── Trạng thái Gateway ────────────────────────────────────────────
    st.markdown("### Trạng thái Gateway")
    gstat_col1, gstat_col2 = st.columns([3, 1])
    with gstat_col2:
        if st.button("Làm mới", width="stretch", key="refresh_gateway_status"):
            refresh_gateway_statuses(force=True)
    statuses = refresh_gateway_statuses(force=False)
    gateways_live = get_gateways()
    if not gateways_live:
        st.caption("Chưa có gateway nào.")
    else:
        for g in gateways_live:
            gid = int(g["id"])
            is_online = bool(statuses.get(gid, False))
            dot = "🟢" if is_online else "🔴"
            carrier = str(g.get("carrier_name") or "")
            host = _host_from_url(str(g.get("url") or ""))
            st.caption(f"{dot} {carrier} — {host}")

    # ── Lọc nhà mạng ─────────────────────────────────────────────────
    st.markdown("### Lọc nhà mạng cần gửi")
    carrier_filter_options = ["Viettel", "MobiFone", "VinaPhone", "Vietnamobile", "Unknown"]
    carrier_filter = st.multiselect(
        "Chọn nhà mạng cần gửi",
        options=carrier_filter_options,
        default=carrier_filter_options,
        key="carrier_filter_multiselect",
    )

    # ── Xem trước tin nhắn ────────────────────────────────────────────
    st.markdown("### Xem trước tin nhắn")
    selected_df = selected_rows(st.session_state.df)
    if selected_df.empty:
        st.info("Không có dòng được chọn gửi để xem trước.")
    else:
        pcol1, pcol2 = st.columns([3, 1])
        with pcol2:
            if st.button("Làm mới", width="stretch", key="refresh_preview"):
                st.session_state.preview_refresh_counter += 1
        with pcol1:
            _ = st.session_state.preview_refresh_counter
            i = random.randint(0, len(selected_df) - 1)
            preview_msg = render_message(template, selected_df.iloc[i])
            if auto_remove_accent:
                preview_msg = remove_vietnamese_accents(preview_msg)
            chars = len(preview_msg)
            parts = estimate_sms_parts(preview_msg, is_accent_removed=auto_remove_accent)
            st.code(preview_msg, language="text")
            st.info(
                f"Số ký tự: {chars} | Số phần SMS: {parts} | "
                f"Ngưỡng: {'160' if auto_remove_accent else '70'} ký tự/phần"
            )

    # ══════════════════════════════════════════════════════════════════
    #  GỬI TIN ĐA LUỒNG — Main Thread Polling (while-loop + placeholder)
    # ══════════════════════════════════════════════════════════════════
    st.markdown("### Gửi tin đa luồng")

    if st.session_state.is_sending:
        stop_btn = st.button("DỪNG GỬI", type="primary", width="stretch", key="stop_sending")
        if stop_btn:
            st.session_state.stop_requested = True
            if st.session_state.stop_event is not None:
                st.session_state.stop_event.set()
    else:
        send_btn = st.button(
            "BẮT ĐẦU GỬI (Đa luồng)", type="primary", width="stretch", key="start_sending"
        )

    progress_ph = st.empty()
    status_ph = st.empty()
    table_ph = st.empty()

    progress_ph.progress(0, text="Sẵn sàng gửi...")

    # ── Khởi tạo workers khi bấm nút ─────────────────────────────────
    if (not st.session_state.is_sending) and ("send_btn" in locals()) and send_btn:
        send_df = selected_rows(st.session_state.df)
        mapping = st.session_state.detected
        gateways_all = get_gateways()
        d_min = get_setting_int("delay_min", 30)
        d_max = get_setting_int("delay_max", 60)

        if send_df.empty:
            st.error("Không có dòng nào được chọn gửi.")
        elif not mapping.get("phone"):
            st.error("Chưa chọn cột SĐT.")
        elif not gateways_all:
            st.error("Chưa cấu hình gateway. Hãy thêm ít nhất 1 gateway Default.")
        elif d_max < d_min:
            st.error("Delay tối đa phải >= delay tối thiểu.")
        else:
            phone_col = mapping.get("phone")
            name_col = mapping.get("name")
            date_col = mapping.get("date")

            if "Nhà mạng" not in st.session_state.df.columns:
                st.session_state.df["Nhà mạng"] = st.session_state.df[phone_col].apply(
                    lambda v: get_carrier(clean_phone_number(str(v)))
                )
            st.session_state.df = ensure_tracking_columns(st.session_state.df)

            queue_df = selected_rows(st.session_state.df)
            if carrier_filter:
                queue_df = queue_df[queue_df["Nhà mạng"].isin(carrier_filter)].copy()
            if queue_df.empty:
                st.warning("Không có dòng nào thỏa điều kiện nhà mạng.")
                st.stop()

            default_gw = next(
                (g for g in gateways_all if int(g.get("is_default") or 0) == 1), None
            )
            by_carrier: Dict[str, Any] = {}
            for g in gateways_all:
                cn = str(g.get("carrier_name") or "").strip()
                if cn and cn != "Default":
                    by_carrier[cn] = g

            if default_gw is None:
                st.error("Bắt buộc có 1 gateway mặc định (Default).")
                st.stop()

            gw_queues: Dict[int, Dict[str, Any]] = {}
            for row_idx in queue_df.index:
                row = st.session_state.df.loc[row_idx]
                phone = clean_phone_number(str(row.get(phone_col, "")))
                carrier = get_carrier(phone) if phone else "Unknown"
                gw = by_carrier.get(carrier) or default_gw
                rt = "internal" if carrier in by_carrier else "external"
                gw_id = int(gw["id"])
                if gw_id not in gw_queues:
                    gw_queues[gw_id] = {"gateway": gw, "items": []}
                gw_queues[gw_id]["items"].append({
                    "row_idx": int(row_idx),
                    "phone": phone,
                    "carrier": carrier,
                    "route_type": rt,
                    "row_data": format_row_data(row),
                    "customer_name": str(row.get(name_col, "")) if name_col else "",
                    "appointment_date": str(row.get(date_col, "")) if date_col else "",
                })

            rq: queue.Queue = queue.Queue()
            se = threading.Event()
            st_today = set(get_success_phones_today())

            executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=max(len(gw_queues), 1)
            )
            futures: List[concurrent.futures.Future] = []
            for _gw_id, gw_data in gw_queues.items():
                f = executor.submit(
                    _gateway_worker,
                    gateway=gw_data["gateway"],
                    items=gw_data["items"],
                    template=template,
                    auto_remove_accent=auto_remove_accent,
                    delay_min=float(d_min),
                    delay_max=float(d_max),
                    sent_today=st_today,
                    result_queue=rq,
                    stop_event=se,
                )
                futures.append(f)

            st.session_state.result_queue = rq
            st.session_state.stop_event = se
            st.session_state.send_futures = futures
            st.session_state.send_executor = executor
            st.session_state.sending_total = sum(len(d["items"]) for d in gw_queues.values())
            st.session_state.sending_success_count = 0
            st.session_state.sending_fail_count = 0
            st.session_state.sending_processed_count = 0
            st.session_state.stop_requested = False
            st.session_state.is_sending = True
            st.rerun()

    # ── Vòng lặp polling realtime (while-loop, KHÔNG dùng st.rerun) ──
    if st.session_state.is_sending:
        rq = st.session_state.result_queue
        futures = st.session_state.send_futures or []
        stop_evt = st.session_state.stop_event
        max_send = get_setting_int("max_send_per_session", 200)

        if rq is None or st.session_state.df is None:
            st.session_state.is_sending = False
            status_ph.warning("Không có hàng đợi gửi.")
        else:
            st.session_state.df = ensure_tracking_columns(st.session_state.df)
            last_phone = ""

            while True:
                if st.session_state.stop_requested and stop_evt and not stop_evt.is_set():
                    stop_evt.set()

                got_new = False
                while True:
                    try:
                        r: Dict = rq.get_nowait()
                    except queue.Empty:
                        break
                    row_idx = r["row_idx"]
                    rtype = r["type"]
                    got_new = True

                    if row_idx >= 0 and row_idx in st.session_state.df.index:
                        if rtype == "skip":
                            st.session_state.df.loc[row_idx, "Trạng thái"] = "Bỏ qua"
                            st.session_state.df.loc[row_idx, "Phản hồi"] = r["response"]
                            st.session_state.df.loc[row_idx, "Gửi từ"] = ""
                        elif rtype == "invalid":
                            st.session_state.df.loc[row_idx, "Trạng thái"] = "Lỗi"
                            st.session_state.df.loc[row_idx, "Phản hồi"] = r["response"]
                            st.session_state.df.loc[row_idx, "Gửi từ"] = ""
                            st.session_state.sending_fail_count += 1
                        elif rtype == "sent":
                            st.session_state.df.loc[row_idx, "Trạng thái"] = "Đã gửi"
                            st.session_state.df.loc[row_idx, "Gửi từ"] = r["gateway_name"]
                            st.session_state.df.loc[row_idx, "Phản hồi"] = r["response"]
                            st.session_state.sending_success_count += 1
                        elif rtype == "failed":
                            st.session_state.df.loc[row_idx, "Trạng thái"] = "Lỗi"
                            st.session_state.df.loc[row_idx, "Gửi từ"] = r["gateway_name"]
                            st.session_state.df.loc[row_idx, "Phản hồi"] = r["response"]
                            st.session_state.sending_fail_count += 1
                    elif rtype == "failed" and row_idx < 0:
                        st.session_state.sending_fail_count += 1

                    st.session_state.sending_processed_count += 1
                    last_phone = r.get("phone", "")

                total = max(int(st.session_state.sending_total or 1), 1)
                processed = int(st.session_state.sending_processed_count or 0)
                active = sum(1 for f in futures if not f.done())
                pct = min(int((processed / total) * 100), 100)

                progress_ph.progress(
                    pct,
                    text=(
                        f"Đã xử lý {processed}/{total} | "
                        f"Thành công: {st.session_state.sending_success_count} | "
                        f"Lỗi: {st.session_state.sending_fail_count} | "
                        f"Luồng đang chạy: {active}"
                    ),
                )

                if got_new:
                    status_ph.info(f"Vừa xử lý: {last_phone}")
                    try:
                        styled = st.session_state.df.head(200).style.apply(
                            highlight_status, axis=1
                        )
                        table_ph.dataframe(styled, width="stretch", height=300)
                    except Exception:
                        pass

                if st.session_state.sending_success_count >= max_send:
                    if stop_evt and not stop_evt.is_set():
                        stop_evt.set()

                all_done = all(f.done() for f in futures) if futures else True
                if all_done and rq.empty():
                    break

                time.sleep(0.5)

            # ── Hoàn tất ──────────────────────────────────────────────
            s_ok = int(st.session_state.sending_success_count or 0)
            s_fail = int(st.session_state.sending_fail_count or 0)
            total_display = int(st.session_state.sending_total or 0)

            progress_ph.progress(100, text="Hoàn tất!")
            if s_fail == 0:
                status_ph.success(f"Hoàn tất: thành công {s_ok}/{total_display}.")
            else:
                status_ph.warning(
                    f"Hoàn tất: thành công {s_ok}, thất bại {s_fail}/{total_display}."
                )
            try:
                styled = st.session_state.df.head(200).style.apply(highlight_status, axis=1)
                table_ph.dataframe(styled, width="stretch", height=300)
            except Exception:
                pass

            if st.session_state.send_executor:
                st.session_state.send_executor.shutdown(wait=False)
            st.session_state.send_executor = None
            st.session_state.send_futures = []
            st.session_state.result_queue = None
            st.session_state.stop_event = None
            st.session_state.sending_processed_count = 0
            st.session_state.is_sending = False

# ══════════════════════════════════════════════════════════════════════
#  LỊCH SỬ GỬI & GỬI LẠI THẤT BẠI
# ══════════════════════════════════════════════════════════════════════
st.divider()
with st.expander("Lịch sử gửi & Gửi lại thất bại", expanded=False):
    log_limit = st.number_input(
        "Số lượng log gần nhất", min_value=10, max_value=5000,
        value=300, step=10, key="logs_limit",
    )
    logs = get_logs(limit=int(log_limit))
    if not logs:
        st.info("Chưa có lịch sử gửi.")
    else:
        log_df = pd.DataFrame(logs)

        success_df = (
            log_df[log_df["status"].astype(str).str.upper() == "SUCCESS"]
            if "status" in log_df.columns
            else pd.DataFrame()
        )
        total_success = int(len(success_df)) if not success_df.empty else 0
        actual_cost = (
            int(success_df.get("cost_vnd", pd.Series(dtype=int)).fillna(0).sum())
            if total_success > 0
            else 0
        )
        baseline_cost = total_success * 300
        saved_cost = baseline_cost - actual_cost

        m1, m2, m3 = st.columns(3)
        m1.metric("Tổng tin thành công", f"{total_success}")
        m2.metric("Tổng chi phí thực tế (VNĐ)", f"{actual_cost:,}")
        m3.metric("Tiền tiết kiệm (VNĐ)", f"{saved_cost:,}")

        st.dataframe(log_df, width="stretch", height=320)

    failed_logs = get_failed_logs(limit=5000)
    failed_count = len(failed_logs)
    st.caption(f"Số bản ghi thất bại hiện có: {failed_count}")

    retry_col1, retry_col2 = st.columns(2)
    with retry_col1:
        if failed_count > 0:
            failed_csv = pd.DataFrame(failed_logs).to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "Xuất danh sách thất bại (CSV)",
                data=failed_csv,
                file_name="failed_sms_logs.csv",
                mime="text/csv",
                width="stretch",
            )
        else:
            st.button("Xuất danh sách thất bại (CSV)", disabled=True, width="stretch")

    with retry_col2:
        retry_remove_accent = st.checkbox(
            "Xóa dấu khi gửi lại",
            value=get_value("remove_accent", "0") == "1",
            key="retry_remove_accent",
        )
        retry_clicked = st.button(
            "Gửi lại danh sách thất bại",
            type="primary",
            width="stretch",
            disabled=failed_count == 0,
            key="retry_failed_btn",
        )

    retry_progress = st.progress(0, text="Sẵn sàng gửi lại...")
    retry_status_box = st.empty()

    if retry_clicked:
        gateways = get_gateways()
        delay_min = get_setting_int("delay_min", 30)
        delay_max = get_setting_int("delay_max", 60)
        retry_template = get_value("message_template", "")

        if not retry_template:
            st.error("Chưa có mẫu tin. Hãy lưu mẫu tin ở khu soạn nội dung.")
        elif not gateways:
            st.error("Chưa cấu hình gateway. Hãy thêm ít nhất 1 gateway Default.")
        elif delay_max < delay_min:
            st.error("Delay tối đa phải >= delay tối thiểu.")
        else:
            default_gw = next((g for g in gateways if int(g.get("is_default") or 0) == 1), None)
            by_carrier = {}
            for g in gateways:
                cname = str(g.get("carrier_name") or "").strip()
                if cname and cname != "Default":
                    by_carrier[cname] = g
            if default_gw is None:
                st.error("Bắt buộc có 1 gateway mặc định (is_default=True).")
                st.stop()

            retry_total = len(failed_logs)
            retry_success = 0
            retry_fail = 0

            for idx, row in enumerate(failed_logs):
                phone = clean_phone_number(str(row.get("phone") or ""))
                if not phone:
                    retry_fail += 1
                    update_log_after_retry(
                        log_id=int(row["id"]),
                        status="Failed",
                        response="Retry thất bại: số điện thoại không hợp lệ",
                    )
                    retry_progress.progress(
                        int(((idx + 1) / retry_total) * 100),
                        text=f"Đã xử lý retry {idx + 1}/{retry_total}",
                    )
                    continue

                retry_message = build_retry_message(retry_template, row)
                if retry_remove_accent:
                    retry_message = remove_vietnamese_accents(retry_message)

                carrier = get_carrier(phone)
                gw = by_carrier.get(carrier) or default_gw
                route_type = "internal" if by_carrier.get(carrier) is not None else "external"
                cost_vnd = 50 if route_type == "internal" else 300

                ok, msg, _ = send_sms(
                    gateway_url=str(gw.get("url") or ""),
                    username=str(gw.get("username") or ""),
                    password=str(gw.get("password") or ""),
                    phone=phone,
                    message=retry_message,
                )

                if ok:
                    retry_success += 1
                    current_status = "Thành công"
                    update_log_after_retry(
                        log_id=int(row["id"]),
                        status="Success",
                        response=f"Retry thành công: {msg}",
                        message=retry_message,
                        carrier=carrier,
                        gateway_name=str(gw.get("carrier_name") or ""),
                        route_type=route_type,
                        cost_vnd=cost_vnd,
                    )
                else:
                    retry_fail += 1
                    current_status = "Thất bại"
                    update_log_after_retry(
                        log_id=int(row["id"]),
                        status="Failed",
                        response=f"Retry thất bại: {msg}",
                        message=retry_message,
                        carrier=carrier,
                        gateway_name=str(gw.get("carrier_name") or ""),
                        route_type=route_type,
                        cost_vnd=0,
                    )

                retry_status_box.info(
                    f"[{idx + 1}/{retry_total}] {phone} → {current_status} | "
                    f"OK: {retry_success}, Lỗi: {retry_fail} | Phản hồi: {msg}"
                )
                retry_progress.progress(
                    int(((idx + 1) / retry_total) * 100),
                    text=f"Đã retry {idx + 1}/{retry_total}",
                )

                if idx < retry_total - 1:
                    time.sleep(random.uniform(delay_min, delay_max))

            if retry_fail == 0:
                st.success(f"Retry hoàn tất: thành công {retry_success}/{retry_total}.")
            else:
                st.warning(
                    f"Retry hoàn tất: thành công {retry_success}, thất bại {retry_fail}/{retry_total}."
                )

# ══════════════════════════════════════════════════════════════════════
#  FOOTER
# ══════════════════════════════════════════════════════════════════════
st.markdown(
    """
<div style="background: linear-gradient(145deg, #18181b, #27272a); padding: 25px; border-radius: 12px; border-left: 5px solid #d4af37; box-shadow: 0 4px 15px rgba(0,0,0,0.5); text-align: center; margin-top: 50px; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;">
    <h4 style="color: #d4af37; margin: 0 0 12px 0; letter-spacing: 1.5px; font-weight: 700; text-transform: uppercase;">Hệ Thống Quản Trị SMS Marketing</h4>
    <p style="color: #e4e4e7; margin: 5px 0; font-size: 16px;">Phát triển & Tối ưu bởi: <span style="color: #ffffff; font-weight: bold; text-transform: uppercase;">Phạm Duy</span></p>
    <p style="color: #a1a1aa; margin: 8px 0 0 0; font-size: 14px;">📞 Hotline: <span style="color: #d4af37; font-weight: bold;">0868 609 901</span> &nbsp;|&nbsp; 📧 Email: <span style="color: #d4af37;">duyhondavn@gmail.com</span></p>
</div>
""",
    unsafe_allow_html=True,
)
