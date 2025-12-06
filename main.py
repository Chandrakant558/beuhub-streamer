# main.py
import os
import logging
import traceback
from aiohttp import web
from pyrogram import Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("beuhub_streamer")

# --- CONFIG ---
API_ID = int(os.environ.get("API_ID", "33833846"))
API_HASH = os.environ.get("API_HASH", "08293ed11f6189993b0337b852ed1446")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8532091150:AAETyfRm0InvlHa-f4sFhdDB4y5_E5ZV8q4")
DEFAULT_CHAT_ID = int(os.environ.get("CHANNEL_ID", "-1003266040653"))
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 1024 * 1024))
USE_IN_MEMORY = os.environ.get("USE_IN_MEMORY", "true").lower() == "true"

# Pyrogram client
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
        if start > end:
            start, end = 0, file_size - 1
        return start, end
    except:
        return 0, file_size - 1

async def stream_message(message, request, start: int, end: int):
    length = end - start + 1
    headers = {
        "Content-Type": getattr(message, "mime_type", "application/octet-stream"),
        "Content-Length": str(length),
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {start}-{end}/{message.file_size or 0}",
        "Content-Disposition": f'inline; filename="{getattr(message, "file_name", "file")}"',
    }
    resp = web.StreamResponse(status=206, headers=headers)
    await resp.prepare(request)

    try:
        async for chunk in app.download_media(
            message,
            offset=start,
            limit=length,
            in_memory=USE_IN_MEMORY,
            chunk_size=CHUNK_SIZE,
        ):
            await resp.write(chunk)
    except Exception as e:
        logger.exception("Streaming error: %s", e)
    finally:
        await resp.write_eof()

    return resp

async def get_message(chat_id, message_id):
    return await app.get_messages(int(chat_id), int(message_id))

# --- Routes ---
async def home(request):
    return web.Response(text="BEUHub MTProto Streamer Running ✓")

async def stream_handler(request):
    try:
        segments = [s for s in request.rel_url.path.split("/") if s]
        if len(segments) < 2:
            return web.Response(status=400, text="Missing message id")
        # Path: /stream/{chat_id}/{message_id} or /stream/{message_id}
        if len(segments) == 2:
            chat_id = DEFAULT_CHAT_ID
            message_id = int(segments[1])
        else:
            chat_id = int(segments[1])
            message_id = int(segments[2])

        message = await get_message(chat_id, message_id)
        if not message or not message.media:
            return web.Response(status=404, text="Message or media not found")

        start, end = parse_range(request.headers.get("Range"), message.file_size or 0)
        return await stream_message(message, request, start, end)

    except Exception as e:
        tb = traceback.format_exc()
        logger.exception("Stream handler error: %s", e)
        return web.Response(status=500, text=f"Server error:\n{tb}")

# --- App Initialization ---
async def init_app():
    await app.start()
    logger.info("Pyrogram client started")
    server = web.Application()
    server.add_routes([
        web.get("/", home),
        web.get("/stream/{id:.*}", stream_handler),
    ])
    return server

def main():
    web.run_app(init_app(), host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    main()
