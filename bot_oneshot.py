#!/usr/bin/env python3
"""
نسخه یک‌باراجرای ربات برای GitHub Actions
هر ۵ دقیقه اجرا می‌شود، پیام‌های جدید را پردازش می‌کند و خارج می‌شود.
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
STATE_FILE = "user_states.json"
TEMP_DIR = Path("temp_files")
TEMP_DIR.mkdir(exist_ok=True)

def api(method, data=None):
    url = f"{API}/{method}"
    try:
        r = requests.post(url, json=data or {}, timeout=45)
        return r.json()
    except Exception as e:
        print(f"API Error: {e}")
        return None

def send_message(chat_id, text, inline_keypad=None):
    data = {"chat_id": chat_id, "text": text}
    if inline_keypad:
        data["inline_keypad"] = inline_keypad
    return api("sendMessage", data)

def get_file(file_id):
    res = api("getFile", {"file_id": file_id})
    if res and res.get("status") == "OK":
        return res.get("data", {}).get("download_url")
    return None

def download_file(url, save_path):
    try:
        with requests.get(url, stream=True, timeout=90) as r:
            r.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return True
    except Exception as e:
        print(f"Download error: {e}")
        return False

def request_send_file(file_type="File"):
    res = api("requestSendFile", {"type": file_type})
    if res and res.get("status") == "OK":
        return res.get("data", {}).get("upload_url")
    return None

def upload_file(upload_url, file_path, file_name):
    try:
        with open(file_path, "rb") as f:
            files = {"file": (file_name, f)}
            r = requests.post(upload_url, files=files, timeout=180)
            res = r.json()
            if res.get("status") == "OK":
                return res.get("data", {}).get("file_id")
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

def compress_video(input_path, output_path, crf=28):
    cmd = ["ffmpeg", "-y", "-i", str(input_path), "-c:v", "libx264", "-crf", str(crf),
           "-preset", "fast", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(output_path)]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        return True
    except:
        return False

def compress_audio(input_path, output_path, bitrate="96k"):
    cmd = ["ffmpeg", "-y", "-i", str(input_path), "-c:a", "libmp3lame", "-b:a", bitrate, str(output_path)]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        return True
    except:
        return False

def compress_image(input_path, output_path, quality=70):
    cmd = ["ffmpeg", "-y", "-i", str(input_path), "-q:v", str(int((100 - quality) / 5) + 2), str(output_path)]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        return True
    except:
        return False

def compress_pdf(input_path, output_path):
    cmd = ["gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4", "-dPDFSETTINGS=/ebook",
           "-dNOPAUSE", "-dQUIET", "-dBATCH", f"-sOutputFile={output_path}", str(input_path)]
    try:
        subprocess.run(cmd, check=True, timeout=120)
        return True
    except:
        import shutil
        shutil.copy(input_path, output_path)
        return False

def make_zip(input_path, output_path):
    import zipfile
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(input_path, arcname=os.path.basename(input_path))
    return True

def make_size_keyboard(file_type):
    if file_type in ["video", "audio"]:
        options = [("کم (حجم کمتر)", "low"), ("متوسط", "medium"), ("بالا (کیفیت بهتر)", "high")]
    else:
        options = [("حداکثر فشرده‌سازی", "max"), ("متوسط", "medium"), ("کم", "low")]
    rows = [{"buttons": [{"id": v, "type": "Simple", "button_text": t}]} for t, v in options]
    return {"rows": rows}

def load_states():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}

def save_states(states):
    with open(STATE_FILE, "w") as f:
        json.dump(states, f)

def load_offset():
    if os.path.exists(OFFSET_FILE):
        with open(OFFSET_FILE) as f:
            return f.read().strip()
    return None

def save_offset(offset):
    with open(OFFSET_FILE, "w") as f:
        f.write(str(offset))

def process_update(update, user_states):
    try:
        if "new_message" not in update:
            return

        msg = update["new_message"]
        chat_id = update.get("chat_id")
        text = (msg.get("text") or "").strip()
        aux = msg.get("aux_data") or {}
        button_id = aux.get("button_id")

        if text in ["/start", "شروع"]:
            send_message(chat_id,
                "سلام 👋\nمن ربات کاهش حجم فایل هستم.\n\n"
                "فایل (ویدیو، صوت، تصویر، PDF یا هر فایل) رو بفرست.\n"
                "بعد گزینه‌های کاهش حجم رو برات می‌فرستم.\n\n"
                "⚠️ این ربات هر ۵ دقیقه یک‌بار چک می‌کند (GitHub Actions)."
            )
            return

        # دکمه انتخاب سطح فشرده‌سازی
        if button_id and chat_id in user_states:
            state = user_states[chat_id]
            level = button_id
            send_message(chat_id, "⏳ در حال کاهش حجم... (ممکن است چند دقیقه طول بکشد)")

            input_path = state["path"]
            original_name = state["name"]
            file_type = state["type"]

            output_name = f"compressed_{original_name}"
            output_path = TEMP_DIR / output_name

            success = False
            if file_type == "video":
                crf = {"low": 32, "medium": 28, "high": 23}.get(level, 28)
                success = compress_video(input_path, output_path, crf)
            elif file_type == "audio":
                br = {"low": "64k", "medium": "96k", "high": "128k"}.get(level, "96k")
                success = compress_audio(input_path, output_path, br)
            elif file_type == "image":
                q = {"max": 50, "medium": 70, "low": 85}.get(level, 70)
                success = compress_image(input_path, output_path, q)
            elif file_type == "pdf":
                success = compress_pdf(input_path, output_path)
            else:
                output_path = TEMP_DIR / (Path(original_name).stem + ".zip")
                success = make_zip(input_path, output_path)
                output_name = output_path.name

            if success and output_path.exists():
                new_size = get_file_size_mb(output_path)
                old_size = state["size"]
                upload_url = request_send_file("File")
                if upload_url:
                    file_id = upload_file(upload_url, output_path, output_name)
                    if file_id:
                        caption = (f"✅ فایل کم‌حجم شد!\n\n"
                                   f"حجم قبلی: {old_size:.1f} MB\n"
                                   f"حجم جدید: {new_size:.1f} MB\n"
                                   f"کاهش: {((old_size - new_size) / max(old_size, 0.01) * 100):.0f}%")
                        send_file(chat_id, file_id, text=caption)
                    else:
                        send_message(chat_id, "❌ خطا در آپلود فایل فشرده.")
                else:
                    send_message(chat_id, "❌ خطا در لینک آپلود.")
            else:
                send_message(chat_id, "❌ فشرده‌سازی ناموفق بود (ممکن است فایل بزرگ باشد یا زمان کم).")

            try:
                if os.path.exists(input_path):
                    os.remove(input_path)
                if output_path.exists():
                    os.remove(output_path)
            except:
                pass
            user_states.pop(chat_id, None)
            return

        # دریافت فایل جدید
        file_info = msg.get("file") or msg.get("file_inline")
        if file_info:
            file_id = file_info.get("file_id") or file_info.get("id")
            file_name = file_info.get("file_name") or file_info.get("name") or "file.bin"

            if not file_id:
                send_message(chat_id, "❌ اطلاعات فایل پیدا نشد.")
                return

            send_message(chat_id, "📥 در حال دانلود فایل...")

            download_url = get_file(file_id)
            if not download_url:
                send_message(chat_id, "❌ لینک دانلود پیدا نشد.")
                return

            local_path = TEMP_DIR / f"{chat_id}_{int(time.time())}_{file_name}"
            if not download_file(download_url, local_path):
                send_message(chat_id, "❌ دانلود ناموفق بود.")
                return

            ext = Path(file_name).suffix.lower()
            if ext in [".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv"]:
                ftype = "video"
            elif ext in [".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"]:
                ftype = "audio"
            elif ext in [".jpg", ".jpeg", ".png", ".webp", ".bmp"]:
                ftype = "image"
            elif ext == ".pdf":
                ftype = "pdf"
            else:
                ftype = "other"

            real_size = get_file_size_mb(local_path)
            user_states[chat_id] = {
                "path": str(local_path),
                "name": file_name,
                "type": ftype,
                "size": real_size
            }

            keyboard = make_size_keyboard(ftype)
            send_message(
                chat_id,
                f"📁 فایل دریافت شد!\nنام: {file_name}\nحجم: {real_size:.1f} MB\n\nچقدر می‌خوای حجمش کم بشه؟",
                inline_keypad=keyboard
            )
            return

    except Exception as e:
        print(f"Process error: {e}")

def main():
    print("🤖 One-shot Rubika bot started (GitHub Actions)...")
    offset = load_offset()
    user_states = load_states()

    data = {"limit": 50}
    if offset:
        data["offset_id"] = offset

    res = api("getUpdates", data)
    if not res or res.get("status") != "OK":
        print("No updates or API error")
        return

    updates = res.get("data", {}).get("updates", [])
    print(f"Received {len(updates)} updates")

    for upd in updates:
        process_update(upd, user_states)
        new_offset = upd.get("message_id") or upd.get("update_id") or upd.get("new_message", {}).get("message_id")
        if new_offset:
            offset = str(new_offset)

    if offset:
        save_offset(offset)
    save_states(user_states)
    print("Done.")

if __name__ == "__main__":
    main()
