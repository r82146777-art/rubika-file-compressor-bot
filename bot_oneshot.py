#!/usr/bin/env python3
"""
ربات کاهش حجم خودکار روبیکا (GitHub Actions - هر ۵ دقیقه)
- بدون سؤال: هر فایل را به کمترین حجم ممکن فشرده می‌کند و همان‌جا برمی‌گرداند
- فایل‌های قبلاً پردازش‌شده را دوباره کار نمی‌کند
"""
import requests
import os
import json
import subprocess
import time
from pathlib import Path

TOKEN = os.environ.get("RUBIKA_TOKEN") or "CGFIFG0HKQPNRAIYNLROCQIPPCAEZQCHJIDXAUHNTEPRDDEQHNRSELACLTXJAMIN"
API = f"https://botapi.rubika.ir/v3/{TOKEN}"
OFFSET_FILE = "offset.txt"
PROCESSED_FILE = "processed_ids.json"
TEMP_DIR = Path("temp_files")
TEMP_DIR.mkdir(exist_ok=True)

# حداکثر حجم ورودی برای پردازش (مگابایت) - برای جلوگیری از timeout
MAX_INPUT_MB = 400

def api(method, data=None):
    url = f"{API}/{method}"
    try:
        r = requests.post(url, json=data or {}, timeout=60)
        print(f"API {method} http={r.status_code}")
        try:
            return r.json()
        except Exception:
            print(f"API raw: {r.text[:400]}")
            return None
    except Exception as e:
        print(f"API Error {method}: {e}")
        return None

def send_message(chat_id, text):
    res = api("sendMessage", {"chat_id": chat_id, "text": text})
    print(f"sendMessage: {res}")
    return res

def get_file(file_id):
    res = api("getFile", {"file_id": file_id})
    print(f"getFile: {str(res)[:300]}")
    if not res:
        return None
    data = res.get("data") if isinstance(res, dict) else None
    if isinstance(data, dict):
        for key in ("download_url", "downloadUrl", "url", "file_url", "link"):
            if data.get(key):
                return data[key]
    if isinstance(res, dict) and res.get("download_url"):
        return res["download_url"]
    return None

