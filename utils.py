import random
import re
from datetime import datetime
from typing import Dict, Optional

import pandas as pd


COLUMN_HINTS = {
    "phone": [
        "so dien thoai",
        "sdt",
        "so dt",
        "phone",
        "phone number",
        "mobile",
        "tel",
        "so dien thoai khach",
    ],
    "name": [
        "ten",
        "ten khach hang",
        "khach hang",
        "ho ten",
        "name",
        "customer",
    ],
    "date": [
        "ngay hen",
        "lich hen",
        "appointment",
        "date",
        "ngay",
        "ngay kiem tra",
    ],
}

_RNG = random.SystemRandom()
_VIETNAMESE_ACCENT_MAP = str.maketrans(
    {
        "à": "a",
        "á": "a",
        "ạ": "a",
        "ả": "a",
        "ã": "a",
        "â": "a",
        "ầ": "a",
        "ấ": "a",
        "ậ": "a",
        "ẩ": "a",
        "ẫ": "a",
        "ă": "a",
        "ằ": "a",
        "ắ": "a",
        "ặ": "a",
        "ẳ": "a",
        "ẵ": "a",
        "è": "e",
        "é": "e",
        "ẹ": "e",
        "ẻ": "e",
        "ẽ": "e",
        "ê": "e",
        "ề": "e",
        "ế": "e",
        "ệ": "e",
        "ể": "e",
        "ễ": "e",
        "ì": "i",
        "í": "i",
        "ị": "i",
        "ỉ": "i",
        "ĩ": "i",
        "ò": "o",
        "ó": "o",
        "ọ": "o",
        "ỏ": "o",
        "õ": "o",
        "ô": "o",
        "ồ": "o",
        "ố": "o",
        "ộ": "o",
        "ổ": "o",
        "ỗ": "o",
        "ơ": "o",
        "ờ": "o",
        "ớ": "o",
        "ợ": "o",
        "ở": "o",
        "ỡ": "o",
        "ù": "u",
        "ú": "u",
        "ụ": "u",
        "ủ": "u",
        "ũ": "u",
        "ư": "u",
        "ừ": "u",
        "ứ": "u",
        "ự": "u",
        "ử": "u",
        "ữ": "u",
        "ỳ": "y",
        "ý": "y",
        "ỵ": "y",
        "ỷ": "y",
        "ỹ": "y",
        "đ": "d",
        "À": "A",
        "Á": "A",
        "Ạ": "A",
        "Ả": "A",
        "Ã": "A",
        "Â": "A",
        "Ầ": "A",
        "Ấ": "A",
        "Ậ": "A",
        "Ẩ": "A",
        "Ẫ": "A",
        "Ă": "A",
        "Ằ": "A",
        "Ắ": "A",
        "Ặ": "A",
        "Ẳ": "A",
        "Ẵ": "A",
        "È": "E",
        "É": "E",
        "Ẹ": "E",
        "Ẻ": "E",
        "Ẽ": "E",
        "Ê": "E",
        "Ề": "E",
        "Ế": "E",
        "Ệ": "E",
        "Ể": "E",
        "Ễ": "E",
        "Ì": "I",
        "Í": "I",
        "Ị": "I",
        "Ỉ": "I",
        "Ĩ": "I",
        "Ò": "O",
        "Ó": "O",
        "Ọ": "O",
        "Ỏ": "O",
        "Õ": "O",
        "Ô": "O",
        "Ồ": "O",
        "Ố": "O",
        "Ộ": "O",
        "Ổ": "O",
        "Ỗ": "O",
        "Ơ": "O",
        "Ờ": "O",
        "Ớ": "O",
        "Ợ": "O",
        "Ở": "O",
        "Ỡ": "O",
        "Ù": "U",
        "Ú": "U",
        "Ụ": "U",
        "Ủ": "U",
        "Ũ": "U",
        "Ư": "U",
        "Ừ": "U",
        "Ứ": "U",
        "Ự": "U",
        "Ử": "U",
        "Ữ": "U",
        "Ỳ": "Y",
        "Ý": "Y",
        "Ỵ": "Y",
        "Ỷ": "Y",
        "Ỹ": "Y",
        "Đ": "D",
    }
)


