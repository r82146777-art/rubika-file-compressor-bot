#!/usr/bin/env python3
"""
ربات کاهش حجم خودکار روبیکا (GitHub Actions)
- بدون offset خراب (همیشه getUpdates بدون offset)
- فقط بعد از پردازش واقعی علامت می‌زند
- کیفیت متعادل حدود ۳۰–۴۵ مگ
"""
import requests
import os
import json
import subprocess
import time
import mimetypes
from pathlib import Path

TOKEN = os.environ.get("RUBIKA_TOKEN") or "CGFIFG0HKQPNRAIYNLROCQIPPCAEZQCHJIDXAUHNTEPRDDEQHNRSELACLTXJAMIN"
API = f"https://botapi.rubika.ir/v3/{TOKEN}"
PROCESSED_FILE = "processed_ids.json"
TEMP_DIR = Path("temp_files")
TEMP_DIR.mkdir(exist_ok=True)

MAX_UPLOAD_MB = 45
MAX_INPUT_MB = 600
MAX_FILES_PER_RUN = 1

def api(method, data=None):
    url = f"{API}/{method}"
    try:
        r = requests.post(url, json=data or {}, timeout=90)
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
    print(f"getFile: {str(res)[:250]}")
    if not res:
        return None
    data = res.get("data") if isinstance(res, dict) else None
    if isinstance(data, dict):
        for key in ("download_url", "downloadUrl", "url", "file_url", "link"):
            if data.get(key):
                return data[key]
    return None