def download_file(url, save_path):
    try:
        print(f"Downloading...")
        with requests.get(url, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
        size = os.path.getsize(save_path)
        print(f"Downloaded size={size}")
        return True
    except Exception as e:
        print(f"Download error: {e}")
        return False

def request_send_file(file_type="File"):
    res = api("requestSendFile", {"type": file_type})
    if not res:
        return None
    data = res.get("data") if isinstance(res, dict) else {}
    if isinstance(data, dict):
        return data.get("upload_url")
    return None

def upload_file(upload_url, file_path, file_name):
    try:
        with open(file_path, "rb") as f:
            files = {"file": (file_name, f)}
            r = requests.post(upload_url, files=files, timeout=600)
            res = r.json()
            print(f"upload: {str(res)[:300]}")
            if isinstance(res, dict):
                data = res.get("data") or {}
                if isinstance(data, dict) and data.get("file_id"):
                    return data["file_id"]
                if res.get("file_id"):
                    return res["file_id"]
    except Exception as e:
        print(f"Upload error: {e}")
    return None

def send_file(chat_id, file_id, text=None):
    data = {"chat_id": chat_id, "file_id": file_id}
    if text:
        data["text"] = text
    return api("sendFile", data)

def get_file_size_mb(path):
    return os.path.getsize(path) / (1024 * 1024)

def detect_type(file_name):
    ext = Path(file_name).suffix.lower()
    if ext in [".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".m4v", ".3gp"]:
        return "video"
    if ext in [".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".opus"]:
        return "audio"
    if ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"]:
        return "image"
    if ext == ".pdf":
        return "pdf"
    return "other"

def compress_min(input_path, output_path, ftype):
    """فشرده‌سازی با کمترین حجم ممکن"""
    try:
        if ftype == "video":
            # CRF بالا = حجم کمتر
            cmd = [
                "ffmpeg", "-y", "-i", str(input_path),
                "-c:v", "libx264", "-crf", "32", "-preset", "veryfast",
                "-vf", "scale='min(1280,iw)':-2",
                "-c:a", "aac", "-b:a", "64k",
                "-movflags", "+faststart", str(output_path)
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900)
            return True
        if ftype == "audio":
            cmd = [
                "ffmpeg", "-y", "-i", str(input_path),
                "-c:a", "libmp3lame", "-b:a", "48k", str(output_path)
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
            return True
        if ftype == "image":
            out = str(output_path)
            if not out.lower().endswith((".jpg", ".jpeg")):
                out = str(Path(output_path).with_suffix(".jpg"))
                output_path = Path(out)
            cmd = [
                "ffmpeg", "-y", "-i", str(input_path),
                "-q:v", "12", str(output_path)
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
            return True
        if ftype == "pdf":
            cmd = [
                "gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
                "-dPDFSETTINGS=/screen", "-dNOPAUSE", "-dQUIET", "-dBATCH",
                f"-sOutputFile={output_path}", str(input_path)
            ]
            try:
                subprocess.run(cmd, check=True, timeout=300)
                return True
            except Exception:
                import shutil
                shutil.copy(input_path, output_path)
                return True
        # other -> zip
        import zipfile
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.write(input_path, arcname=os.path.basename(input_path))
        return True
    except Exception as e:
        print(f"compress error: {e}")
        return False

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return default

def save_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f)

def load_offset():
    if os.path.exists(OFFSET_FILE):
        with open(OFFSET_FILE) as f:
            v = f.read().strip()
            return v or None
    return None

def save_offset(offset):
    with open(OFFSET_FILE, "w") as f:
        f.write(str(offset))

def process_file_message(chat_id, msg, processed):
    file_info = msg.get("file") or msg.get("file_inline") or msg.get("document")
    if not file_info:
        return False

    message_id = str(msg.get("message_id") or "")
    file_id = file_info.get("file_id") or file_info.get("id")
    file_name = file_info.get("file_name") or file_info.get("name") or "file.bin"
    size_hint = file_info.get("size") or 0
    try:
        size_hint = int(size_hint)
    except Exception:
        size_hint = 0

    # جلوگیری از پردازش تکراری
    keys = []
    if message_id:
        keys.append(f"msg:{message_id}")
    if file_id:
        keys.append(f"file:{file_id}")

    for k in keys:
        if k in processed:
            print(f"SKIP already processed: {k}")
            return True  # handled (skip)

    if not file_id:
        send_message(chat_id, "❌ اطلاعات فایل پیدا نشد.")
        return True

    size_mb_hint = size_hint / (1024 * 1024) if size_hint else 0
    if size_mb_hint > MAX_INPUT_MB:
        send_message(chat_id, f"❌ فایل خیلی بزرگ است ({size_mb_hint:.0f} MB). حداکثر حدود {MAX_INPUT_MB} MB.")
        for k in keys:
            processed[k] = time.time()
        return True

    send_message(chat_id, "📥 فایل دریافت شد. در حال کاهش حجم به کمترین حالت ممکن...")

    download_url = get_file(file_id)
    if not download_url:
        send_message(chat_id, "❌ لینک دانلود پیدا نشد.")
        return True

    safe_name = "".join(c if c.isalnum() or c in ".-_" else "_" for c in file_name)[:80]
    local_path = TEMP_DIR / f"in_{int(time.time())}_{safe_name}"
    if not download_file(download_url, local_path):
        send_message(chat_id, "❌ دانلود ناموفق بود.")
        return True

    old_size = get_file_size_mb(local_path)
    ftype = detect_type(file_name)

    if ftype == "video":
        out_name = Path(safe_name).stem + "_min.mp4"
    elif ftype == "audio":
        out_name = Path(safe_name).stem + "_min.mp3"
    elif ftype == "image":
        out_name = Path(safe_name).stem + "_min.jpg"
    elif ftype == "pdf":
        out_name = Path(safe_name).stem + "_min.pdf"
    else:
        out_name = Path(safe_name).stem + "_min.zip"

    output_path = TEMP_DIR / out_name
    ok = compress_min(local_path, output_path, ftype)

    if not ok or not output_path.exists():
        send_message(chat_id, "❌ فشرده‌سازی ناموفق بود.")
        try:
            os.remove(local_path)
        except Exception:
            pass
        for k in keys:
            processed[k] = time.time()
        return True

    new_size = get_file_size_mb(output_path)
    upload_url = request_send_file("File")
    if not upload_url:
        send_message(chat_id, "❌ خطا در دریافت لینک آپلود.")
    else:
        new_file_id = upload_file(upload_url, output_path, out_name)
        if new_file_id:
            reduction = ((old_size - new_size) / max(old_size, 0.01)) * 100
            caption = (
                f"✅ فایل با کمترین حجم ممکن آماده شد\n\n"
                f"قبل: {old_size:.1f} MB\n"
                f"بعد: {new_size:.1f} MB\n"
                f"کاهش: {reduction:.0f}%"
            )
            send_file(chat_id, new_file_id, text=caption)
        else:
            send_message(chat_id, "❌ خطا در آپلود فایل فشرده.")

    # پاکسازی و ثبت به‌عنوان پردازش‌شده
    for p in (local_path, output_path):
        try:
            if p.exists():
                os.remove(p)
        except Exception:
            pass

    for k in keys:
        processed[k] = time.time()
    return True

def process_update(update, processed):
    try:
        msg = None
        chat_id = None

        if "new_message" in update:
            msg = update["new_message"]
            chat_id = update.get("chat_id") or (msg or {}).get("chat_id")
        elif update.get("type") == "NewMessage":
            msg = update.get("new_message")
            chat_id = update.get("chat_id")

        if not msg or not chat_id:
            return

        message_id = str(msg.get("message_id") or "")
        if message_id and f"msg:{message_id}" in processed:
            print(f"SKIP msg already done: {message_id}")
            return

        text = (msg.get("text") or "").strip()

        # /start
        if text in ("/start", "شروع", "start"):
            send_message(
                chat_id,
                "سلام 👋\n"
                "هر فایل (ویدیو، صوت، تصویر، PDF و ...) را بفرست.\n"
                "من خودکار به کمترین حجم ممکن کاهش می‌دهم و برمی‌گردانم.\n"
                "بدون سؤال و بدون انتخاب.\n\n"
                "⚠️ پاسخ‌دهی حدود هر ۵ دقیقه یک‌بار است."
            )
            if message_id:
                processed[f"msg:{message_id}"] = time.time()
            return

        # فایل → فشرده‌سازی خودکار
        file_info = msg.get("file") or msg.get("file_inline") or msg.get("document")
        if file_info:
            process_file_message(chat_id, msg, processed)
            return

        # دکمه یا متن اضافی را نادیده بگیر (دیگر سؤال نمی‌پرسیم)
        aux = msg.get("aux_data") or {}
        if isinstance(aux, dict) and aux.get("button_id"):
            print(f"Ignore button_id={aux.get('button_id')} (auto mode)")
            if message_id:
                processed[f"msg:{message_id}"] = time.time()
            return

        if text:
            # فقط یک بار راهنما، نه برای هر متن
            print(f"Ignore text: {text[:40]!r}")
            if message_id:
                processed[f"msg:{message_id}"] = time.time()

    except Exception as e:
        print(f"Process error: {e}")
        import traceback
        traceback.print_exc()

def main():
    print("🤖 Auto-compress bot started...")
    offset = load_offset()
    processed = load_json(PROCESSED_FILE, {})
    # پاکسازی شناسه‌های قدیمی‌تر از ۷ روز
    now = time.time()
    processed = {k: v for k, v in processed.items() if isinstance(v, (int, float)) and now - v < 7 * 86400}
    print(f"offset={offset!r} processed_count={len(processed)}")

    data = {"limit": 50}
    if offset:
        data["offset_id"] = offset

    res = api("getUpdates", data)
    if not res:
        print("No getUpdates response")
        return

    updates = []
    if isinstance(res, dict) and res.get("status") == "OK":
        data_part = res.get("data") or {}
        updates = data_part.get("updates") or []
        if isinstance(updates, dict):
            updates = [updates]

    print(f"Received {len(updates)} updates")

    for upd in updates:
        process_update(upd, processed)
        if isinstance(upd, dict):
            new_offset = (
                (upd.get("new_message") or {}).get("message_id")
                or upd.get("message_id")
                or upd.get("update_id")
                or upd.get("update_time")
            )
            if new_offset:
                offset = str(new_offset)

    if offset:
        save_offset(offset)
        print(f"Saved offset={offset}")
    save_json(PROCESSED_FILE, processed)
    print("Done.")

if __name__ == "__main__":
    main()
