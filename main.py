# -*- coding: utf-8 -*-
# بوت ثعلوبي AI - من الصفر
import os, threading
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
انت مساعد ذكاء اصطناعي خبير في التأمين الطبي السعودي ونظام نفيس NPHIES.
بتتكلم بالعربي المصري البسيط والعملي.
بتفهم:
- ملفات JSON بتاعة FHIR و ClaimResponse و Organization
- ملفات Excel بتاعة المطالبات فيها اعمدة زي gross, net_amount, discount_amount, patient_share, company_share, vat_amount, payer_name, tpa_name, disposition, adjudication_outcome, response_outcome, request_type, request_subtype, claim_date, policy_holder, accounting_period, cancel_status, statuscode
- أكواد رفض نفيس ومعناها وازاي تصلحها
لو اتبعتلك ملف، حلله بعمق وطلع مجاميع ونسب واعلى مطالبات واسباب رفض ونصايح للفريق.
متكررش الارقام غلط، ولو مش متأكد قول مش متأكد.
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
        "أهلا بيك في بوت ثعلوبي AI 🤖🩺\n\n"
        "أنا بوت ذكاء اصطناعي جديد من الصفر.\n"
        "ابعتلي:\n"
        "1. أي سؤال عن التأمين أو نفيس\n"
        "2. ملف JSON بتاع نفيس\n"
        "3. ملف Excel بتاع المطالبات\n\n"
        "وأنا هفهمه وأحلله لوحدي."
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
        if fname.endswith(".json"):
            await f.download_to_drive("in.json")
            with open("in.json", encoding="utf-8") as fh:
                txt = fh.read()
            ans = await ask_ai(f"حلل ملف JSON ده من نفيس بالكامل:\n{txt}")
            for i in range(0, len(ans), 4000):
                await update.message.reply_text(ans[i:i+4000])
            return
        await f.download_to_drive("in.xlsx")
        df = pd.read_csv("in.xlsx") if fname.endswith(".csv") else pd.read_excel("in.xlsx")
        summary = f"عدد الصفوف: {len(df)}\nالأعمدة: {list(df.columns)}\n\n"
        summary += "أول 5 صفوف:\n" + df.head(5).to_string() + "\n\n"
        summary += "وصف الأرقام:\n" + df.describe(include='all').to_string() + "\n\n"
        for c in ['gross','net_amount','discount_amount','patient_share','company_share','vat_amount']:
            if c in df.columns:
                summary += f"مجموع {c}: {df[c].sum():,.2f}\n"
        for c in ['payer_name','tpa_name','adjudication_outcome','response_outcome','disposition','statuscode','request_type','request_subtype','cancel_status','policy_holder','accounting_period']:
            if c in df.columns:
                summary += f"\nتوزيع {c}:\n" + df[c].value_counts().head(10).to_string() + "\n"
        if 'gross' in df.columns:
            summary += "\nأعلى 5 مطالبات:\n" + df.sort_values(by='gross', ascending=False).head(5).to_string() + "\n"
        ans = await ask_ai(f"اعمل تحليل عميق كامل لملف المطالبات ده:\n{summary}")
        for i in range(0, len(ans), 4000):
            await update.message.reply_text(ans[i:i+4000])
    except Exception as e:
        await update.message.reply_text(f"فيه مشكلة في الملف: {e}")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    app.add_handler(MessageHandler(filters.Document.ALL, doc))
    print("New AI Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
