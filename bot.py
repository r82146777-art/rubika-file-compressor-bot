import requests
import time
import os
import json
import subprocess
from pathlib import Path

# ====================== تنظیمات ======================
TOKEN = "CGFIFG0HKQPNRAIYNLROCQIPPCAEZQCHJIDXAUHNTEPRDDEQHNRSELACLTXJAMIN"
API = f"https://botapi.rubika.ir/v3/{TOKEN}"
OFFSET_FILE = "offset.txt"
TEMP_DIR = Path("temp_files")
TEMP_DIR.mkdir(exist_ok=True)

# وضعیت کاربران (chat_id -> اطلاعات فایل در حال پردازش)
user_states = {}

# ====================== توابع API ======================
def api(method, data=None):
    url = f"{API}/{method}"
    try:
        r = requests.post(url, json=data or {}, timeout=60)
        return r.json()
    except Exception as e:
        print(f"API Error: {e}")
        return None

def send_message(chat_id, text, inline_keypad=None, reply_to=None):
    data = {"chat_id": chat_id, "text": text}
    if inline_keypad:
        data["inline_keypad"] = inline_keypad
    if reply_to:
        data["reply_to_message_id"] = reply_to
    return api("sendMessage", data)

def get_file(file_id):
    res = api("getFile", {"file_id": file_id})
    if res and res.get("status") == "OK":
        return res.get("data", {}).get("download_url")
    return None

def download_file(url, save_path):
    try:
        with requests.get(url, stream=True, timeout=120) as r:
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
            r = requests.post(upload_url, files=files, timeout=300)
            res = r.json()
            if res.get("status") == "OK":
                return res.get("data", {}).get("file_id")
    except Exception as e:
        print(f"Upload error: {e}")
    return None

def send_file(chat_id, file_id, text=None, reply_to=None):
    data = {"chat_id": chat_id, "file_id": file_id}
    if text:
        data["text"] = text
    if reply_to:
        data["reply_to_message_id"] = reply_to
    return api("sendFile", data)

# ====================== فشرده‌سازی ======================
def get_file_size_mb(path):
    return os.path.getsize(path) / (1024 * 1024)

def compress_video(input_path, output_path, crf=28):
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-c:v", "libx264", "-crf", str(crf),
        "-preset", "medium", "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", str(output_path)
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except:
        return False

def compress_audio(input_path, output_path, bitrate="96k"):
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-c:a", "libmp3lame", "-b:a", bitrate, str(output_path)
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except:
        return False

def compress_image(input_path, output_path, quality=70):
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-q:v", str(int((100 - quality) / 5) + 2), str(output_path)
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except:
        return False

def compress_pdf(input_path, output_path):
    cmd = [
        "gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
        "-dPDFSETTINGS=/ebook", "-dNOPAUSE", "-dQUIET", "-dBATCH",
        f"-sOutputFile={output_path}", str(input_path)
    ]
    try:
        subprocess.run(cmd, check=True)
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

# ====================== ساخت کیبورد ======================
def make_size_keyboard(file_size_mb, file_type):
    if file_type in ["video", "audio"]:
        options = [
            ("کم (حجم کمتر)", "low"),
            ("متوسط", "medium"),
            ("بالا (کیفیت بهتر)", "high"),
        ]
    else:
        options = [
            ("حداکثر فشرده‌سازی", "max"),
            ("متوسط", "medium"),
            ("کم", "low"),
        ]

    rows = []
    for text, value in options:
        rows.append({
            "buttons": [{
                "id": value,
                "type": "Simple",
                "button_text": text
            }]
        })
    return {"rows": rows}