def normalize_text(text: str) -> str:
    # Chuẩn hóa text (không dấu, lower-case) để nhận diện tên cột linh hoạt hơn.
    text = str(text).strip().lower()
    repl = {
        "á": "a",
        "à": "a",
        "ả": "a",
        "ã": "a",
        "ạ": "a",
        "ă": "a",
        "ắ": "a",
        "ằ": "a",
        "ẳ": "a",
        "ẵ": "a",
        "ặ": "a",
        "â": "a",
        "ấ": "a",
        "ầ": "a",
        "ẩ": "a",
        "ẫ": "a",
        "ậ": "a",
        "đ": "d",
        "é": "e",
        "è": "e",
        "ẻ": "e",
        "ẽ": "e",
        "ẹ": "e",
        "ê": "e",
        "ế": "e",
        "ề": "e",
        "ể": "e",
        "ễ": "e",
        "ệ": "e",
        "í": "i",
        "ì": "i",
        "ỉ": "i",
        "ĩ": "i",
        "ị": "i",
        "ó": "o",
        "ò": "o",
        "ỏ": "o",
        "õ": "o",
        "ọ": "o",
        "ô": "o",
        "ố": "o",
        "ồ": "o",
        "ổ": "o",
        "ỗ": "o",
        "ộ": "o",
        "ơ": "o",
        "ớ": "o",
        "ờ": "o",
        "ở": "o",
        "ỡ": "o",
        "ợ": "o",
        "ú": "u",
        "ù": "u",
        "ủ": "u",
        "ũ": "u",
        "ụ": "u",
        "ư": "u",
        "ứ": "u",
        "ừ": "u",
        "ử": "u",
        "ữ": "u",
        "ự": "u",
        "ý": "y",
        "ỳ": "y",
        "ỷ": "y",
        "ỹ": "y",
        "ỵ": "y",
    }
    for src, dst in repl.items():
        text = text.replace(src, dst)
    text = re.sub(r"\s+", " ", text)
    return text


def detect_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    # Tự động map các cột phổ biến từ file import về phone/name/date.
    detected: Dict[str, Optional[str]] = {"phone": None, "name": None, "date": None}
    normalized_cols = {col: normalize_text(col) for col in df.columns}
    for key, hints in COLUMN_HINTS.items():
        for col, norm in normalized_cols.items():
            if any(hint in norm for hint in hints):
                detected[key] = col
                break
    return detected


def parse_spintax(text: str) -> str:
    # Resolve innermost groups first so nested spintax works correctly.
    while "{" in text and "}" in text:
        stack = []
        replaced = False
        for idx, ch in enumerate(text):
            if ch == "{":
                stack.append(idx)
            elif ch == "}" and stack:
                start = stack.pop()
                content = text[start + 1 : idx]
                choices = [choice.strip() for choice in content.split("|") if choice.strip()]
                if not choices:
                    replacement = ""
                else:
                    replacement = _RNG.choice(choices)
                text = text[:start] + replacement + text[idx + 1 :]
                replaced = True
                break
        if not replaced:
            break
    return text


