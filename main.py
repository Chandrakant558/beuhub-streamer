import os
import logging
import sys
from aiohttp import web
from pyrogram import Client

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("beuhub_streamer")

# --- CONFIG ---
# (Apne variables environment se uthayega)
API_ID = int(os.environ.get("API_ID", "33833846"))
API_HASH = os.environ.get("API_HASH", "08293ed11f6189993b0337b852ed1446")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8532091150:AAETyfRm0InvlHa-f4sFhdDB4y5_E5ZV8q4")

# Chunk Size: 512KB (Balance between Speed and Memory)
CHUNK_SIZE = 1024 * 512

# --- TELEGRAM CLIENT (Iska naam ab 'tg_bot' hai) ---
tg_bot = Client("beuhub_streamer", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

# --- LIFECYCLE HANDLER (Server start hote hi Bot start hoga) ---
async def telegram_engine(app):
    logger.info("🤖 Starting Telegram Bot...")
    await tg_bot.start()
    yield
    logger.info("🛑 Stopping Telegram Bot...")
    await tg_bot.stop()

# --- STREAMING LOGIC ---
async def stream_handler(request):
    try:
        segments = [s for s in request.rel_url.path.split("/") if s]
        if len(segments) < 3: 
            return web.Response(text="Bad URL. Use: /stream/CHAT_ID/MESSAGE_ID", status=400)
        
        # 1. Chat ID / Username nikalo
        raw_chat = segments[1]
        try:
            chat_id = int(raw_chat)
        except ValueError:
            chat_id = raw_chat # Agar username hai (e.g., beuhub_test_123)

        # 2. Message ID nikalo
        try:
            message_id = int(segments[2])
        except ValueError:
            return web.Response(text="Message ID must be a number", status=400)

        logger.info(f"⚡ Request: Chat={chat_id} | Msg={message_id}")

        # 3. Message Fetch karo
        try:
            message = await tg_bot.get_messages(chat_id, message_id)
        except Exception as e:
            logger.error(f"Telegram Error: {e}")
            return web.Response(text=f"Telegram Error: {e}", status=500)

        if not message: 
            return web.Response(text="Message Not Found (Check ID/Permissions)", status=404)
        
        media = message.video or message.document or message.audio
        if not media: 
            return web.Response(text="No Media Found in this message", status=404)

        # 4. File Details
        file_size = getattr(media, "file_size", 0)
        mime_type = getattr(media, "mime_type", "video/mp4") 
        file_name = getattr(media, "file_name", "video.mp4")

        # 5. Response Headers (Direct Play Mode - Status 200)
        headers = {
            "Content-Type": mime_type,
            "Content-Length": str(file_size),
            "Content-Disposition": f'inline; filename="{file_name}"',
            "Connection": "keep-alive"
        }

        resp = web.StreamResponse(status=200, headers=headers)
        await resp.prepare(request)

        # 6. Start Download & Stream
        async for chunk in tg_bot.download_media(message, chunk_size=CHUNK_SIZE):
            await resp.write(chunk)
            
        return resp

    except Exception as e:
        logger.error(f"Server Crash: {e}")
        return web.Response(text="Internal Server Error", status=500)

# --- APP FACTORY ---
async def make_app():
    app = web.Application()
    # Ye line Bot ko safe tareeke se start karegi
    app.cleanup_ctx.append(telegram_engine)
    
    app.add_routes([
        web.get("/", lambda r: web.Response(text="Server Running")),
        web.get("/stream/{chat_id}/{message_id}", stream_handler)
    ])
    return app

# --- MAIN ENTRY POINT ---
if __name__ == "__main__":
    # Render port uthayega
    port = int(os.environ.get("PORT", 8080))
    web.run_app(make_app(), host="0.0.0.0", port=port)