# ====================== پردازش پیام ======================
def process_update(update):
    try:
        if "new_message" not in update:
            return

        msg = update["new_message"]
        chat_id = update.get("chat_id")
        message_id = str(msg.get("message_id", ""))
        text = msg.get("text", "") or ""
        sender_id = msg.get("sender_id")

        aux = msg.get("aux_data") or {}
        button_id = aux.get("button_id")

        if text.strip() in ["/start", "شروع"]:
            send_message(chat_id,
                "سلام 👋\n"
                "من ربات کاهش حجم فایل هستم.\n\n"
                "فقط فایل (ویدیو، صوت، تصویر، PDF یا هر فایل دیگه) رو بفرست.\n"
                "بعد از دریافت، گزینه‌های کاهش حجم رو برات می‌فرستم."
            )
            return

        if button_id and chat_id in user_states:
            state = user_states[chat_id]
            level = button_id
            send_message(chat_id, "⏳ در حال کاهش حجم فایل... لطفاً صبر کن.")

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
                        caption = (
                            f"✅ فایل با موفقیت کم‌حجم شد!\n\n"
                            f"حجم قبلی: {old_size:.1f} MB\n"
                            f"حجم جدید: {new_size:.1f} MB\n"
                            f"کاهش: {((old_size - new_size) / old_size * 100):.0f}%"
                        )
                        send_file(chat_id, file_id, text=caption)
                    else:
                        send_message(chat_id, "❌ خطا در آپلود فایل فشرده.")
                else:
                    send_message(chat_id, "❌ خطا در دریافت لینک آپلود.")
            else:
                send_message(chat_id, "❌ متأسفانه نتونستم فایل رو فشرده کنم.")

            try:
                os.remove(input_path)
                if output_path.exists():
                    os.remove(output_path)
            except:
                pass
            user_states.pop(chat_id, None)
            return

        file_info = msg.get("file") or msg.get("file_inline")
        if file_info:
            file_id = file_info.get("file_id") or file_info.get("id")
            file_name = file_info.get("file_name") or file_info.get("name") or "file.bin"
            size = file_info.get("size", 0) / (1024 * 1024)

            if not file_id:
                send_message(chat_id, "❌ نتونستم اطلاعات فایل رو بگیرم.")
                return

            send_message(chat_id, "📥 در حال دانلود فایل...")

            download_url = get_file(file_id)
            if not download_url:
                send_message(chat_id, "❌ لینک دانلود فایل پیدا نشد.")
                return

            local_path = TEMP_DIR / f"{chat_id}_{file_name}"
            if not download_file(download_url, local_path):
                send_message(chat_id, "❌ دانلود فایل ناموفق بود.")
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

            keyboard = make_size_keyboard(real_size, ftype)
            send_message(
                chat_id,
                f"📁 فایل دریافت شد!\n"
                f"نام: {file_name}\n"
                f"حجم فعلی: {real_size:.1f} MB\n\n"
                f"چقدر می‌خوای حجمش کم بشه؟",
                inline_keypad=keyboard
            )
            return

    except Exception as e:
        print(f"Process error: {e}")

# ====================== حلقه اصلی ======================
def load_offset():
    if os.path.exists(OFFSET_FILE):
        with open(OFFSET_FILE) as f:
            return f.read().strip()
    return None

def save_offset(offset):
    with open(OFFSET_FILE, "w") as f:
        f.write(str(offset))

def main():
    print("🤖 ربات کاهش حجم فایل روبیکا شروع به کار کرد...")
    offset = load_offset()

    while True:
        try:
            data = {"limit": 100}
            if offset:
                data["offset_id"] = offset

            res = api("getUpdates", data)
            if not res or res.get("status") != "OK":
                time.sleep(3)
                continue

            updates = res.get("data", {}).get("updates", [])
            if not updates:
                time.sleep(2)
                continue

            for upd in updates:
                process_update(upd)
                new_offset = upd.get("message_id") or upd.get("update_id")
                if new_offset:
                    offset = new_offset
                    save_offset(offset)

            time.sleep(1)

        except KeyboardInterrupt:
            print("\nربات متوقف شد.")
            break
        except Exception as e:
            print(f"Main loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
