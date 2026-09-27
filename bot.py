import os, asyncio, subprocess
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN")
MAX_STREAMS = 9
streams = {}
sessions = {}

def ffmpeg_ok():
    try:
        return subprocess.run(["ffmpeg","-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode == 0
    except Exception:
        return False

def start_ffmpeg(source, key):
    output = f"rtmps://live-api-s.facebook.com:443/rtmp/{key}"
    cmd = [
        "ffmpeg","-hide_banner","-loglevel","warning",
        "-reconnect","1","-reconnect_streamed","1","-reconnect_delay_max","10",
        "-i",source,
        "-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",
        "-r","30","-g","60","-keyint_min","60","-sc_threshold","0",
        "-c:a","aac","-b:a","128k","-ar","44100",
        "-f","flv",output
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

def duration(started):
    s = int((datetime.now()-started).total_seconds())
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("استخدم: /start 1 إلى /start 9")
        return
    try: slot = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ الرقم يجب أن يكون من 1 إلى 9."); return
    if not 1 <= slot <= 9:
        await update.message.reply_text("❌ الرقم يجب أن يكون من 1 إلى 9."); return
    if slot in streams:
        await update.message.reply_text(f"⚠️ البث {slot} يعمل بالفعل. استخدم /stop {slot}")
        return
    sessions[update.effective_user.id] = {"slot":slot,"step":"key"}
    await update.message.reply_text(f"📡 بدء البث رقم {slot}\n\nأرسل Facebook Stream Key 🔑")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in sessions: return
    text = update.message.text.strip()
    s = sessions[uid]
    if s["step"] == "key":
        if not text:
            await update.message.reply_text("❌ Stream Key غير صالح."); return
        s["key"] = text; s["step"] = "source"
        await update.message.reply_text(f"✅ تم استلام المفتاح للبث {s['slot']}.\n\nأرسل رابط المصدر فقط 🔗")
        return
    slot, key, source = s["slot"], s["key"], text
    await update.message.reply_text(f"⏳ جاري تشغيل البث {slot}...")
    try:
        p = start_ffmpeg(source, key)
        await asyncio.sleep(3)
        if p.poll() is not None:
            err = ""
            if p.stderr:
                try: err = p.stderr.read().decode("utf-8","ignore")[-1500:]
                except Exception: pass
            sessions.pop(uid,None)
            await update.message.reply_text(f"❌ فشل البث {slot}.\n\n{err or 'FFmpeg توقف مباشرة.'}")
            return
        streams[slot] = {"process":p,"started":datetime.now(),"source":source,"user_id":uid}
        sessions.pop(uid,None)
        await update.message.reply_text(f"🟢 البث {slot} يعمل الآن.\n\nإيقاف: /stop {slot}\nالحالة: /live")
    except Exception as e:
        sessions.pop(uid,None)
        await update.message.reply_text(f"❌ خطأ: {e}")

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("استخدم /stop 1 إلى /stop 9"); return
    try: slot = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ الرقم يجب أن يكون من 1 إلى 9."); return
    if not 1 <= slot <= 9:
        await update.message.reply_text("❌ الرقم يجب أن يكون من 1 إلى 9."); return
    item = streams.get(slot)
    if not item:
        await update.message.reply_text(f"🔴 البث {slot} غير مشغل."); return
    p = item["process"]
    try:
        p.terminate(); p.wait(timeout=10)
    except Exception:
        try: p.kill()
        except Exception: pass
    streams.pop(slot,None)
    await update.message.reply_text(f"⛔ تم إيقاف البث {slot}.")

async def live_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    out = "📡 حالة البثوث 1-9\n\n"
    for slot in range(1,10):
        item = streams.get(slot)
        if not item:
            out += f"{slot} 🔴 متوقف\n"; continue
        if item["process"].poll() is not None:
            streams.pop(slot,None); out += f"{slot} 🔴 انتهى\n"; continue
        out += f"{slot} 🟢 Live — {duration(item['started'])}\n"
    await update.message.reply_text(out)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start 1 إلى /start 9 — بدء بث\n/stop 1 إلى /stop 9 — إيقاف بث\n/live — الحالة\n/help — المساعدة")

async def monitor():
    while True:
        for slot,item in list(streams.items()):
            if item["process"].poll() is not None: streams.pop(slot,None)
        await asyncio.sleep(10)

async def post_init(app):
    asyncio.create_task(monitor())

def main():
    if not BOT_TOKEN: raise RuntimeError("BOT_TOKEN environment variable is missing.")
    if not ffmpeg_ok(): raise RuntimeError("FFmpeg is not installed.")
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",start_cmd))
    app.add_handler(CommandHandler("stop",stop_cmd))
    app.add_handler(CommandHandler("live",live_cmd))
    app.add_handler(CommandHandler("help",help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_handler))
    app.run_polling()

if __name__ == "__main__": main()
