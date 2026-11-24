# -*- coding: utf-8 -*-
# بوت ثعلوبي AI - بوت عام
import os
import re
import json
import time
import asyncio
import logging
import tempfile
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer

import pandas as pd
import google.generativeai as genai
try:
    from google.api_core.exceptions import ResourceExhausted
except ImportError:
    class ResourceExhausted(Exception):
        pass
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes,
)

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger("thaaloby-bot")


# ------------------------------------------------------------------
# Keep-alive (Render): بيرد على GET و HEAD
# ------------------------------------------------------------------
def keep_alive():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"AI Bot is alive")

        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


threading.Thread(target=keep_alive, daemon=True).start()

# ------------------------------------------------------------------
# الإعدادات
# ------------------------------------------------------------------
TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")

# اختياري: IDs المسموحة (مفصولة بفاصلة). فاضي = الكل مسموح.
ALLOWED = {
    int(x) for x in os.environ.get("ALLOWED_USER_IDS", "").replace(" ", "").split(",")
    if x.isdigit()
}

MAX_PROMPT_CHARS = 60000   # أقصى حجم نص بيتبعت للموديل
MAX_FILE_MB = 15           # حد أمان للملفات والصور (تليجرام بيسمح لحد 20MB)
MAX_HISTORY = 20           # عدد رسايل المحادثة المحفوظة لكل مستخدم (سؤال + رد = 2)

SYSTEM = """
انت مساعد ذكاء اصطناعي عام، شاطر وذكي وبتتكلم بالعربي المصري البسيط والواضح.
بتساعد في أي حاجة:
- تشرح أي موضوع صعب بطريقة سهلة
- تكتب مقالات، بوستات، رسائل، ايميلات، سيرة ذاتية
- تحل مسائل رياضة وفيزياء وبرمجة
- تحلل ملفات Excel و CSV و JSON و PDF والصور وتطلع منها ملخصات وأرقام مهمة
- تترجم لأي لغة
- تعمل أفكار لمشاريع، محتوى، بيزنس
- تنصح وتدي رأي عملي
لو المستخدم بعت ملف، حلله بعمق وطلع أهم النقاط والأرقام والنصايح، واعتمد على الأرقام الموجودة بس.
لو مش متأكد من حاجة، قول مش متأكد.
خليك دايما عملي ومختصر ومفيد، من غير رغي.
"""

FALLBACK_MODEL = os.environ.get("GEMINI_FALLBACK_MODEL", "")
RPM = int(os.environ.get("GEMINI_RPM", "4"))  # الحد المجاني 5 في الدقيقة، بنسيب هامش

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

_models = {}


def get_model(name):
    if name not in _models:
        _models[name] = genai.GenerativeModel(name, system_instruction=SYSTEM)
    return _models[name]


model = get_model(MODEL_NAME) if GEMINI_KEY else None

# تنظيم معدل الطلبات: مش هنبعت أكتر من RPM طلب في الدقيقة للمشروع كله
_rate_lock = asyncio.Lock()
_calls = deque()


async def throttle():
    async with _rate_lock:
        now = time.monotonic()
        while _calls and now - _calls[0] >= 60:
            _calls.popleft()
        if len(_calls) >= RPM:
            await asyncio.sleep(60 - (now - _calls[0]) + 0.5)
            now = time.monotonic()
            while _calls and now - _calls[0] >= 60:
                _calls.popleft()
        _calls.append(time.monotonic())


def retry_delay(msg: str) -> float:
    m = re.search(r"retry in ([\d.]+)s", msg) or re.search(r"seconds:\s*(\d+)", msg)
    return float(m.group(1)) if m else 30.0


async def generate_with_retry(contents):
    """بيرجع (نجح؟، النص). بيستنى ويعيد المحاولة لو الكوتا خلصت، وبيجرب موديل بديل لو متظبط."""
    names = [MODEL_NAME]
    if FALLBACK_MODEL and FALLBACK_MODEL != MODEL_NAME:
        names.append(FALLBACK_MODEL)
    last_err = None
    for attempt in range(2):
        for name in names:
            await throttle()
            try:
                resp = await get_model(name).generate_content_async(contents)
                try:
                    return True, resp.text
                except ValueError:
                    return False, "الذكاء الاصطناعي ما رجعش رد (ممكن يكون اتحجب). جرب صياغة تانية."
            except ResourceExhausted as e:
                last_err = e
                log.warning("Quota hit on %s", name)
            except Exception as e:
                log.exception("Gemini error")
                return False, f"فيه مشكلة في الذكاء الاصطناعي: {e}"
        msg = str(last_err)
        if "PerDay" in msg:
            return False, "الحد اليومي المجاني لـ Gemini خلص. جرب بكرة أو فعّل الفوترة في Google AI Studio."
        delay = retry_delay(msg)
        if attempt == 0 and delay <= 90:
            await asyncio.sleep(delay + 1)
            continue
        break
    return False, "البوت وصل للحد المجاني لعدد الطلبات في الدقيقة. استنى دقيقة وابعت تاني."

