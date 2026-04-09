# Local SMS Reminder App (Python + Streamlit)

Ứng dụng cục bộ để gửi tin nhắn nhắc lịch hàng loạt qua Android SMS Gateway.

## 1) Công nghệ sử dụng

- Python 3
- Streamlit (UI local web app)
- Pandas (đọc Excel/CSV)
- SQLite (lưu cấu hình + lịch sử gửi)

## 2) Cấu trúc dự án

```text
sms auto/
├─ app.py            # Streamlit UI + luồng gửi
├─ database.py       # SQLite init/settings/logs
├─ gateway.py        # Kết nối + gửi SMS qua API gateway
├─ utils.py          # Spintax + variable engine + detect cột
├─ requirements.txt
└─ README.md
```

## 3) Cài đặt và chạy

### Bước 1: Tạo môi trường ảo (khuyến nghị)

Trên Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Bước 2: Cài thư viện

```powershell
pip install -r requirements.txt
```

### Bước 3: Chạy ứng dụng

```powershell
streamlit run app.py
```

Mặc định Streamlit mở ở: `http://localhost:8501`

## 4) Hướng dẫn sử dụng (Dashboard 1 màn hình)

Giao diện hiện tại dùng bố cục 2 cột:

- **Cột trái (Dữ liệu):**
  - Tải file `.xlsx`/`.csv`
  - Chỉnh trực tiếp dữ liệu bằng `data_editor`
  - Cột `[x] Chọn gửi` để chọn dòng gửi
  - Nút thao tác nhanh: chuẩn hóa SĐT, lọc trùng, chọn/bỏ chọn tất cả, xóa file
  - Mapping cột SĐT/Tên/Ngày hẹn

- **Cột phải (Điều khiển & Gửi):**
  - `expander` cấu hình API + delay + giới hạn gửi
  - Soạn template Spintax và danh sách biến khả dụng từ tên cột import
  - Live preview (nội dung thực tế + số ký tự + số phần SMS)
  - Nút gửi chính với progress và trạng thái realtime

- **Khối dưới cùng (Logs & Retry):**
  - `expander` lịch sử gửi gần nhất
  - Xuất danh sách thất bại ra CSV
  - Retry toàn bộ bản ghi thất bại với progress riêng

Thông tin cấu hình và lịch sử được lưu vào SQLite (`app_data.db`) nên mở lại app không mất dữ liệu.

## 5) Lưu ý tương thích API Gateway

`gateway.py` đang dùng đúng chuẩn Local Server của `capcom6/android-sms-gateway`:

- Endpoint: `POST <Gateway URL>/message`
- Auth: Basic Auth (`Username` + `Password`)
- Payload:
  - `message`: nội dung tin sau khi render Spintax/biến
  - `phoneNumbers`: mảng số điện thoại
