import os
from pyrogram import Client
from aiohttp import web

# --- APNA DATA YAHAN DALEN ---
API_ID = 33833846              # my.telegram.org se mila ID (Number)
API_HASH = "08293ed11f6189993b0337b852ed1446"   # my.telegram.org se mila Hash (String)
BOT_TOKEN = "8532091150:AAETyfRm0InvlHa-f4sFhdDB4y5_E5ZV8q4"   # 8532... wala Token

# Client Setup
app = Client("beuhub_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

async def stream_handler(request):
    try:
        file_id = request.match_info['file_id']
        # File ID se file ki location nikalna
        file = await app.get_messages(chat_id=int("-1003266040653"), message_ids=int(file_id))
        # Note: Agar hum direct file_id use kar rahe hain to hame 'download_media' ka stream use karna hoga
        # Lekin Pyrogram me 'get_file' direct file_id se nahi chalta bina message reference ke.
        # Isliye hum Android app me thoda change karenge taaki wo 'File ID' ki jagah 'Message ID' bheje.
        
        # Abhi ke liye hum direct stream try karte hain:
        media = file.video or file.document or file.audio
        if not media:
            return web.Response(status=404, text="File not found")

        resp = web.StreamResponse()
        resp.headers['Content-Type'] = media.mime_type
        resp.headers['Content-Disposition'] = f'inline; filename="{media.file_name or "video.mp4"}"'
        resp.content_length = media.file_size
        
        await resp.prepare(request)

        async for chunk in app.download_media(media.file_id, in_memory=True, chunk_size=1024*1024):
             await resp.write(chunk)
             
        return resp
    except Exception as e:
        return web.Response(status=500, text=str(e))

# Route for direct file_id streaming (Simple Method)
async def simple_stream(request):
    try:
        file_id = request.match_info['file_id']
        # Session start
        if not app.is_connected: await app.start()
        
        # Get file info
        file = await app.get_file(file_id)
        
        resp = web.StreamResponse()
        # Header set karna jaruri hai player ke liye
        resp.headers['Content-Type'] = 'video/mp4'
        await resp.prepare(request)
        
        # Stream chunks
        async for chunk in app.download_media(file.file_id, in_memory=True):
            await resp.write(chunk)
            
        return resp
    except Exception as e:
        # Re-connect if needed
        if not app.is_connected: await app.start()
        return web.Response(status=500, text=f"Error: {e}")

async def init_app():
    if not app.is_connected: await app.start()
    server = web.Application()
    # Hum simple wala route use karenge jo kisi bhi file_id ko play kare
    server.router.add_get('/stream/{file_id}', simple_stream)
    return server

if __name__ == "__main__":
    web.run_app(init_app(), port=8080)