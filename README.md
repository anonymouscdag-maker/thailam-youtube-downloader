# Thái Lâm YouTube Downloader Worker

Backend worker cho website downloader chạy trên Render Free.

## Deploy bằng Render Blueprint

1. Trong Render chọn **New → Blueprint**.
2. Kết nối repository này.
3. Render đọc `render.yaml` và tạo Docker Web Service.
4. Khi Render hỏi `API_KEY`, nhập API key của website cPanel.
5. Chờ deploy xong rồi kiểm tra endpoint `/v1/health` từ website.

`DOWNLOAD_SECRET` được Render tự tạo, không commit secret vào GitHub.

> Chỉ tải nội dung bạn sở hữu hoặc có quyền tải/sử dụng.
