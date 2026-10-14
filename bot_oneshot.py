#!/usr/bin/env python3
"""
ربات کاهش حجم خودکار روبیکا (GitHub Actions - هر ۵ دقیقه)
- هر فایل فقط یک‌بار پردازش می‌شود (processed_ids در cache ذخیره می‌شود)
- فشرده‌سازی فوق‌العاده تهاجمی برای کمترین حجم ممکن (هدف حدود ۲ تا ۱۰ مگ)
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

MAX_UPLOAD_MB = 45
# هدف حجم خیلی کوچک برای ویدیو
TARGET_MB = 8
MAX_INPUT_MB = 600
# در هر اجرا حداکثر چند فایل جدید پردازش شود (جلوگیری از صف قدیمی)
MAX_FILES_PER_RUN = 1

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
    return {
        "video": "Video",
        "audio": "Music",
        "image": "Image",
        "pdf": "File",
        "other": "File",
    }.get(ftype, "File")

def run_ffmpeg(cmd, timeout=1200):
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
        return True
    except Exception as e:
        print(f"ffmpeg failed: {e}")
        return False

def compress_ultra_min(input_path, output_path, ftype):
    """کمترین حجم ممکن - هدف حدود ۲ تا ۱۰ مگ برای ویدیو"""
    if ftype == "video":
        # از خیلی فشرده شروع می‌کنیم و اگر لازم باشد کوچک‌تر
        attempts = [
            # scale, crf, fps, audio
            ("640", "38", "18", "32k"),
            ("480", "42", "15", "24k"),
            ("360", "45", "12", "24k"),
            ("320", "48", "10", "16k"),
            ("240", "51", "8", "16k"),
        ]
        best = None
        for scale, crf, fps, abr in attempts:
            cmd = [
                "ffmpeg", "-y", "-i", str(input_path),
                "-c:v", "libx264", "-crf", crf, "-preset", "veryfast",
                "-vf", f"scale={scale}:-2,fps={fps}",
                "-c:a", "aac", "-b:a", abr, "-ac", "1",
                "-movflags", "+faststart", str(output_path),
            ]
            if run_ffmpeg(cmd) and output_path.exists():
                mb = get_file_size_mb(output_path)
                print(f"video attempt {scale}p crf={crf} fps={fps} -> {mb:.1f} MB")
                best = mb
                if mb <= TARGET_MB:
                    return True
                if mb <= MAX_UPLOAD_MB and scale == "240":
                    return True
        return output_path.exists() and get_file_size_mb(output_path) <= MAX_UPLOAD_MB

    if ftype == "audio":
        for br in ("48k", "32k", "24k", "16k"):
            cmd = [
                "ffmpeg", "-y", "-i", str(input_path),
                "-c:a", "libmp3lame", "-b:a", br, "-ac", "1", str(output_path),
            ]
            if run_ffmpeg(cmd, timeout=300) and output_path.exists():
                mb = get_file_size_mb(output_path)
                print(f"audio {br} -> {mb:.1f} MB")
                if mb <= TARGET_MB or br == "16k":
                    return True
        return output_path.exists()

    if ftype == "image":
        out = output_path if str(output_path).lower().endswith((".jpg", ".jpeg")) else Path(str(output_path) + ".jpg")
        for scale, q in (("720", "10"), ("480", "12"), ("360", "15"), ("240", "20")):
            cmd = [
                "ffmpeg", "-y", "-i", str(input_path),
                "-vf", f"scale='min({scale},iw)':-2", "-q:v", q, str(out),
            ]
            if run_ffmpeg(cmd, timeout=120) and out.exists():
                mb = get_file_size_mb(out)
                print(f"image {scale} q={q} -> {mb:.1f} MB")
                if out != output_path:
                    out.replace(output_path)
                if mb <= TARGET_MB or scale == "240":
                    return True
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

def mark_processed(processed, message_id, file_id=None):
    now = time.time()
    if message_id:
        processed[f"msg:{message_id}"] = now
    if file_id:
        processed[f"file:{file_id}"] = now

def is_processed(processed, message_id, file_id=None):
    if message_id and f"msg:{message_id}" in processed:
        return True
    if file_id and f"file:{file_id}" in processed:
        return True
    return False

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

    send_message(chat_id, "📥 فایل دریافت شد.\nدر حال کاهش به کمترین حجم ممکن...")

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
    ok = compress_ultra_min(local_path, output_path, ftype)

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
        send_message(
            chat_id,
            f"❌ بعد از حداکثر فشرده‌سازی هنوز {new_size:.1f} MB است.\n"
            f"سقف روبیکا حدود ۵۰ MB است. فایل کوتاه‌تر بفرست."
        )
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
                f"✅ فایل با کمترین حجم ممکن آماده شد\n\n"
                f"قبل: {old_size:.1f} MB\n"
                f"بعد: {new_size:.1f} MB\n"
                f"کاهش: {reduction:.0f}%"
            )
            send_file(chat_id, new_file_id, text=caption)
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

def extract_file_updates(updates):
    """لیست (update, chat_id, msg) برای پیام‌های دارای فایل"""
    result = []
    for upd in updates:
        if not isinstance(upd, dict):
            continue
        msg = None
        chat_id = None
        if "new_message" in upd:
            msg = upd["new_message"]
            chat_id = upd.get("chat_id") or (msg or {}).get("chat_id")
        elif upd.get("type") == "NewMessage":
            msg = upd.get("new_message")
            chat_id = upd.get("chat_id")
        if not msg or not chat_id:
            continue
        if msg.get("file") or msg.get("file_inline") or msg.get("document"):
            result.append((upd, chat_id, msg))
    return result

def process_update_non_file(update, processed):
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
        return

    text = (msg.get("text") or "").strip()
    if text in ("/start", "شروع", "start"):
        send_message(
            chat_id,
            "سلام 👋\n"
            "فقط فایل بفرست.\n"
            "من یک‌بار به کمترین حجم ممکن کم می‌کنم و برمی‌گردانم.\n"
            "همان فایل دوباره پردازش نمی‌شود.\n\n"
            "⚠️ هر حدود ۵ دقیقه یک‌بار چک می‌شود."
        )
        mark_processed(processed, message_id)
        return

    # دکمه یا متن → فقط علامت بزن که دیده شد
    if message_id:
        mark_processed(processed, message_id)

def main():
    print("🤖 Auto-compress bot started...")
    offset = load_offset()
    processed = load_json(PROCESSED_FILE, {})
    now = time.time()
    # نگه داشتن شناسه‌ها تا ۳۰ روز
    processed = {k: v for k, v in processed.items() if isinstance(v, (int, float)) and now - v < 30 * 86400}
    print(f"offset={offset!r} processed_count={len(processed)}")

    data = {"limit": 100}
    if offset:
        data["offset_id"] = offset

    res = api("getUpdates", data)
    if not res:
        print("No getUpdates response")
        save_json(PROCESSED_FILE, processed)
        return

    updates = []
    if isinstance(res, dict) and res.get("status") == "OK":
        data_part = res.get("data") or {}
        updates = data_part.get("updates") or []
        if isinstance(updates, dict):
            updates = [updates]

    print(f"Received {len(updates)} updates")

    # اول همه غیر‌فایل‌ها را علامت بزن / start را جواب بده
    for upd in updates:
        if isinstance(upd, dict):
            fi = None
            nm = upd.get("new_message") or {}
            if isinstance(nm, dict):
                fi = nm.get("file") or nm.get("file_inline") or nm.get("document")
            if not fi:
                process_update_non_file(upd, processed)

    file_updates = extract_file_updates(updates)
    print(f"File messages in batch: {len(file_updates)}")

    # فقط فایل‌هایی که هنوز پردازش نشده‌اند
    pending = []
    for upd, chat_id, msg in file_updates:
        mid = str(msg.get("message_id") or "")
        finfo = msg.get("file") or msg.get("file_inline") or msg.get("document") or {}
        fid = finfo.get("file_id") or finfo.get("id")
        if is_processed(processed, mid, fid):
            print(f"SKIP old file msg={mid}")
            continue
        pending.append((upd, chat_id, msg))

    print(f"Pending new files: {len(pending)}")

    # فقط جدیدترین‌ها (آخر لیست معمولاً جدیدتر است) — حداکثر MAX_FILES_PER_RUN
    to_process = pending[-MAX_FILES_PER_RUN:] if pending else []

    # بقیه pending که در این دور پردازش نمی‌شوند را هم علامت نزن
    # تا دور بعد فقط یکی‌یکی انجام شوند — اما اگر تعداد خیلی زیاد است
    # فایل‌های خیلی قدیمی (به‌جز آخرین‌ها) را SKIP و mark کن تا گیر نکند
    if len(pending) > MAX_FILES_PER_RUN:
        old_ones = pending[:-MAX_FILES_PER_RUN]
        print(f"Marking {len(old_ones)} older pending files as skipped (only process newest)")
        for upd, chat_id, msg in old_ones:
            mid = str(msg.get("message_id") or "")
            finfo = msg.get("file") or msg.get("file_inline") or msg.get("document") or {}
            fid = finfo.get("file_id") or finfo.get("id")
            mark_processed(processed, mid, fid)

    for upd, chat_id, msg in to_process:
        process_file_message(chat_id, msg, processed)

    # به‌روزرسانی offset از آخرین آپدیت
    new_offset = offset
    for upd in updates:
        if isinstance(upd, dict):
            cand = (
                (upd.get("new_message") or {}).get("message_id")
                or upd.get("message_id")
                or upd.get("update_id")
            )
            if cand:
                new_offset = str(cand)

    if new_offset:
        save_offset(new_offset)
        print(f"Saved offset={new_offset}")

    save_json(PROCESSED_FILE, processed)
    print(f"processed_count now={len(processed)}")
    print("Done.")

if __name__ == "__main__":
    main()
