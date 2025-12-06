import os
import logging
import sys
import mimetypes
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
API_ID = int(os.environ.get("API_ID", "33833846"))
API_HASH = os.environ.get("API_HASH", "08293ed11f6189993b0337b852ed1446"))
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8532091150:AAETyfRm0InvlHa-f4sFhdDB4y5_E5ZV8q4"))
CHUNK_SIZE = 1024 * 512  # 512KB Chunks (Balance speed)

app = Client("beuhub_streamer", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

async def stream_handler(request):
    try:
        segments = [s for s in request.rel_url.path.split("/") if s]
        if len(segments) < 3: return web.Response(text="Bad URL", status=400)
        
        # ID/Username Handling
        raw_chat = segments[1]
        try:
            chat_id = int(raw_chat)
        except:
            chat_id = raw_chat # Username

        try:
            message_id = int(segments[2])
        except:
            return web.Response(text="Bad Message ID", status=400)

        logger.info(f"⚡ Requesting: {chat_id} / {message_id}")
        
        try:
            message = await app.get_messages(chat_id, message_id)
        except Exception as e:
            logger.error(f"Telegram Error: {e}")
            return web.Response(text=f"Error: {e}", status=500)

        if not message: return web.Response(text="Message Not Found", status=404)
        
        media = message.video or message.document or message.audio
        if not media: return web.Response(text="No Media Found", status=404)

        file_size = getattr(media, "file_size", 0)
        # Force MP4 mime type agar detect na ho
        mime_type = getattr(media, "mime_type", "video/mp4") 
        file_name = getattr(media, "file_name", "video.mp4")

        # HEADER FOR DIRECT PLAY (Status 200)
        headers = {
            "Content-Type": mime_type,
            "Content-Length": str(file_size),
            "Content-Disposition": f'inline; filename="{file_name}"',
            "Connection": "keep-alive"
        }

        # Status 200 OK (Not 206)
        resp = web.StreamResponse(status=200, headers=headers)
        await resp.prepare(request)

        logger.info("⬇️ Downloading Started...")
        
        # Simple Download Loop
        async for chunk in app.download_media(message, chunk_size=CHUNK_SIZE):
            await resp.write(chunk)
            
        return resp

    except Exception as e:
        logger.error(f"Crash: {e}")
        return web.Response(status=500)

async def init_app():
    await app.start()
    app = web.Application()
    app.add_routes([web.get("/stream/{chat_id}/{message_id}", stream_handler)])
    return app

if __name__ == "__main__":
    web.run_app(init_app(), host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
