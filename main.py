# -*- coding: utf-8 -*-
# بوت ثعلوبي AI - بوت عام
import os, threading, asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer

def keep_alive():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"AI Bot is alive")
        def log_message(self, *args): pass
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
threading.Thread(target=keep_alive, daemon=True).start()

import pandas as pd
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai

TOKEN = os.environ.get("BOT_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")
else:
    model = None

SYSTEM = """
انت مساعد ذكاء اصطناعي عام، شاطر وذكي وبتتكلم بالعربي المصري البسيط والواضح.
بتساعد في أي حاجة:
- تشرح أي موضوع صعب بطريقة سهلة
- تكتب مقالات، بوستات، رسائل، ايميلات، سيرة ذاتية
- تحل مسائل رياضة وفيزياء وبرمجة
- تحلل ملفات Excel و CSV و JSON وتطلع منها ملخصات وأرقام مهمة
- تترجم لأي لغة
- تعمل أفكار لمشاريع، محتوى، بيزنس
- تنصح وتدي رأي عملي
لو المستخدم بعت ملف، حلله بعمق وطلع أهم النقاط والأرقام والنصايح.
لو مش متأكد من حاجة، قول مش متأكد.
خليك دايما عملي ومختصر ومفيد، من غير رغي.
"""

async def ask_ai(text):
    if not model:
        return "مفتاح Gemini مش موجود. حط GEMINI_API_KEY في Render."
    try:
        r = model.generate_content(SYSTEM + "\n\nالمستخدم بعت:\n" + text[:15000])
        return r.text
    except Exception as e:
        return f"فيه مشكلة: {e}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلا بيك في بوت ثعلوبي AI 🤖\n\n"
        "أنا مساعدك الذكي الجديد.\n"
        "اسألني أي حاجة، ابعتلي أي ملف، أي صورة، أي فكرة.\n\n"
        "ممكن:\n"
        "- اشرحلي أي درس\n"
        "- اكتبلي بوست\n"
        "- حللي ملف Excel\n"
        "- ترجملي ده\n"
        "- اعملي خطة لمشروع\n\n"
        "ابعتلي دلوقتي انت عايز ايه؟"
    )

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("بفكر... ثواني 🤔")
    ans = await ask_ai(update.message.text)
    for i in range(0, len(ans), 4000):
        await update.message.reply_text(ans[i:i+4000])

async def doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = update.message.document
    fname = (d.file_name or "").lower()
    f = await d.get_file()
    await update.message.reply_text("وصلني الملف، بحلله بالذكاء الاصطناعي ⏳")
    try:
        if fname.endswith(".json") or fname.endswith(".txt") or fname.endswith(".csv"):
            await f.download_to_drive("in.txt")
            with open("in.txt", encoding="utf-8", errors="ignore") as fh:
                txt = fh.read()
            ans = await ask_ai(f"حلل الملف ده بالكامل وطلع أهم النقاط:\n{txt}")
            for i in range(0, len(ans), 4000):
                await update.message.reply_text(ans[i:i+4000])
            return
        await f.download_to_drive("in.xlsx")
        df = pd.read_excel("in.xlsx")
        summary = f"عدد الصفوف: {len(df)}\nالأعمدة: {list(df.columns)}\n\n"
        summary += "أول 5 صفوف:\n" + df.head(5).to_string() + "\n\n"
        summary += "وصف الأرقام:\n" + df.describe(include='all').to_string() + "\n"
        ans = await ask_ai(f"اعمل تحليل عميق كامل لملف Excel ده:\n{summary}")
        for i in range(0, len(ans), 4000):
            await update.message.reply_text(ans[i:i+4000])
    except Exception as e:
        await update.message.reply_text(f"فيه مشكلة في الملف: {e}")

def main():
    asyncio.set_event_loop(asyncio.new_event_loop())
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    app.add_handler(MessageHandler(filters.Document.ALL, doc))
    print("Thaaloby AI Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