# ذاكرة المحادثة (في الرام، بتتمسح مع إعادة التشغيل)
HISTORY: dict[int, list[tuple[str, str]]] = {}


# ------------------------------------------------------------------
# أدوات مساعدة
# ------------------------------------------------------------------
async def ask_ai(user_id: int, text: str, media=None, remember: str | None = None) -> str:
    """بيبعت للموديل مع تاريخ المحادثة. media = قايمة {mime_type, data} للصور و PDF."""
    if not model:
        return "مفتاح Gemini مش موجود. حط GEMINI_API_KEY في Render واعمل Redeploy."

    hist = HISTORY.setdefault(user_id, [])
    parts = [text[:MAX_PROMPT_CHARS]] + list(media or [])
    contents = [{"role": r, "parts": [t]} for r, t in hist]
    contents.append({"role": "user", "parts": parts})

    ok, answer = await generate_with_retry(contents)
    if not ok:
        return answer

    hist.append(("user", (remember or text)[:6000]))
    hist.append(("model", answer[:6000]))
    del hist[:-MAX_HISTORY]
    return answer


async def send_long(update: Update, text: str):
    """تليجرام بيقبل 4096 حرف بس، فبنقسم عند آخر سطر جديد."""
    text = (text or "").strip() or "(مفيش رد)"
    while text:
        if len(text) <= 4000:
            chunk, text = text, ""
        else:
            cut = text.rfind("\n", 0, 4000)
            if cut < 1000:
                cut = 4000
            chunk, text = text[:cut], text[cut:].lstrip("\n")
        await update.message.reply_text(chunk)


def is_allowed(update: Update) -> bool:
    if not ALLOWED:
        return True
    user = update.effective_user
    return bool(user and user.id in ALLOWED)


async def deny(update: Update):
    await update.message.reply_text("مش مصرحلك تستخدم البوت ده. ابعت /id وادي الرقم للمسؤول.")


# ------------------------------------------------------------------
# قراءة وتلخيص الملفات
# ------------------------------------------------------------------
def read_text_file(path: str) -> str:
    with open(path, encoding="utf-8-sig", errors="ignore") as f:
        return f.read()


def load_csv(path: str) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp1256", "latin-1"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue


def summarize_df(df: pd.DataFrame, name: str) -> str:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # أعمدة أرقام متخزنة كنص (فيها فواصل)
    for c in df.select_dtypes(include="object").columns:
        conv = pd.to_numeric(df[c].astype(str).str.replace(",", "", regex=False), errors="coerce")
        if conv.notna().mean() > 0.9:
            df[c] = conv

    cols = list(df.columns)[:60]
    sub = df[cols]
    L = [f"## {name}: {len(df)} صف × {df.shape[1]} عمود"]
    L.append("الأعمدة: " + ", ".join(f"{c} ({sub[c].dtype})" for c in cols))

    nulls = sub.isna().sum()
    nulls = nulls[nulls > 0]
    if len(nulls):
        L.append("قيم فاضية:\n" + nulls.to_string())

    dups = int(df.duplicated().sum())
    if dups:
        L.append(f"صفوف مكررة بالكامل: {dups}")

    L.append("أول 5 صفوف:\n" + sub.head(5).to_string())

    num = sub.select_dtypes(include="number")
    if not num.empty:
        num = num.iloc[:, :25]
        stats = num.describe().T
        stats["sum"] = num.sum()
        L.append("إحصائيات الأرقام:\n" + stats.round(2).to_string())

    # توزيعات الأعمدة النصية القليلة التنوع
    shown = 0
    for c in sub.select_dtypes(include="object").columns:
        n = sub[c].nunique(dropna=True)
        if 0 < n <= 50 and shown < 10:
            L.append(f"توزيع {c}:\n" + sub[c].value_counts().head(8).to_string())
            shown += 1

    # أعمدة تواريخ (بالاسم)
    for c in cols:
        if any(k in str(c).lower() for k in ("date", "تاريخ")):
            d = pd.to_datetime(sub[c], errors="coerce")
            if d.notna().mean() > 0.5:
                m = d.dt.to_period("M").astype(str).value_counts().sort_index()
                L.append(f"توزيع {c} حسب الشهر:\n" + m.to_string())
                break

    return "\n\n".join(L)


def summarize_table_file(path: str, fname: str) -> str:
    if fname.endswith(".csv"):
        return summarize_df(load_csv(path), "CSV")
    sheets = pd.read_excel(path, sheet_name=None)
    parts = [summarize_df(df, f"شيت {name}") for name, df in list(sheets.items())[:5]]
    if len(sheets) > 5:
        parts.append(f"(فيه {len(sheets) - 5} شيت تانية مش معروضة)")
    return "\n\n".join(parts)


