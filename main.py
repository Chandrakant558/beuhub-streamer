import os
import logging
import traceback
import sys
from aiohttp import web
from pyrogram import Client, filters

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("beuhub_streamer")

# --- CONFIG ---
API_ID = int(os.environ.get("API_ID", "33833846"))
API_HASH = os.environ.get("API_HASH", "08293ed11f6189993b0337b852ed1446")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8532091150:AAETyfRm0InvlHa-f4sFhdDB4y5_E5ZV8q4")

app = Client("beuhub_streamer", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

# --- Helpers ---
def get_media_details(message):
    media = message.video or message.document or message.audio
    if media:
        return (
            media, 
            getattr(media, "file_size", 0), 
            getattr(media, "mime_type", "application/octet-stream"), 
            getattr(media, "file_name", "video.mp4")
        )
    return None, 0, None, None

def parse_range(range_header, file_size):
    if not range_header: return 0, file_size - 1
    try:
        r = range_header.strip().lower().replace("bytes=", "")
        start_str, end_str = r.split("-", 1)
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
        return max(0, start), min(end, file_size - 1)
    except:
        return 0, file_size - 1

async def stream_message(request, message, media, file_size, mime_type, file_name, start, end):
    length = end - start + 1
    headers = {
        "Content-Type": mime_type,
        "Content-Length": str(length),
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Disposition": f'inline; filename="{file_name}"',
    }
    resp = web.StreamResponse(status=206, headers=headers)
    await resp.prepare(request)
    
    try:
        async for chunk in app.download_media(message, offset=start, limit=length, chunk_size=720*1280, in_memory=True):
            await resp.write(chunk)
    except Exception as e:
        logger.error(f"Stream Error: {e}")
    finally:
        await resp.write_eof()
    return resp

# --- Routes ---
async def stream_handler(request):
    try:
        segments = [s for s in request.rel_url.path.split("/") if s]
        if len(segments) < 3: 
            return web.Response(text="Use format: /stream/CHAT_ID_OR_USERNAME/MESSAGE_ID", status=400)
        
        # --- FIX: Handle both Integer ID and String Username ---
        raw_chat_id = segments[1]
        try:
            chat_id = int(raw_chat_id) # Agar number hai to int banao
        except ValueError:
            chat_id = raw_chat_id      # Agar naam (username) hai to string rehne do

        try:
            message_id = int(segments[2])
        except ValueError:
            return web.Response(text="Message ID must be a number", status=400)

        logger.info(f"🔎 Requesting Chat: {chat_id}, Msg: {message_id}")

        try:
            message = await app.get_messages(chat_id, message_id)
        except Exception as e:
            logger.error(f"Fetch Failed: {e}")
            return web.Response(text=f"Telegram Error: {e}", status=500)

        if not message: return web.Response(text="Message Not Found", status=404)

        media, file_size, mime_type, file_name = get_media_details(message)
        if not media: return web.Response(text="Not a Video", status=404)

        start, end = parse_range(request.headers.get("Range"), file_size)
        return await stream_message(request, message, media, file_size, mime_type, file_name, start, end)

    except Exception as e:
        return web.Response(text=f"Server Error: {traceback.format_exc()}", status=500)

async def init_app():
    await app.start()
    logger.info("🤖 Bot Started!")
    app_web = web.Application()
    app_web.add_routes([
        web.get("/", lambda r: web.Response(text="Server Running")),
        web.get("/stream/{chat_id}/{message_id}", stream_handler)
    ])
    return app_web

def main():
    web.run_app(init_app(), host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    main()

