import os
import asyncio
import tempfile
import subprocess
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import (
Application,
CommandHandler,
MessageHandler,
ContextTypes,
filters,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(name)

TOKEN = os.environ.get("BOT_TOKEN")

if not TOKEN:
raise RuntimeError("يرجى ضبط متغير BOT_TOKEN في إعدادات الاستضافة")

MAX_FILE_SIZE = 20 * 1024 * 1024
SUPPORTED = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4"}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.message.reply_text(
"🎤 أهلاً بك في بوت الكاريوكي!\n\n"
"أرسل أغنية كملف صوتي أو فيديو، وسأحاول فصل صوت المغني عن الموسيقى.\n"
"🎵 سأرسل لك نسخة الموسيقى فقط.\n\n"
"ملاحظة: قد تستغرق الأغاني الطويلة وقتاً، "
"وقد تفشل المعالجة إذا لم تتوفر ذاكرة كافية."
)

async def process_song(update: Update, context: ContextTypes.DEFAULT_TYPE):
message = update.effective_message

media = message.document or message.audio or message.video

if not media:
    await message.reply_text("❌ أرسل الأغنية كملف صوتي أو فيديو.")
    return

filename = getattr(media, "file_name", None) or "song.mp3"
ext = Path(filename).suffix.lower()

if ext not in SUPPORTED:
    await message.reply_text(
        "❌ صيغة الملف غير مدعومة. أرسل MP3 أو WAV أو M4A أو FLAC أو MP4."
    )
    return

if media.file_size and media.file_size > MAX_FILE_SIZE:
    await message.reply_text(
        "❌ حجم الملف أكبر من 20 ميغابايت. أرسل ملفاً أصغر."
    )
    return

status = await message.reply_text(
    "⏳ استلمت الأغنية. جارٍ تجهيزها للكاريوكي..."
)

try:
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        input_path = work / f"input{ext}"
        output_dir = work / "output"
        output_dir.mkdir()

        telegram_file = await media.get_file()
        await telegram_file.download_to_drive(custom_path=str(input_path))

        await status.edit_text(
            "🎵 جارٍ فصل صوت المغني عن الموسيقى. قد تستغرق العملية وقتاً..."
        )

        command = [
            "python", "-m", "demucs",
            "--two-stems", "vocals",
            "-n", "htdemucs",
            "--out", str(output_dir),
            str(input_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(), timeout=3600
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            await status.edit_text(
                "⌛ استغرقت المعالجة أكثر من ساعة. جرّب أغنية أقصر."
            )
            return

        if process.returncode != 0:
            log.error("Demucs failed: %s", (stdout or b"").decode(
                errors="replace"
            )[-4000:])
            await status.edit_text(
                "❌ تعذرت معالجة الأغنية. قد تكون ذاكرة السيرفر غير كافية."
            )
            return

        instrumental_files = list(output_dir.rglob("no_vocals.wav"))

        if not instrumental_files:
            await status.edit_text("❌ لم أجد ملف الموسيقى الناتج.")
            return

        result_path = instrumental_files[0]

        await status.edit_text("📤 اكتملت المعالجة! جارٍ إرسال الموسيقى...")

        with result_path.open("rb") as audio:
            await message.reply_document(
                document=audio,
                filename="karaoke.wav",
                caption="🎤 تفضل! الموسيقى بدون صوت المغني."
            )

        await status.edit_text("✅ انتهت العملية بنجاح!")

except Exception:
    log.exception("Song processing failed")
    await status.edit_text(
        "❌ حدث خطأ أثناء المعالجة. جرّب ملفاً آخر أو أغنية أقصر."
    )

def main():
app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(
    MessageHandler(
        filters.AUDIO | filters.Document.ALL | filters.VIDEO,
        process_song,
    )
)

app.run_polling()

if name == "main":
main()
