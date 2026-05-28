import telebot
import os
import random
import threading
from flask import Flask
from yt_dlp import YoutubeDL

# --- [0] إعداد السيرفر عشان يفضل صاحي ---
app = Flask('')
@app.route('/')
def home(): return "بوت مصطفى شغال زي الساعة ✅"

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_flask, daemon=True).start()

# --- [1] الأساسيات (تأكد من وضع التوكن في Environ) ---
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- [2] دالة التحميل الذكية ---
def download_video(url, chat_id, message_id):
    # خيارات التحميل بلمسة بشرية: بنحاول نجيب أقل جودة عشان ما نتعدى 50 ميجا
    ydl_opts = {
        'format': 'best[height<=480][ext=mp4]/best[ext=mp4]/best', # دقة 480 مناسبة جداً لتليجرام
        'outtmpl': os.path.join(BASE_DIR, f'botmost_{chat_id}.%(ext)s'),
        'nocheckcertificate': True,
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 48 * 1024 * 1024, # خلّي شوية مساحة أمان
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    }

    # إضافة الكوكيز لو موجودة (عشان يوتيوب ما يزعل)
    if "youtube" in url or "youtu.be" in url:
        cookie_path = os.path.join(BASE_DIR, "youtube_cookies.txt")
        if os.path.exists(cookie_path):
            ydl_opts['cookiefile'] = cookie_path

    try:
        with YoutubeDL(ydl_opts) as ydl:
            bot.edit_message_text("⏳ ثواني.. جاري سحب الفيديو من السيرفر...", chat_id, message_id)
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

            bot.edit_message_text("📤 جاري الرفع لتليجرام.. أبشر بالخير", chat_id, message_id)
            with open(filename, 'rb') as video:
                bot.send_video(chat_id, video, caption="تم التحميل بواسطة BotMost 🦾🇸🇩")
            
            bot.delete_message(chat_id, message_id)
            if os.path.exists(filename): os.remove(filename)

    except Exception as e:
        error_msg = str(e)
        if "File size" in error_msg:
            bot.edit_message_text("❌ الفيديو ده تقيل شديد (أكبر من 50MB)، جرب فيديو أقصر.", chat_id, message_id)
        else:
            bot.edit_message_text("❌ حصلت مشكلة تقنية، غالباً الرابط خاص أو السيرفر محظور.", chat_id, message_id)
        print(f"Error: {e}")

# --- [3] استقبال الرسائل ---
@bot.message_handler(commands=['start'])
def welcome(m):
    bot.reply_to(m, "يا هلا بيك! أرسل لي أي رابط (تيك توك، يوتيوب، تويتر) وحأحمله ليك فوراً. 🚀")

@bot.message_handler(func=lambda m: m.text and m.text.startswith('http'))
def handle_links(m):
    url = m.text
    msg = bot.reply_to(m, "🔍 جاري الفحص.. خليك قريب")
    # تشغيل التحميل في Thread منفصل عشان البوت ما يعلق لو في زول تاني أرسل
    threading.Thread(target=download_video, args=(url, m.chat.id, msg.message_id)).start()

if __name__ == "__main__":
    print("Bot is flying...")
    bot.infinity_polling()