def download_file(url, save_path):
    try:
        print("Downloading...")
        with requests.get(url, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
        print(f"Downloaded size={os.path.getsize(save_path)}")
        return True
    except Exception as e:
        print(f"Download error: {e}")
        return False

def request_send_file(file_type="File"):
    res = api("requestSendFile", {"type": file_type})
    print(f"requestSendFile({file_type}): {res}")
    if not res:
        return None
    data = res.get("data") if isinstance(res, dict) else {}
    if isinstance(data, dict):
        return data.get("upload_url")
    return None

def upload_file(upload_url, file_path, file_name):
    try:
        size = os.path.getsize(file_path)
        print(f"Uploading {file_name} size={size} bytes...")
        mime = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        with open(file_path, "rb") as f:
            files = {"file": (file_name, f, mime)}
            r = requests.post(upload_url, files=files, timeout=600)
        print(f"upload http={r.status_code} body={r.text[:400]}")
        try:
            res = r.json()
        except Exception:
            return None
        if isinstance(res, dict):
            data = res.get("data") or {}
            if isinstance(data, dict) and data.get("file_id"):
                return data["file_id"]
            if res.get("file_id"):
                return res["file_id"]
        return None
    except Exception as e:
        print(f"Upload error: {e}")
        return None

def send_file(chat_id, file_id, text=None):
    data = {"chat_id": chat_id, "file_id": file_id}
    if text:
        data["text"] = text
    res = api("sendFile", data)
    print(f"sendFile: {res}")
    return res

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

def rubika_upload_type(ftype):
    return {"video": "Video", "audio": "Music", "image": "Image"}.get(ftype, "File")

def run_ffmpeg(cmd, timeout=1200):
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
        return True
    except Exception as e:
        print(f"ffmpeg failed: {e}")
        return False

def compress_balanced(input_path, output_path, ftype):
    if ftype == "video":
        attempts = [
            ("min(1280,iw)", "28"),
            ("min(854,iw)", "32"),
            ("min(640,iw)", "36"),
        ]
        for scale, crf in attempts:
            cmd = [
                "ffmpeg", "-y", "-i", str(input_path),
                "-c:v", "libx264", "-crf", crf, "-preset", "veryfast",
                "-vf", f"scale='{scale}':-2",
                "-c:a", "aac", "-b:a", "96k",
                "-movflags", "+faststart", str(output_path),
            ]
            if run_ffmpeg(cmd) and output_path.exists():
                mb = get_file_size_mb(output_path)
                print(f"video attempt scale={scale} crf={crf} -> {mb:.1f} MB")
                if mb <= MAX_UPLOAD_MB:
                    return True
        return output_path.exists() and get_file_size_mb(output_path) <= MAX_UPLOAD_MB

    if ftype == "audio":
        for br in ("128k", "96k", "64k"):
            cmd = ["ffmpeg", "-y", "-i", str(input_path), "-c:a", "libmp3lame", "-b:a", br, str(output_path)]
            if run_ffmpeg(cmd, timeout=300) and output_path.exists():
                print(f"audio {br} -> {get_file_size_mb(output_path):.1f} MB")
                if get_file_size_mb(output_path) <= MAX_UPLOAD_MB:
                    return True
        return output_path.exists()

    if ftype == "image":
        out = output_path if str(output_path).lower().endswith((".jpg", ".jpeg")) else Path(str(output_path) + ".jpg")
        for q in ("5", "8", "12"):
            cmd = ["ffmpeg", "-y", "-i", str(input_path), "-q:v", q, str(out)]
            if run_ffmpeg(cmd, timeout=120) and out.exists():
                if out != output_path:
                    out.replace(output_path)
                print(f"image q={q} -> {get_file_size_mb(output_path):.1f} MB")
                if get_file_size_mb(output_path) <= MAX_UPLOAD_MB:
                    return True
        return output_path.exists()

    if ftype == "pdf":
        cmd = [
            "gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
            "-dPDFSETTINGS=/ebook", "-dNOPAUSE", "-dQUIET", "-dBATCH",
            f"-sOutputFile={output_path}", str(input_path),
        ]
        try:
            subprocess.run(cmd, check=True, timeout=300)
            return output_path.exists()
        except Exception:
            import shutil
            shutil.copy(input_path, output_path)
            return True

    import zipfile
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(input_path, arcname=os.path.basename(input_path))
    return output_path.exists()

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

def mark_processed(processed, message_id=None, file_id=None):
    now = time.time()
    if message_id:
        processed[f"msg:{message_id}"] = now
    if file_id:
        processed[f"file:{file_id}"] = now

def is_processed(processed, message_id=None, file_id=None):
    if message_id and f"msg:{message_id}" in processed:
        return True
    if file_id and f"file:{file_id}" in processed:
        return True
    return False

def is_from_bot(msg):
    return (msg.get("sender_type") or "").lower() == "bot"

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

    if is_processed(processed, message_id, file_id):
        print(f"SKIP already processed msg={message_id} file={file_id}")
        return True

    if not file_id:
        send_message(chat_id, "❌ اطلاعات فایل پیدا نشد.")
        mark_processed(processed, message_id)
        return True

    size_mb_hint = size_hint / (1024 * 1024) if size_hint else 0
    if size_mb_hint > MAX_INPUT_MB:
        send_message(chat_id, f"❌ فایل خیلی بزرگ است ({size_mb_hint:.0f} MB).")
        mark_processed(processed, message_id, file_id)
        return True

    send_message(chat_id, "📥 فایل دریافت شد.\nدر حال کاهش حجم...")

    download_url = get_file(file_id)
    if not download_url:
        send_message(chat_id, "❌ لینک دانلود پیدا نشد.")
        mark_processed(processed, message_id, file_id)
        return True

    safe_name = "".join(c if c.isalnum() or c in ".-_" else "_" for c in file_name)[:80]
    local_path = TEMP_DIR / f"in_{int(time.time())}_{safe_name}"
    if not download_file(download_url, local_path):
        send_message(chat_id, "❌ دانلود ناموفق بود.")
        mark_processed(processed, message_id, file_id)
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
    ok = compress_balanced(local_path, output_path, ftype)

    if not ok or not output_path.exists():
        send_message(chat_id, "❌ فشرده‌سازی ناموفق بود.")
        try:
            os.remove(local_path)
        except Exception:
            pass
        mark_processed(processed, message_id, file_id)
        return True

    new_size = get_file_size_mb(output_path)
    print(f"Final size: {new_size:.2f} MB")

    if new_size > MAX_UPLOAD_MB:
        send_message(chat_id, f"❌ بعد از فشرده‌سازی هنوز {new_size:.1f} MB است (سقف حدود ۵۰MB).")
        for p in (local_path, output_path):
            try:
                if p.exists():
                    os.remove(p)
            except Exception:
                pass
        mark_processed(processed, message_id, file_id)
        return True

    upload_type = rubika_upload_type(ftype)
    upload_url = request_send_file(upload_type) or request_send_file("File")

    if not upload_url:
        send_message(chat_id, "❌ خطا در لینک آپلود.")
    else:
        new_file_id = upload_file(upload_url, output_path, out_name)
        if not new_file_id and upload_type != "File":
            url2 = request_send_file("File")
            if url2:
                new_file_id = upload_file(url2, output_path, out_name)

        if new_file_id:
            reduction = ((old_size - new_size) / max(old_size, 0.01)) * 100
            caption = (
                f"✅ فایل کم‌حجم شد\n\n"
                f"قبل: {old_size:.1f} MB\n"
                f"بعد: {new_size:.1f} MB\n"
                f"کاهش: {reduction:.0f}%"
            )
            send_file(chat_id, new_file_id, text=caption)
            mark_processed(processed, file_id=new_file_id)
        else:
            send_message(chat_id, f"❌ خطا در آپلود ({new_size:.1f} MB).")

    for p in (local_path, output_path):
        try:
            if p.exists():
                os.remove(p)
        except Exception:
            pass

    mark_processed(processed, message_id, file_id)
    return True

def process_non_file(update, processed):
    msg = update.get("new_message")
    chat_id = update.get("chat_id")
    if not msg or not chat_id:
        return
    if is_from_bot(msg):
        mid = str(msg.get("message_id") or "")
        if mid:
            mark_processed(processed, mid)
        return
    message_id = str(msg.get("message_id") or "")
    if message_id and f"msg:{message_id}" in processed:
        return
    text = (msg.get("text") or "").strip()
    if text in ("/start", "شروع", "start"):
        send_message(
            chat_id,
            "سلام 👋\n"
            "فایل بفرست؛ یک‌بار حجمش را کم می‌کنم و برمی‌گردانم.\n"
            "⚠️ ممکن است چند دقیقه تا یک ساعت طول بکشد (محدودیت گیت‌هاب)."
        )
    if message_id:
        mark_processed(processed, message_id)

def main():
    print("🤖 Auto-compress bot started...")
    processed = load_json(PROCESSED_FILE, {})
    now = time.time()
    processed = {k: v for k, v in processed.items() if isinstance(v, (int, float)) and now - v < 30 * 86400}
    print(f"processed_count={len(processed)}")

    # هرگز از offset استفاده نکن — باعث صفر شدن آپدیت‌های جدید می‌شد
    res = api("getUpdates", {"limit": 100})
    updates = []
    if isinstance(res, dict) and res.get("status") == "OK":
        data_part = res.get("data") or {}
        updates = data_part.get("updates") or []
        if isinstance(updates, dict):
            updates = [updates]
    print(f"Received {len(updates)} updates")

    # یکتا بر اساس message_id
    seen = set()
    unique = []
    for u in updates:
        if not isinstance(u, dict):
            continue
        mid = str((u.get("new_message") or {}).get("message_id") or u.get("update_time") or id(u))
        if mid in seen:
            continue
        seen.add(mid)
        unique.append(u)
    updates = unique
    print(f"Unique updates: {len(updates)}")

    for upd in updates:
        nm = upd.get("new_message") or {}
        has_file = bool(nm.get("file") or nm.get("file_inline") or nm.get("document"))
        if not has_file:
            process_non_file(upd, processed)

    # فایل‌های کاربر (نه ربات)، مرتب از جدید به قدیم
    file_items = []
    for upd in updates:
        msg = upd.get("new_message")
        chat_id = upd.get("chat_id")
        if not msg or not chat_id:
            continue
        if is_from_bot(msg):
            mid = str(msg.get("message_id") or "")
            mark_processed(processed, mid)
            continue
        finfo = msg.get("file") or msg.get("file_inline") or msg.get("document")
        if not finfo:
            continue
        mid = str(msg.get("message_id") or "")
        fid = finfo.get("file_id") or finfo.get("id")
        ut = upd.get("update_time") or msg.get("time") or 0
        try:
            ut = int(ut)
        except Exception:
            ut = 0
        file_items.append((ut, mid, chat_id, msg, fid))

    file_items.sort(key=lambda x: (x[0], x[1]), reverse=True)  # جدیدترین اول
    print(f"User file messages: {len(file_items)}")

    pending = []
    for ut, mid, chat_id, msg, fid in file_items:
        if is_processed(processed, mid, fid):
            print(f"SKIP old msg={mid} file={fid}")
            continue
        pending.append((ut, mid, chat_id, msg, fid))

    print(f"Pending new files: {len(pending)}")

    # فقط جدیدترین را پردازش کن؛ بقیه را برای دور بعد نگه دار (علامت نزن)
    for ut, mid, chat_id, msg, fid in pending[:MAX_FILES_PER_RUN]:
        print(f"Processing msg={mid} file={fid}")
        process_file_message(chat_id, msg, processed)

    save_json(PROCESSED_FILE, processed)
    print(f"processed_count now={len(processed)}")
    print("Done.")

if __name__ == "__main__":
    main()
