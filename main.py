# main.py
import os
import asyncio
import logging
from aiohttp import web
from pyrogram import Client
from pyrogram.errors import RPCError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("beuhub_streamer")

# --- CONFIG (FROM ENV) ---
# Defaults provided from user input (recommended: override with env vars in Render)
API_ID = int(os.environ.get("API_ID", "33833846"))
API_HASH = os.environ.get("API_HASH", "08293ed11f6189993b0337b852ed1446")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8532091150:AAETyfRm0InvlHa-f4sFhdDB4y5_E5ZV8q4")
DEFAULT_CHAT_ID = os.environ.get("CHANNEL_ID", str(-1003266040653))  # keep as string
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 1024 * 1024))  # 1MB default
USE_IN_MEMORY = os.environ.get("USE_IN_MEMORY", "false").lower() == "true"
# For large files it's safer to stream from disk (in_memory=False)

if not API_ID or not API_HASH or not BOT_TOKEN:
    logger.error("Missing API_ID / API_HASH / BOT_TOKEN in environment variables.")
    # Requests will be rejected with 500 until correct creds are provided.

# Create Pyrogram client (bot mode)
app = Client(
    "beuhub_streamer",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="/tmp/pyrogram"
)


async def home(request):
    return web.Response(text="BEUHub MTProto Streamer is running ✓")


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
        if start < 0:
            start = 0
        if end >= file_size:
            end = file_size - 1
        if start > end:
            start = 0
            end = file_size - 1
        return start, end
    except Exception:
        return 0, file_size - 1


async def stream_from_message(message, request, start: int, end: int):
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

    # Use in_memory flag based on env setting. For very large files prefer in_memory=False.
    try:
        async for chunk in app.download_media(
            message,
            file_name=None,
            in_memory=USE_IN_MEMORY,   # default false (safer)
            progress=None,
            chunk_size=CHUNK_SIZE,
            offset=start,
            limit=length,
        ):
            if not chunk:
                break
            await resp.write(chunk)
    except Exception as e:
        logger.exception("Error while streaming chunks: %s", e)
        # fallthrough -> attempt to close gracefully
    finally:
        try:
            await resp.write_eof()
        except Exception:
            pass

    return resp


async def get_message_by_id(chat_identifier, message_id):
    try:
        msg = await app.get_messages(chat_identifier, int(message_id))
        return msg
    except Exception as e:
        logger.exception("get_messages failed: %s", e)
        raise


async def stream_handler(request):
    if not BOT_TOKEN or not API_ID or not API_HASH:
        return web.Response(status=500, text="Server misconfigured: missing TELEGRAM credentials")

    raw = request.rel_url.path  # e.g. /stream/-100123/456 or /stream/<id>
    segments = [s for s in raw.split("/") if s]
    try:
        if len(segments) >= 3:
            # /stream/<chat_id>/<message_id>
            chat_id = segments[1]
            message_id = segments[2]
            use_chat = chat_id
            use_msg = message_id
            is_file_id = False
        else:
            use_id = segments[1] if len(segments) >= 2 else None
            if use_id is None:
                return web.Response(status=400, text="Missing id")
            if use_id.isdigit() and DEFAULT_CHAT_ID:
                use_chat = DEFAULT_CHAT_ID
                use_msg = use_id
                is_file_id = False
            else:
                use_chat = None
                use_msg = use_id
                is_file_id = True
    except Exception as e:
        logger.exception("Parsing path failed: %s", e)
        return web.Response(status=400, text="Bad request path")

    try:
        if not is_file_id:
            if not use_chat:
                return web.Response(status=400, text="Missing chat id for message-based streaming")
            logger.info("Fetching message_id=%s from chat=%s", use_msg, use_chat)
            message = await get_message_by_id(use_chat, use_msg)
            if not message or not message.media:
                return web.Response(status=404, text="Message or media not found")
            file_size = message.file_size or 0
            start, end = parse_range(request.headers.get("Range"), file_size)
            return await stream_from_message(message, request, start, end)

        else:
            file_id = use_msg
            logger.info("Streaming by file_id=%s", file_id)
            if DEFAULT_CHAT_ID:
                try:
                    last_msgs = await app.get_history(int(DEFAULT_CHAT_ID), limit=200)
                    found = None
                    for m in last_msgs:
                        try:
                            if getattr(m, "video", None) and m.video.file_id == file_id:
                                found = m; break
                            if getattr(m, "document", None) and m.document.file_id == file_id:
                                found = m; break
                            if getattr(m, "audio", None) and m.audio.file_id == file_id:
                                found = m; break
                        except Exception:
                            continue
                    if not found:
                        return web.Response(status=404, text="file_id not found in recent chat history; save message metadata at upload time")
                    message = found
                    file_size = message.file_size or 0
                    start, end = parse_range(request.headers.get("Range"), file_size)
                    return await stream_from_message(message, request, start, end)
                except Exception as e:
                    logger.exception("Searching for file_id failed: %s", e)
                    return web.Response(status=500, text="Server search error for file_id")
            else:
                return web.Response(status=400, text="file_id streaming requires DEFAULT_CHAT_ID or explicit message reference")

    except RPCError as rpc_e:
        logger.exception("Telegram RPCError: %s", rpc_e)
        return web.Response(status=500, text=f"Telegram RPC Error: {rpc_e}")
    except Exception as e:
        logger.exception("Unhandled exception: %s", e)
        return web.Response(status=500, text=f"Server error: {e}")


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
