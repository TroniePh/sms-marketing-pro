import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


DB_PATH = Path("app_data.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    # Khởi tạo schema tối thiểu cho settings và lịch sử gửi tin.
    with closing(get_connection()) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS message_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL,
                customer_name TEXT,
                appointment_date TEXT,
                message TEXT NOT NULL,
                status TEXT NOT NULL,
                response TEXT,
                sent_at TEXT NOT NULL
            )
            """
        )
        # Gateways (multi-device): migrate an toàn nếu DB cũ đã có bảng gateways khác schema.
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gateways'")
        has_gateways = cur.fetchone() is not None
        if not has_gateways:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS gateways (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    carrier_name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    username TEXT NOT NULL,
                    password TEXT NOT NULL,
                    is_default INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        else:
            cur.execute("PRAGMA table_info(gateways)")
            gw_cols = {row[1] for row in cur.fetchall()}
            expected = {"id", "carrier_name", "url", "username", "password", "is_default"}
            if not expected.issubset(gw_cols):
                # Tạo bảng mới đúng schema và copy dữ liệu phù hợp.
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS gateways_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        carrier_name TEXT NOT NULL,
                        url TEXT NOT NULL,
                        username TEXT NOT NULL,
                        password TEXT NOT NULL,
                        is_default INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                # Nếu bảng cũ dùng cột 'name' thì map sang carrier_name.
                if "name" in gw_cols:
                    cur.execute(
                        """
                        INSERT INTO gateways_new(carrier_name, url, username, password, is_default)
                        SELECT COALESCE(NULLIF(name, ''), 'Default'),
                               url,
                               COALESCE(username, ''),
                               COALESCE(password, ''),
                               0
                        FROM gateways
                        """
                    )
                else:
                    # Trường hợp khác: cố gắng copy tối thiểu, fallback carrier_name=Default.
                    cur.execute(
                        """
                        INSERT INTO gateways_new(carrier_name, url, username, password, is_default)
                        SELECT 'Default',
                               COALESCE(url, ''),
                               COALESCE(username, ''),
                               COALESCE(password, ''),
                               0
                        FROM gateways
                        """
                    )

                # Đảm bảo có đúng 1 default sau migrate: chọn row đầu tiên làm default nếu chưa có.
                cur.execute("SELECT id FROM gateways_new ORDER BY id ASC LIMIT 1")
                first_row = cur.fetchone()
                if first_row is not None:
                    cur.execute(
                        "UPDATE gateways_new SET is_default = 1 WHERE id = ?",
                        (int(first_row[0]),),
                    )

                cur.execute("DROP TABLE gateways")
                cur.execute("ALTER TABLE gateways_new RENAME TO gateways")

        # Bổ sung cột mới cho message_logs nếu cần (tương thích DB cũ).
        cur.execute("PRAGMA table_info(message_logs)")
        existing_cols = {row[1] for row in cur.fetchall()}
        if "carrier" not in existing_cols:
            cur.execute("ALTER TABLE message_logs ADD COLUMN carrier TEXT")
        if "gateway_name" not in existing_cols:
            cur.execute("ALTER TABLE message_logs ADD COLUMN gateway_name TEXT")
        if "route_type" not in existing_cols:
            cur.execute("ALTER TABLE message_logs ADD COLUMN route_type TEXT")
        if "cost_vnd" not in existing_cols:
            cur.execute("ALTER TABLE message_logs ADD COLUMN cost_vnd INTEGER")

        conn.commit()


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with closing(get_connection()) as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default


def get_setting_int(key: str, default: int) -> int:
    # Đọc setting dạng số nguyên an toàn, fallback khi dữ liệu lỗi.
    value = get_setting(key, str(default))
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def set_setting(key: str, value: str) -> None:
    with closing(get_connection()) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO settings(key, value)
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        conn.commit()


def save_log(
    phone: str,
    customer_name: Optional[str],
    appointment_date: Optional[str],
    message: str,
    status: str,
    response: Optional[str],
    carrier: Optional[str] = None,
    gateway_name: Optional[str] = None,
    route_type: Optional[str] = None,
    cost_vnd: Optional[int] = None,
) -> None:
    # Lưu một bản ghi gửi tin (thành công hoặc thất bại).
    with closing(get_connection()) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO message_logs(
                phone, customer_name, appointment_date, message, status, response, carrier, gateway_name, route_type, cost_vnd, sent_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                phone,
                customer_name,
                appointment_date,
                message,
                status,
                response,
                carrier,
                gateway_name,
                route_type,
                cost_vnd,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()


def get_logs(limit: int = 1000) -> List[Dict[str, Any]]:
    with closing(get_connection()) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, phone, customer_name, appointment_date, message, status, response,
                   carrier, gateway_name, route_type, cost_vnd, sent_at
            FROM message_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def get_failed_logs(limit: int = 5000) -> List[Dict[str, Any]]:
    with closing(get_connection()) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, phone, customer_name, appointment_date, message, status, response,
                   carrier, gateway_name, route_type, cost_vnd, sent_at
            FROM message_logs
            WHERE UPPER(status) = 'FAILED'
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def get_success_phones_today() -> List[str]:
    """
    Lấy danh sách số điện thoại đã gửi THÀNH CÔNG trong ngày hôm nay (theo local time của SQLite).
    Dùng cho cơ chế skip trùng khi gửi lại.
    """
    with closing(get_connection()) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT phone
            FROM message_logs
            WHERE UPPER(status) = 'SUCCESS'
              AND substr(sent_at, 1, 10) = date('now')
            ORDER BY phone ASC
            """
        )
        rows = cur.fetchall()
        return [str(r[0]) for r in rows if r[0] is not None]


