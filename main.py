# main.py
import os
import logging
import stat
import traceback
from aiohttp import web
from pyrogram import Client
from pyrogram.errors import RPCError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("beuhub_streamer")

# --- CONFIG (FROM ENV or defaults you provided) ---
try:
    API_ID = int(os.environ.get("API_ID", "33833846"))
except Exception:
    API_ID = None
API_HASH = os.environ.get("API_HASH", "08293ed11f6189993b0337b852ed1446")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8532091150:AAETyfRm0InvlHa-f4sFhdDB4y5_E5ZV8q4")
# DEFAULT_CHAT_ID: try parse to int, else None
_default_chat = os.environ.get("CHANNEL_ID")
try:
    DEFAULT_CHAT_ID = int(_default_chat) if _default_chat is not None else None
except Exception:
    DEFAULT_CHAT_ID = None

CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 1024 * 1024))  # 1MB default
USE_IN_MEMORY = os.environ.get("USE_IN_MEMORY", "false").lower() == "true"

# --- WORKDIR / SESSION DIR (ensure exists & writable) ---
WORKDIR = os.environ.get("PYROGRAM_WORKDIR", "/tmp/pyrogram")
try:
    os.makedirs(WORKDIR, exist_ok=True)
    if not os.access(WORKDIR, os.W_OK):
        try:
            os.chmod(WORKDIR, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
        except Exception as e:
            logger.warning("Could not chmod workdir (%s): %s", WORKDIR, e)
    logger.info("Using workdir: %s", WORKDIR)
except Exception as e:
    logger.exception("Failed to prepare workdir (%s): %s", WORKDIR, e)

if not API_ID or not API_HASH or not BOT_TOKEN:
    logger.error("Missing TELEGRAM credentials (API_ID/API_HASH/BOT_TOKEN). Set in env vars.")

# Create Pyrogram client (bot mode)
app = Client(
    "beuhub_streamer",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir=WORKDIR
)


async def home(request):
    return web.Response(text="BEUHub MTProto Streamer is running ✓")


def parse_range(range_header: str, file_size: int):
    """
    Returns tuple (start, end) where end may be None if file_size unknown.
    """
    # normalize file_size
    try:
        file_size = int(file_size or 0)
    except Exception:
        file_size = 0

    if not range_header or file_size <= 0:
        # no range requested or unknown length
        return 0, (file_size - 1) if file_size > 0 else None

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


async def stream_from_message(message, request, start: int, end):
    """
    Stream bytes [start..end] from a pyrogram Message's media.
    If end is None -> stream to EOF.
    """
    try:
        file_size = int(getattr(message, "file_size", 0) or 0)
    except Exception:
        file_size = 0

    if end is None:
        end = (file_size - 1) if file_size > 0 else None

    length = (end - start + 1) if (end is not None) else None

    headers = {
        "Content-Type": getattr(message, "mime_type", "application/octet-stream"),
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{getattr(message, "file_name", "file")}"',
    }
    if length is not None:
        headers["Content-Length"] = str(length)
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size or '*'}"

    status = 206 if request.headers.get("Range") else 200
    resp = web.StreamResponse(status=status, headers=headers)
    await resp.prepare(request)

    try:
        limit = None if end is None else (end - start + 1)
        # stream in chunks; prefer disk-based streaming for large files if USE_IN_MEMORY is False
        async for chunk in app.download_media(
            message,
            file_name=None,
            in_memory=USE_IN_MEMORY,
            progress=None,
            chunk_size=CHUNK_SIZE,
            offset=start,
            limit=limit,
        ):
            if not chunk:
                break
            await resp.write(chunk)
    except Exception as e:
        logger.exception("Error while streaming chunks: %s", e)
        # respond gracefully (don't leak internal traceback)
        try:
            await resp.write(b"\n\nSTREAM ERROR\n")
        except Exception:
            pass
    finally:
        try:
            await resp.write_eof()
        except Exception:
            pass

    return resp


async def get_message_by_id(chat_identifier, message_id):
    """
    Fetch message by chat identifier (int or username) and message id.
    """
    try:
        try:
            chat = int(chat_identifier)
        except Exception:
            chat = chat_identifier
        msg = await app.get_messages(chat, int(message_id))
        return msg
    except Exception as e:
        logger.exception("get_messages failed: %s", e)
        raise


async def stream_handler(request):
    """
    Routes:
      /stream/<chat_id>/<message_id>   -> reliable (preferred)
      /stream/<message_id>             -> uses DEFAULT_CHAT_ID if set
      /stream/<file_id>                -> fallback: searches recent messages in DEFAULT_CHAT_ID
    """
    if not BOT_TOKEN or not API_ID or not API_HASH:
        return web.Response(status=500, text="Server misconfigured: missing TELEGRAM credentials")

    raw = request.rel_url.path
    segments = [s for s in raw.split("/") if s]
    try:
        if len(segments) >= 3:
            chat_id = segments[1]
            message_id = segments[2]
            use_chat = chat_id
            use_msg = message_id
            is_file_id = False
        else:
            use_id = segments[1] if len(segments) >= 2 else None
            if use_id is None:
                return web.Response(status=400, text="Missing id")
            # heuristic: message_id is numeric; otherwise treat as file_id
            if use_id.isdigit() and DEFAULT_CHAT_ID is not None:
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
            if DEFAULT_CHAT_ID is not None:
                try:
                    # Search recent history in DEFAULT_CHAT_ID for this file_id (fallback only)
                    last_msgs = await app.get_history(DEFAULT_CHAT_ID, limit=200)
                    found = None
                    for m in last_msgs:
                        try:
                            if getattr(m, "video", None) and m.video.file_id == file_id:
                                found = m
                                break
                            if getattr(m, "document", None) and m.document.file_id == file_id:
                                found = m
                                break
                            if getattr(m, "audio", None) and m.audio.file_id == file_id:
                                found = m
                                break
                        except Exception:
                            continue
                    if not found:
                        return web.Response(status=404, text="file_id not found in recent chat history; save message metadata at upload time")
                    message = found
                    file_size = message.file_size or 0
                    start, end = parse_range(request.headers.get("Range"), file_size)
                    return await stream_from_message(message, request, start, end)
                except RPCError as rpc_e:
                    logger.exception("Telegram RPCError while searching file_id: %s", rpc_e)
                    return web.Response(status=500, text="Telegram RPC error while searching file_id")
                except Exception as e:
                    logger.exception("Error searching for file_id: %s", e)
                    return web.Response(status=500, text="Server error while searching for file_id")
            else:
                return web.Response(status=400, text="file_id streaming requires DEFAULT_CHAT_ID or explicit message reference")

    except RPCError as rpc_e:
        logger.exception("Telegram RPCError: %s", rpc_e)
        return web.Response(status=500, text="Telegram RPC error")
    except Exception as e:
        logger.exception("Unhandled exception: %s", e)
        # do not leak internal traceback to clients; log it instead
        logger.debug(traceback.format_exc())
        return web.Response(status=500, text="Server error")


async def init_app():
    # start pyrogram client
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
