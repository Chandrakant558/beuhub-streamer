import os
import logging
import traceback
import sys
from aiohttp import web
from pyrogram import Client, filters

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

# ✅ FIX: Chunk size reduced to 64KB for instant playback
CHUNK_SIZE = 64 * 1024 

app = Client("beuhub_streamer", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

async def stream_message(request, message, file_size, file_name, start, end):
    length = end - start + 1
    headers = {
        "Content-Type": "video/mp4", # Force MP4 for better browser support
        "Content-Length": str(length),
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Disposition": f'inline; filename="{file_name}"',
    }
    resp = web.StreamResponse(status=206, headers=headers)
    await resp.prepare(request)
    
    try:
        # Download in small chunks (64KB)
        async for chunk in app.download_media(message, offset=start, limit=length, chunk_size=CHUNK_SIZE, in_memory=True):
            await resp.write(chunk)
    except Exception as e:
        logger.error(f"Stream Error: {e}")
    finally:
        await resp.write_eof()
    return resp

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

async def stream_handler(request):
    try:
        segments = [s for s in request.rel_url.path.split("/") if s]
        if len(segments) < 3: return web.Response(text="Bad URL", status=400)
        
        chat_id_str = segments[1]
        try:
            chat_id = int(chat_id_str)
        except ValueError:
            chat_id = chat_id_str # Username support

        try:
            message_id = int(segments[2])
        except ValueError:
            return web.Response(text="Bad Message ID", status=400)

        try:
            message = await app.get_messages(chat_id, message_id)
        except Exception as e:
            return web.Response(text=f"Telegram Error: {e}", status=500)

        if not message: return web.Response(text="Message Not Found", status=404)

        media = message.video or message.document
        if not media: return web.Response(text="No Video Found", status=404)

        file_size = getattr(media, "file_size", 0)
        file_name = getattr(media, "file_name", "video.mp4")
        
        start, end = parse_range(request.headers.get("Range"), file_size)
        return await stream_message(request, message, file_size, file_name, start, end)

    except Exception as e:
        return web.Response(text=f"Server Error: {traceback.format_exc()}", status=500)

async def init_app():
    await app.start()
    app_web = web.Application()
    app_web.add_routes([web.get("/stream/{chat_id}/{message_id}", stream_handler)])
    return app_web

def main():
    web.run_app(init_app(), host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    main()