def update_log_after_retry(
    log_id: int,
    status: str,
    response: Optional[str],
    message: Optional[str] = None,
    carrier: Optional[str] = None,
    gateway_name: Optional[str] = None,
    route_type: Optional[str] = None,
    cost_vnd: Optional[int] = None,
) -> None:
    # Cập nhật lại cùng một bản ghi sau khi retry để tránh trùng thống kê.
    with closing(get_connection()) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE message_logs
            SET message = COALESCE(?, message),
                status = ?,
                response = ?,
                carrier = COALESCE(?, carrier),
                gateway_name = COALESCE(?, gateway_name),
                route_type = COALESCE(?, route_type),
                cost_vnd = COALESCE(?, cost_vnd),
                sent_at = ?
            WHERE id = ?
            """,
            (
                message,
                status,
                response,
                carrier,
                gateway_name,
                route_type,
                cost_vnd,
                datetime.now().isoformat(timespec="seconds"),
                log_id,
            ),
        )
        conn.commit()


def get_gateways() -> List[Dict[str, Any]]:
    with closing(get_connection()) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, carrier_name, url, username, password, is_default FROM gateways ORDER BY id ASC"
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def upsert_gateway(
    gateway_id: Optional[int],
    carrier_name: str,
    url: str,
    username: str,
    password: str,
    is_default: int = 0,
) -> int:
    with closing(get_connection()) as conn:
        cur = conn.cursor()
        if gateway_id:
            cur.execute(
                """
                UPDATE gateways
                SET carrier_name = ?, url = ?, username = ?, password = ?, is_default = ?
                WHERE id = ?
                """,
                (carrier_name, url, username, password, int(is_default), gateway_id),
            )
            if int(is_default) == 1:
                cur.execute("UPDATE gateways SET is_default = 0 WHERE id <> ?", (gateway_id,))
            conn.commit()
            return int(gateway_id)
        cur.execute(
            """
            INSERT INTO gateways(carrier_name, url, username, password, is_default)
            VALUES(?, ?, ?, ?, ?)
            """,
            (carrier_name, url, username, password, int(is_default)),
        )
        new_id = int(cur.lastrowid)
        if int(is_default) == 1:
            cur.execute("UPDATE gateways SET is_default = 0 WHERE id <> ?", (new_id,))
        conn.commit()
        return new_id


def delete_gateway(gateway_id: int) -> None:
    with closing(get_connection()) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM gateways WHERE id = ?", (gateway_id,))
        # Đảm bảo luôn có đúng 1 default nếu còn gateway.
        cur.execute("SELECT id FROM gateways WHERE is_default = 1 LIMIT 1")
        has_default = cur.fetchone() is not None
        if not has_default:
            cur.execute("SELECT id FROM gateways ORDER BY id ASC LIMIT 1")
            row = cur.fetchone()
            if row is not None:
                cur.execute("UPDATE gateways SET is_default = 1 WHERE id = ?", (int(row[0]),))
        conn.commit()


def ensure_single_default_gateway() -> None:
    """Đảm bảo có đúng 1 gateway default (phục vụ validate sau các thao tác)."""
    with closing(get_connection()) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM gateways WHERE is_default = 1 ORDER BY id ASC")
        rows = [int(r[0]) for r in cur.fetchall()]
        if len(rows) == 0:
            cur.execute("SELECT id FROM gateways ORDER BY id ASC LIMIT 1")
            row = cur.fetchone()
            if row is not None:
                cur.execute("UPDATE gateways SET is_default = 1 WHERE id = ?", (int(row[0]),))
        elif len(rows) > 1:
            keep = rows[0]
            cur.execute("UPDATE gateways SET is_default = 0 WHERE id <> ?", (keep,))
        conn.commit()


def replace_gateways(gateways: List[Dict[str, Any]]) -> None:
    """
    Ghi đè toàn bộ danh sách gateways.
    Dùng cho data_editor (add/edit/delete) để đồng bộ 1 lần.
    """
    with closing(get_connection()) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM gateways")
        for row in gateways:
            cur.execute(
                """
                INSERT INTO gateways(carrier_name, url, username, password, is_default)
                VALUES(?, ?, ?, ?, ?)
                """,
                (
                    str(row.get("carrier_name") or "Default"),
                    str(row.get("url") or ""),
                    str(row.get("username") or ""),
                    str(row.get("password") or ""),
                    1 if bool(row.get("is_default")) else 0,
                ),
            )
        conn.commit()