def _format_cell_value(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if pd.isna(value):
        return ""
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.strftime("%d/%m/%Y")
    return str(value).strip()


def apply_variables(template: str, row_data: Dict[str, str]) -> str:
    # Thay thế [Tên cột] trong template bằng dữ liệu thật của từng dòng.
    def repl(match: re.Match) -> str:
        key = match.group(1).strip()
        return row_data.get(key, "")

    return re.sub(r"\[([^\]]+)\]", repl, template)


def render_message(template: str, row: pd.Series) -> str:
    # Pipeline render: thay biến -> trộn spintax.
    row_data = {str(col): _format_cell_value(row[col]) for col in row.index}
    with_vars = apply_variables(template, row_data)
    return parse_spintax(with_vars)


def format_row_data(row: pd.Series) -> Dict[str, str]:
    """Chuyển Pandas Series thành dict chuỗi đã format (thread-safe, không phụ thuộc Pandas)."""
    return {str(col): _format_cell_value(row[col]) for col in row.index}


def clean_phone_number(phone: str) -> str:
    # Chuẩn hóa số điện thoại về định dạng nội địa bắt đầu bằng 0.
    if phone is None:
        return ""
    value = str(phone).strip()
    value = re.sub(r"[\s\.\-]", "", value)
    value = re.sub(r"[^\d+]", "", value)

    if value.startswith("+84"):
        value = "0" + value[3:]
    elif value.startswith("84"):
        value = "0" + value[2:]
    elif value.startswith("+"):
        value = value[1:]

    value = re.sub(r"[^\d]", "", value)
    if value and not value.startswith("0"):
        value = "0" + value
    return value


def remove_vietnamese_accents(text: str) -> str:
    # Chuyển tiếng Việt có dấu thành không dấu để tối ưu độ dài SMS.
    if text is None:
        return ""
    return str(text).translate(_VIETNAMESE_ACCENT_MAP)


def estimate_sms_parts(message: str, is_accent_removed: bool) -> int:
    length = len(message or "")
    if length == 0:
        return 0
    single_part_limit = 160 if is_accent_removed else 70
    return (length + single_part_limit - 1) // single_part_limit


def get_carrier(phone: str) -> str:
    """
    Phân loại nhà mạng theo đầu số VN (cập nhật phổ biến 2024).
    Đầu vào nên là số dạng 0xxxxxxxxx (đã qua clean_phone_number).
    """
    p = clean_phone_number(phone)
    if len(p) < 3:
        return "Unknown"

    prefix3 = p[:3]

    viettel = {
        "086",
        "096",
        "097",
        "098",
        "032",
        "033",
        "034",
        "035",
        "036",
        "037",
        "038",
        "039",
    }
    vinaphone = {
        "088",
        "091",
        "094",
        "081",
        "082",
        "083",
        "084",
        "085",
    }
    mobifone = {
        "089",
        "090",
        "093",
        "070",
        "076",
        "077",
        "078",
        "079",
    }
    vietnamobile = {"092", "056", "058"}
    gmobile = {"099", "059"}
    itel = {"087"}

    if prefix3 in viettel:
        return "Viettel"
    if prefix3 in vinaphone:
        return "VinaPhone"
    if prefix3 in mobifone:
        return "MobiFone"
    if prefix3 in vietnamobile:
        return "Vietnamobile"
    if prefix3 in gmobile:
        return "Unknown"
    if prefix3 in itel:
        return "Unknown"
    return "Unknown"


def spintax_templates() -> Dict[str, str]:
    """Một vài mẫu Spintax có sẵn để người dùng chọn nhanh."""
    return {
        "Nhắc lịch": "{Chào|Xin chào|Kính chào} [Tên khách hàng], {nhắc bạn|thông báo} lịch hẹn vào ngày [Ngày hẹn]. {Vui lòng đến đúng giờ|Mong bạn sắp xếp thời gian}. Cảm ơn!",
        "Chúc mừng": "{Chào|Xin chào} [Tên khách hàng], {chúc bạn|gửi lời chúc bạn} {một ngày tốt lành|nhiều sức khỏe|luôn vui vẻ}. Trân trọng!",
        "Quảng cáo": "{Chào|Xin chào} [Tên khách hàng], {bên mình|cửa hàng} đang có {ưu đãi|khuyến mãi} {giảm giá|tặng quà} cho dịch vụ. {Quan tâm phản hồi tin nhắn này|Gọi ngay để được tư vấn}.",
    }


def simple_ai_rewrite_to_spintax(text: str) -> str:
    """
    "AI Rewrite" đơn giản (không dùng API): thay một số cụm từ bằng spintax đồng nghĩa.
    Mục tiêu: tạo biến thể nội dung để giảm trùng lặp.
    """
    if not text:
        return ""
    s = str(text)
    replacements = {
        r"\bChào\b": "{Chào|Xin chào|Kính chào}",
        r"\bXin chào\b": "{Chào|Xin chào|Kính chào}",
        r"\bthông báo\b": "{thông báo|nhắc bạn|gửi bạn}",
        r"\bnhắc\b": "{nhắc|thông báo|nhắn}",
        r"\bVui lòng\b": "{Vui lòng|Mong bạn|Phiền bạn}",
        r"\bCảm ơn\b": "{Cảm ơn|Xin cảm ơn|Trân trọng cảm ơn}",
    }
    for pattern, repl in replacements.items():
        s = re.sub(pattern, repl, s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s