def summarize_text_file(path: str, fname: str) -> str:
    txt = read_text_file(path)
    if fname.endswith(".json"):
        try:
            txt = json.dumps(json.loads(txt), ensure_ascii=False, separators=(",", ":"))
        except json.JSONDecodeError:
            pass  # نبعته كنص عادي
    if len(txt) > 40000:
        txt = txt[:40000] + "\n...[الملف اتقص لأنه طويل]"
    return txt


# ------------------------------------------------------------------
# الأوامر والـ Handlers
# ------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await deny(update)
    await update.message.reply_text(
        "أهلا بيك في بوت ثعلوبي AI 🤖\n\n"
        "أنا مساعدك الذكي. اسألني أي حاجة أو ابعتلي:\n"
        "- نص أو سؤال\n"
        "- صورة (وممكن تكتب تعليق بالمطلوب)\n"
        "- ملف Excel / CSV / JSON / TXT / PDF\n\n"
        "ممكن:\n"
        "- اشرحلي أي درس\n"
        "- اكتبلي بوست\n"
        "- حللي ملف Excel\n"
        "- ترجملي ده\n"
        "- اعملي خطة لمشروع\n\n"
        "أوامر: /reset لمسح المحادثة، /id لمعرفة الـ ID بتاعك."
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    HISTORY.pop(update.effective_user.id, None)
    await update.message.reply_text("مسحت المحادثة، نبدأ من جديد ✨")


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"الـ ID بتاعك: {update.effective_user.id}")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await deny(update)
    await update.message.chat.send_action(ChatAction.TYPING)
    ans = await ask_ai(update.effective_user.id, update.message.text or "")
    await send_long(update, ans)


async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await deny(update)
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        p = update.message.photo[-1]  # أكبر نسخة
        f = await p.get_file()
        data = bytes(await f.download_as_bytearray())
        caption = update.message.caption or "اشرحلي الصورة دي وقولي أهم حاجة فيها."
        ans = await ask_ai(
            update.effective_user.id, caption,
            media=[{"mime_type": "image/jpeg", "data": data}],
            remember=f"[المستخدم بعت صورة] {caption}",
        )
        await send_long(update, ans)
    except Exception as e:
        log.exception("Photo error")
        await update.message.reply_text(f"فيه مشكلة في الصورة: {e}")


async def doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return await deny(update)

    d = update.message.document
    fname = (d.file_name or "").lower()
    uid = update.effective_user.id
    instruction = update.message.caption  # لو كتب طلب مع الملف

    if d.file_size and d.file_size > MAX_FILE_MB * 1024 * 1024:
        return await update.message.reply_text(f"الملف أكبر من {MAX_FILE_MB}MB. ابعت ملف أصغر.")
    if not fname.endswith((".xlsx", ".xls", ".csv", ".json", ".txt", ".pdf")):
        return await update.message.reply_text("بقبل: XLSX / XLS / CSV / JSON / TXT / PDF.")

    await update.message.reply_text("وصلني الملف، بحلله ⏳")
    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        f = await d.get_file()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "upload" + os.path.splitext(fname)[1])
            await f.download_to_drive(custom_path=path)

            if fname.endswith(".pdf"):
                with open(path, "rb") as fh:
                    data = fh.read()
                prompt = instruction or "لخص الملف ده وطلع أهم النقاط والأرقام."
                ans = await ask_ai(
                    uid, prompt,
                    media=[{"mime_type": "application/pdf", "data": data}],
                    remember=f"[المستخدم بعت PDF: {d.file_name}] {prompt}",
                )
                return await send_long(update, ans)

            if fname.endswith((".xlsx", ".xls", ".csv")):
                content = await asyncio.to_thread(summarize_table_file, path, fname)
                kind = "ملخص اتحسب بالكود لملف جداول"
                default = "اعمل تحليل عميق: أهم الأرقام والأنماط والملاحظات وأي مشاكل في البيانات ونصايح عملية."
            else:
                content = await asyncio.to_thread(summarize_text_file, path, fname)
                kind = "محتوى ملف"
                default = "حلل الملف ده وطلع أهم النقاط."

        prompt = f"{instruction or default}\n\n{kind} ({d.file_name}):\n{content}"
        ans = await ask_ai(uid, prompt, remember=prompt[:6000])
        await send_long(update, ans)

    except Exception as e:
        log.exception("File error")
        await update.message.reply_text(f"فيه مشكلة في الملف: {e}")


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled error", exc_info=context.error)


def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN مش متظبط في Environment Variables")
    app = (
        Application.builder()
        .token(TOKEN)
        .concurrent_updates(True)
        .read_timeout(60)
        .write_timeout(60)
        .connect_timeout(30)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("id", my_id))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    app.add_handler(MessageHandler(filters.PHOTO, photo))
    app.add_handler(MessageHandler(filters.Document.ALL, doc))
    app.add_error_handler(on_error)
    log.info("Thaaloby AI Bot Running...")
    app.run_polling()


if __name__ == "__main__":
    main()
