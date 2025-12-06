import os
import logging
import traceback
import sys
from aiohttp import web
from pyrogram import Client

# Logging setup to show logs IMMEDIATELY
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
DEFAULT_CHAT_ID = int(os.environ.get("CHANNEL_ID", "-1003266040653"))
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 1024 * 1024)) 

app = Client("beuhub_streamer", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- Helpers ---
def parse_range(range_header: str, file_size: int):
    if not range_header:
        return 0, file_size - 1
    try:
        r = range_header.strip().lower()
        if not r.startswith("bytes="):
            return 0, file_size - 1
        r = r.replace("bytes=", "")
        start_str, end_str = r.split("-", 1)
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
        start = max(0, start)
        end = min(end, file_size - 1)
        return start, end
    except:
        return 0, file_size - 1

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
    
    logger.info(f"⬇️ Starting download loop for bytes {start}-{end}")

    try:
        # Debug: Count chunks
        chunk_count = 0
        async for chunk in app.download_media(
            message,
            offset=start,
            limit=length,
            chunk_size=CHUNK_SIZE,
            in_memory=True 
        ):
            await resp.write(chunk)
            chunk_count += 1
            if chunk_count % 5 == 0:
                logger.info(f"✅ Served {chunk_count} chunks...")
                
    except Exception as e:
        logger.error(f"❌ Streaming interrupted: {e}")
    finally:
        await resp.write_eof()
        logger.info("🏁 Streaming finished")

    return resp

# --- Routes ---
async def home(request):
    return web.Response(text="BEUHub MTProto Streamer Running ✓")

async def stream_handler(request):
    # Log immediately when request hits
    logger.info(f"🔔 REQUEST HIT: {request.rel_url}")
    
    try:
        segments = [s for s in request.rel_url.path.split("/") if s]
        
        if len(segments) == 2: 
            chat_id = DEFAULT_CHAT_ID
            message_id = int(segments[1])
        elif len(segments) >= 3: 
            chat_id = int(segments[1])
            message_id = int(segments[2])
        else:
            return web.Response(status=400, text="Invalid URL")

        logger.info(f"🔎 Looking for Chat: {chat_id}, Msg: {message_id}")

        # Fetch Message
        try:
            message = await app.get_messages(int(chat_id), int(message_id))
        except Exception as e:
            logger.error(f"❌ Error fetching message from Telegram: {e}")
            return web.Response(status=500, text=f"Telegram Error: {e}")

        if not message:
            logger.error("❌ Message is None (Bot cannot see it)")
            return web.Response(status=404, text="Message Not Found")
            
        logger.info("✅ Message found! Extracting media...")

        media, file_size, mime_type, file_name = get_media_details(message)
        
        if not media:
            logger.error("❌ No media found in message")
            return web.Response(status=404, text="No Media")

        logger.info(f"🎥 Media: {file_name} | Size: {file_size}")

        start, end = parse_range(request.headers.get("Range"), file_size)
        return await stream_message(request, message, media, file_size, mime_type, file_name, start, end)

    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"❌ CRITICAL HANDLER ERROR: {e}\n{tb}")
        return web.Response(status=500, text=f"Server Error:\n{tb}")

# --- Init ---
async def init_app():
    await app.start()
    logger.info("🤖 Pyrogram Client Started Successfully")
    server = web.Application()
    server.add_routes([
        web.get("/", home),
        web.get("/stream/{id:.*}", stream_handler),
    ])
    return server

def main():
    port = int(os.environ.get("PORT", 8080))
    web.run_app(init_app(), host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
