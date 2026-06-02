import telebot
import os
import time
from flask import Flask, jsonify
from yt_dlp import YoutubeDL
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client, Client
from datetime import datetime

# --- [0] إعداد خادم الويب ---
app = Flask('')
@app.route('/')
def home():
    return "خادم البوت يعمل بكفاءة عالية ✅"

@app.route('/health')
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()}), 200

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# تشغيل خادم ويب Flask في الخلفية
import threading
threading.Thread(target=run_flask, daemon=True).start()

# --- [1] إعدادات البوت و Supabase ---
TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))

if not TOKEN or not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("تأكد من تعبئة BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY في المتغيرات البيئية")

bot = telebot.TeleBot(TOKEN)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# تحديد عدد العمال بـ 4 لمنع استهلاك موارد السيرفر بالكامل عند الضغط
executor = ThreadPoolExecutor(max_workers=4)

# --- [2] دوال السيرفر وقاعدة البيانات ---
def log_event(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def save_user(user_id, username):
    try:
        supabase.table("users").upsert({
            "user_id": int(user_id),
            "username": username or "بدون_يوزر"
        }).execute()
        log_event(f"➕ مستخدم محفوظ: @{username} ({user_id})")
    except Exception as e:
        log_event(f"❌ خطأ أثناء حفظ مستخدم: {e}")

def get_all_users():
    try:
        res = supabase.table("users").select("user_id").execute()
        return [int(u['user_id']) for u in res.data]
    except Exception as e:
        log_event(f"❌ خطأ جلب المستخدمين: {e}")
        return []

def get_cookie_file():
    """يجيب أقل كوكي استهلاكاً ويرجع مسار ملف نصي ثابت لمنع التصادم"""
    try:
        res = supabase.table("tiktok_cookies").select("*").eq("is_active", True).order("last_used").limit(1).execute()
        if not res.data:
            return None

        cookie = res.data[0]
        # استخدام اسم ثابت لكل معرف كوكي يمنع تصادم وحذف الخيوط لملفات بعضها البعض
        cookie_path = os.path.join(BASE_DIR, f"cookie_{cookie['id']}.txt")

        # إنشاء أو تحديث ملف الكوكي (عملية كتابة سريعة لا تضر)
        with open(cookie_path, 'w', encoding='utf-8') as f:
            f.write(cookie['cookie_text'])

        # تحديث وقت الاستخدام في الداتابيز
        supabase.table("tiktok_cookies").update({"last_used": datetime.now().isoformat()}).eq("id", cookie['id']).execute()
        return cookie_path
    except Exception as e:
        log_event(f"❌ خطأ جلب الكوكي من Supabase: {e}")
        return None

# --- [3] دالة معالجة وتحميل الفيديو ---
def download_tiktok_video(url, chat_id, message_id, username):
    unique_id = f"{chat_id}_{int(time.time())}"
    filename = os.path.join(BASE_DIR, f'tiktok_{unique_id}.mp4')
    cookie_file = get_cookie_file()

    # خيارات تحميل متوافقة لضمان دمج الصوت والفيديو بشكل صحيح واختيار حاوية mp4
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': filename,
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 49 * 1024 * 1024, # حماية أمان لتليجرام (أقل من 50 ميجا)
        'socket_timeout': 30,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    }

    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    try:
        log_event(f"📥 بدء تحميل لـ @{username} | الرابط: {url}")
        bot.edit_message_text("⏳ جاري سحب مقطع الفيديو من الخادم...", chat_id, message_id)

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'فيديو تيك توك')[:100]
            author = info.get('uploader', 'غير معروف')
            duration = info.get('duration', 0)

        bot.edit_message_text("📤 جاري الرفع إلى تليجرام، يرجى الانتظار...", chat_id, message_id)

        # تجهيز الوصف بصيغة احترافية ورسمية
        caption = f"🎬 {title}\n👤 ‏{author}\n⏱️ {duration//60}:{duration%60:02d}" if duration else f"🎬 {title}\n👤 ‏{author}"

        with open(filename, 'rb') as video:
            bot.send_video(chat_id, video, caption=caption + "\n\n✨ تم التحميل عبر نظام التحميل الآلي.")

        bot.delete_message(chat_id, message_id)
        log_event(f"✅ تم إرسال الفيديو بنجاح إلى @{username}")

    except Exception as e:
        error = str(e).lower()
        log_event(f"❌ خطأ أثناء معالجة طلب @{username}: {e}")

        if "file size" in error or "too large" in error:
            msg = "❌ نعتذر، حجم الفيديو يتجاوز الحد المسموح به (50 ميجابايت)."
        elif "private" in error or "login" in error:
            msg = "❌ عذراً، هذا المقطع خاص بحساب مقفل (Private). يرجى تجربة مقطع عام."
        else:
            msg = "❌ عذراً، فشل تحميل المقطع. تأكد من صحة الرابط ثم أعد المحاولة لاحقاً."

        bot.edit_message_text(msg, chat_id, message_id)

    finally:
        # حذف ملف الفيديو فقط للحفاظ على مساحة الهارد ديسك بالسيرفر
        # ملفات الكوكيز نتركها لتجنب ضرب خيوط التحميل المتزامنة (Race Condition)
        if os.path.exists(filename):
            try: 
                os.remove(filename)
            except: 
                pass

