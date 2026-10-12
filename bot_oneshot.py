#!/usr/bin/env python3
"""
ربات کاهش حجم خودکار روبیکا (GitHub Actions)
- بدون سؤال: هر فایل را به کمترین حجم ممکن (زیر سقف ۵۰MB روبیکا) فشرده می‌کند
- فایل‌های تکراری را دوباره پردازش نمی‌کند
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
OFFSET_FILE = "offset.txt"
PROCESSED_FILE = "processed_ids.json"
TEMP_DIR = Path("temp_files")
TEMP_DIR.mkdir(exist_ok=True)

# سقف آپلود روبیکا برای File/Video حدود ۵۰MB است
MAX_UPLOAD_MB = 45
MAX_INPUT_MB = 500

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
    # type: File | Image | Voice | Video | Music | Gif
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
        print(f"Uploading {file_name} size={size} bytes to {upload_url[:80]}...")
        mime = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        with open(file_path, "rb") as f:
            files = {"file": (file_name, f, mime)}
            r = requests.post(upload_url, files=files, timeout=600)
        print(f"upload http={r.status_code} body={r.text[:500]}")
        try:
            res = r.json()
        except Exception:
            print(f"upload non-json: {r.text[:300]}")
            return None
        if isinstance(res, dict):
            if res.get("status") == "OK":
                data = res.get("data") or {}
                if isinstance(data, dict) and data.get("file_id"):
                    return data["file_id"]
            # بعضی پاسخ‌ها مستقیم file_id دارند
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
    return {
        "video": "Video",
        "audio": "Music",
        "image": "Image",
        "pdf": "File",
        "other": "File",
    }.get(ftype, "File")

def run_ffmpeg(cmd, timeout=900):
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
        return True
    except Exception as e:
        print(f"ffmpeg failed: {e}")
        return False

def compress_under_limit(input_path, output_path, ftype):
    """فشرده تا زیر MAX_UPLOAD_MB با چند مرحله تهاجمی‌تر"""
    attempts = []

    if ftype == "video":
        attempts = [
            # (scale, crf, audio_bitrate)
            ("min(1280,iw)", "28", "96k"),
            ("min(854,iw)", "32", "64k"),
            ("min(640,iw)", "36", "48k"),
            ("min(480,iw)", "40", "32k"),
        ]
        for scale, crf, abr in attempts:
            cmd = [
                "ffmpeg", "-y", "-i", str(input_path),
                "-c:v", "libx264", "-crf", crf, "-preset", "veryfast",
                "-vf", f"scale='{scale}':-2",
                "-c:a", "aac", "-b:a", abr,
                "-movflags", "+faststart", str(output_path),
            ]
            if run_ffmpeg(cmd) and output_path.exists():
                mb = get_file_size_mb(output_path)
                print(f"video attempt scale={scale} crf={crf} -> {mb:.1f} MB")
                if mb <= MAX_UPLOAD_MB:
                    return True
        return output_path.exists() and get_file_size_mb(output_path) <= MAX_UPLOAD_MB

    if ftype == "audio":
        for br in ("96k", "64k", "48k", "32k"):
            cmd = ["ffmpeg", "-y", "-i", str(input_path), "-c:a", "libmp3lame", "-b:a", br, str(output_path)]
            if run_ffmpeg(cmd, timeout=300) and output_path.exists():
                mb = get_file_size_mb(output_path)
                print(f"audio attempt {br} -> {mb:.1f} MB")
                if mb <= MAX_UPLOAD_MB:
                    return True
        return output_path.exists() and get_file_size_mb(output_path) <= MAX_UPLOAD_MB

    if ftype == "image":
        out = output_path if str(output_path).lower().endswith((".jpg", ".jpeg")) else Path(str(output_path) + ".jpg")
        for q in ("8", "12", "18", "25"):
            cmd = ["ffmpeg", "-y", "-i", str(input_path), "-q:v", q, str(out)]
            if run_ffmpeg(cmd, timeout=120) and out.exists():
                mb = get_file_size_mb(out)
                print(f"image attempt q={q} -> {mb:.1f} MB")
                if mb <= MAX_UPLOAD_MB:
                    if out != output_path:
                        out.replace(output_path)
                    return True
        if out.exists() and out != output_path:
            out.replace(output_path)
        return output_path.exists()

    if ftype == "pdf":
        cmd = [
            "gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
            "-dPDFSETTINGS=/screen", "-dNOPAUSE", "-dQUIET", "-dBATCH",
            f"-sOutputFile={output_path}", str(input_path),
        ]
        try:
            subprocess.run(cmd, check=True, timeout=300)
            return output_path.exists()
        except Exception:
            import shutil
            shutil.copy(input_path, output_path)
            return True

    # other -> zip
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

    keys = []
    if message_id:
        keys.append(f"msg:{message_id}")
    if file_id:
        keys.append(f"file:{file_id}")

    for k in keys:
        if k in processed:
            print(f"SKIP already processed: {k}")
            return True

    if not file_id:
        send_message(chat_id, "❌ اطلاعات فایل پیدا نشد.")
        return True

    size_mb_hint = size_hint / (1024 * 1024) if size_hint else 0
    if size_mb_hint > MAX_INPUT_MB:
        send_message(chat_id, f"❌ فایل خیلی بزرگ است ({size_mb_hint:.0f} MB).")
        for k in keys:
            processed[k] = time.time()
        return True

    send_message(chat_id, "📥 فایل دریافت شد.\nدر حال کاهش حجم به زیر ۵۰ مگابایت...")

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
    ok = compress_under_limit(local_path, output_path, ftype)

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
    print(f"Final size: {new_size:.2f} MB (limit {MAX_UPLOAD_MB})")

    if new_size > MAX_UPLOAD_MB:
        send_message(
            chat_id,
            f"❌ بعد از فشرده‌سازی هنوز حجم زیاد است ({new_size:.1f} MB).\n"
            f"سقف ارسال روبیکا حدود ۵۰ MB است. لطفاً فایل کوتاه‌تر بفرست."
        )
        for p in (local_path, output_path):
            try:
                if p.exists():
                    os.remove(p)
            except Exception:
                pass
        for k in keys:
            processed[k] = time.time()
        return True

    upload_type = rubika_upload_type(ftype)
    upload_url = request_send_file(upload_type)
    if not upload_url:
        # fallback
        upload_url = request_send_file("File")

    if not upload_url:
        send_message(chat_id, "❌ خطا در دریافت لینک آپلود از روبیکا.")
    else:
        new_file_id = upload_file(upload_url, output_path, out_name)
        if not new_file_id and upload_type != "File":
            # یک‌بار دیگر با نوع File
            upload_url2 = request_send_file("File")
            if upload_url2:
                new_file_id = upload_file(upload_url2, output_path, out_name)

        if new_file_id:
            reduction = ((old_size - new_size) / max(old_size, 0.01)) * 100
            caption = (
                f"✅ فایل کم‌حجم شد\n\n"
                f"قبل: {old_size:.1f} MB\n"
                f"بعد: {new_size:.1f} MB\n"
                f"کاهش: {reduction:.0f}%"
            )
            send_file(chat_id, new_file_id, text=caption)
        else:
            send_message(
                chat_id,
                f"❌ خطا در آپلود فایل فشرده ({new_size:.1f} MB).\n"
                f"ممکن است سرور روبیکا موقتاً مشکل داشته باشد. دوباره فایل را بفرست."
            )

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

        if text in ("/start", "شروع", "start"):
            send_message(
                chat_id,
                "سلام 👋\n"
                "هر فایل را بفرست؛ خودکار به کمترین حجم ممکن (زیر ۵۰ مگ) کم می‌کنم و برمی‌گردانم.\n"
                "بدون سؤال.\n\n"
                "⚠️ پاسخ حدود هر ۵ دقیقه یک‌بار است."
            )
            if message_id:
                processed[f"msg:{message_id}"] = time.time()
            return

        file_info = msg.get("file") or msg.get("file_inline") or msg.get("document")
        if file_info:
            process_file_message(chat_id, msg, processed)
            return

        aux = msg.get("aux_data") or {}
        if isinstance(aux, dict) and aux.get("button_id"):
            print(f"Ignore button {aux.get('button_id')}")
            if message_id:
                processed[f"msg:{message_id}"] = time.time()
            return

        if text and message_id:
            processed[f"msg:{message_id}"] = time.time()

    except Exception as e:
        print(f"Process error: {e}")
        import traceback
        traceback.print_exc()

def main():
    print("🤖 Auto-compress bot started...")
    offset = load_offset()
    processed = load_json(PROCESSED_FILE, {})
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
