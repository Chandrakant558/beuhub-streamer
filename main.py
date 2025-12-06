import os
import math
from pyrogram import Client
from aiohttp import web

# --- APNA DATA YAHAN DALEN (Updated) ---
API_ID = 33833846              
API_HASH = "08293ed11f6189993b0337b852ed1446"   
BOT_TOKEN = "8532091150:AAETyfRm0InvlHa-f4sFhdDB4y5_E5ZV8q4" 
CHANNEL_ID = -1003266040653    # ✅ Apka Chat ID

# Pyrogram Client (MTProto - The Big Gate)
app = Client(
    "beuhub_streamer",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

async def stream_handler(request):
    try:
        # URL se Message ID nikalo
        message_id = int(request.match_info['id'])
        
        # File dhundo
        message = await app.get_messages(CHANNEL_ID, message_id)
        media = message.video or message.document or message.audio
        
        if not media:
            return web.Response(status=404, text="Media not found")

        file_size = media.file_size
        mime_type = media.mime_type or "video/mp4"
        file_name = getattr(media, "file_name", "video.mp4")

        # Range Header Handle karna (Seeking ke liye jaruri hai)
        range_header = request.headers.get("Range")
        from_bytes, until_bytes = 0, file_size - 1
        
        if range_header:
            try:
                ranges = range_header.replace("bytes=", "").split("-")
                from_bytes = int(ranges[0])
                if len(ranges) > 1 and ranges[1]:
                    until_bytes = int(ranges[1])
            except:
                pass
        
        # Calculate length
        content_length = until_bytes - from_bytes + 1
        
        # Setup Response Headers
        headers = {
            "Content-Type": mime_type,
            "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
            "Content-Length": str(content_length),
            "Content-Disposition": f'inline; filename="{file_name}"',
            "Accept-Ranges": "bytes",
        }

        resp = web.StreamResponse(status=206, headers=headers)
        await resp.prepare(request)

        # 🔥 MTProto Streaming Magic (Bada Darwaza)
        # Hum file ko tukdo (chunks) mein download karke seedha bhej rahe hain
        async for chunk in app.download_media(
            message,
            offset=from_bytes,
            limit=content_length,
            in_memory=True,
            chunk_size=1024 * 1024 # 1MB chunks
        ):
            await resp.write(chunk)

        return resp

    except Exception as e:
        print(f"Error: {e}")
        return web.Response(status=500, text=f"Stream Error: {str(e)}")

async def home(request):
    return web.Response(text="BEUHub MTProto Streamer is Running! 🚀")

async def init_app():
    if not app.is_connected:
        await app.start()
    
    server = web.Application()
    server.router.add_get("/", home)
    server.router.add_get("/stream/{id}", stream_handler)
    return server

if __name__ == "__main__":
    web.run_app(init_app(), port=8080)