# --- [4] البث الجماعي (Broadcast) ---
def send_broadcast(text, admin_chat_id):
    users = get_all_users()
    if not users:
        bot.send_message(admin_chat_id, "❌ لا يوجد مستخدمين مسجلين في النظام حالياً.")
        return

    status = bot.send_message(admin_chat_id, f"📢 بدء عملية الإرسال الجماعي لـ {len(users)} مستخدم...")
    success = fail = 0

    for uid in users:
        try:
            bot.send_message(uid, text)
            success += 1
            time.sleep(0.05) # معدل إرسال آمن لتجنب حظر التليجرام (Flood Control)
        except telebot.apihelper.ApiTelegramException as e:
            fail += 1
            if e.error_code == 403: # إذا قام المستخدم بحظر البوت، يتم حذفه تلقائياً
                try:
                    supabase.table("users").delete().eq("user_id", int(uid)).execute()
                except Exception as db_err:
                    log_event(f"⚠️ تعذر حذف المستخدم المحظور {uid} من الداتابيز: {db_err}")
        except:
            fail += 1

    bot.edit_message_text(
        f"✅ اكتملت عملية الإرسال الجماعي بنجاح.\n\n📊 الإحصائيات:\n- ناجح: {success}\n- فشل / حظر: {fail}",
        admin_chat_id, status.message_id
    )

# --- [5] مستقبِلات الرسائل (Handlers) ---
@bot.message_handler(commands=['start'])
def welcome(m):
    save_user(m.chat.id, m.from_user.username)
    bot.reply_to(m, "مرحباً بك! يرجى إرسال رابط فيديو TikTok المراد تحميله، وسيقوم النظام بمعالجته فوراً. 🤖")

@bot.message_handler(commands=['stats'])
def stats(m):
    if m.chat.id != ADMIN_ID: 
        return
    users = get_all_users()
    cookies = supabase.table("tiktok_cookies").select("id", count="exact").execute()
    bot.reply_to(m, f"📊 إحصائيات النظام الحالية:\n\n👥 عدد المستخدمين: {len(users)}\n🍪 عدد الكوكيز النشطة: {cookies.count}")

@bot.message_handler(commands=['broadcast'])
def broadcast_cmd(m):
    if m.chat.id != ADMIN_ID: 
        return
    text = m.text.replace("/broadcast", "").strip()
    if not text:
        bot.reply_to(m, "⚠️ يرجى كتابة نص الرسالة بعد الأمر.\nمثال: `/broadcast تحديث جديد للنظام`", parse_mode="Markdown")
        return
    executor.submit(send_broadcast, text, m.chat.id)

@bot.message_handler(func=lambda m: m.text and ('tiktok.com' in m.text or 'vxtiktok.com' in m.text))
def handle_link(m):
    username = m.from_user.username or f"User_{m.chat.id}"
    msg = bot.reply_to(m, "🔍 جاري فحص الرابط والتحقق من صلاحيته...")
    executor.submit(download_tiktok_video, m.text.strip(), m.chat.id, msg.message_id, username)

# مستجيب الروابط غير المدعومة (يعمل فقط إذا أرسل المستخدم رابطاً لموقع آخر)
@bot.message_handler(func=lambda m: m.text and m.text.startswith('http') and 'tiktok.com' not in m.text)
def fallback(m):
    bot.reply_to(m, "❌ عذراً، هذا الرابط غير مدعوم. النظام مخصص حالياً للتحميل من منصة تيك توك (TikTok) فقط.")

if __name__ == "__main__":
    log_event("النظام يعمل الآن بنجاح وأعلى درجات الأمان...")
    # إعداد الـ Polling مع ميزة الـ Long Polling لضمان الاستقرار وعدم انقطاع الاتصال
    bot.infinity_polling(timeout=20, long_polling_timeout=10)
