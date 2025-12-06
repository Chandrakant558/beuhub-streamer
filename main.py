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
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 1024 * 1024))  # <= 1MiB recommended for stream_media

app = Client("beuhub_streamer", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- Helpers ---
def parse_range(range_header: str, file_size: int):
    """
    Returns (start, end, is_partial)
    """
    if not range_header:
        return 0, file_size - 1, False
    try:
        r = range_header.strip().lower()
        if not r.startswith("bytes="):
            return 0, file_size - 1, False
        r = r.replace("bytes=", "")
        start_str, end_str = r.split("-", 1)
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
        start = max(0, start)
        end = min(end, file_size - 1)
        if start > end:
            return 0, file_size - 1, False
        return start, end, not (start == 0 and end == file_size - 1)
    except Exception:
        return 0, file_size - 1, False

def get_media_details(message):
    media = message.video or message.document or message.audio
    if media:
        return (
            media,
            getattr(media, "file_size", 0),
            getattr(media, "mime_type", "application/octet-stream"),
            getattr(media, "file_name", "file.bin")
        )
    return None, 0, None, None

async def stream_message(request, message, file_size, mime_type, file_name, start, end, is_partial):
    length = end - start + 1

    # Prepare headers
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{file_name}"'
    }
    if is_partial:
        headers.update({
            "Content-Type": mime_type,
            "Content-Length": str(length),
            "Content-Range": f"bytes {start}-{end}/{file_size}"
        })
        status = 206
    else:
        headers.update({
            "Content-Type": mime_type,
            "Content-Length": str(file_size)
        })
        status = 200

    # If HEAD request, return headers-only response
    if request.method == "HEAD":
        return web.Response(status=status, headers=headers)

    resp = web.StreamResponse(status=status, headers=headers)
    await resp.prepare(request)

    logger.info(f"⬇️ Starting stream: bytes {start}-{end} (len={length}) for file '{file_name}'")

    chunk_counter = 0
    try:
        # Use Pyrogram's stream_media for chunked streaming (offset/limit in bytes)
        async for chunk in app.stream_media(message, offset=start, limit=length, chunk_size=CHUNK_SIZE):
            if not chunk:
                break
            await resp.write(chunk)
            chunk_counter += 1
            if chunk_counter % 8 == 0:
                logger.info(f"✅ Sent {chunk_counter} chunks ({chunk_counter * CHUNK_SIZE} bytes approx)")
    except Exception as e:
        logger.error(f"❌ Streaming interrupted: {e}")
        logger.error(traceback.format_exc())
    finally:
        try:
            await resp.write_eof()
        except Exception:
            pass
        logger.info(f"🏁 Streaming finished; chunks_sent={chunk_counter}")

    return resp

# --- Routes ---
async def home(request):
    return web.Response(text="BEUHub MTProto Streamer Running ✓")

async def stream_handler(request):
    logger.info(f"🔔 REQUEST HIT: {request.method} {request.rel_url}")

    try:
        # segments: e.g. ['', 'stream', '-1003266040653', '10'] when splitting path
        segments = [s for s in request.rel_url.path.split("/") if s]

        if len(segments) == 2:
            # /stream/<message_id>
            chat_id = DEFAULT_CHAT_ID
            message_id = int(segments[1])
        elif len(segments) >= 3:
            # /stream/<chat_id>/<message_id>
            chat_id = int(segments[1])
            message_id = int(segments[2])
        else:
            return web.Response(status=400, text="Invalid URL")

        logger.info(f"🔎 Looking for Chat: {chat_id}, Msg: {message_id}")

        try:
            message = await app.get_messages(int(chat_id), int(message_id))
        except Exception as e:
            logger.error(f"❌ Error fetching message from Telegram: {e}")
            return web.Response(status=500, text=f"Telegram Error: {e}")

        if not message:
            logger.error("❌ Message not found (bot might not have access)")
            return web.Response(status=404, text="Message Not Found")

        media, file_size, mime_type, file_name = get_media_details(message)
        if not media or file_size == 0:
            logger.error("❌ No media or zero-size media found in message")
            return web.Response(status=404, text="No Media")

        # Parse Range header
        range_header = request.headers.get("Range")
        start, end, is_partial = parse_range(range_header, file_size)

        # Sanity check bounds
        start = max(0, min(start, file_size - 1))
        end = max(start, min(end, file_size - 1))

        logger.info(f"➡️ Serving bytes {start}-{end} (partial={is_partial}) mime={mime_type} size={file_size}")

        return await stream_message(request, message, file_size, mime_type, file_name, start, end, is_partial)

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
        web.get("/stream/{id:.*}", stream_handler),  # Do NOT add a separate web.head(...) route
    ])
    return server

def main():
    port = int(os.environ.get("PORT", 8080))
    web.run_app(init_app(), host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
