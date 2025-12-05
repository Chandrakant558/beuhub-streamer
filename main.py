import os
from pyrogram import Client
from aiohttp import web

# --- APNA DATA YAHAN DALEN (Updated) ---
API_ID = 33833846              
API_HASH = "08293ed11f6189993b0337b852ed1446"   
BOT_TOKEN = "8532091150:AAETyfRm0InvlHa-f4sFhdDB4y5_E5ZV8q4" 
CHANNEL_ID = -1003266040653    # ✅ Apka Chat ID

app = Client("beuhub_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

async def stream_handler(request):
    try:
        # URL se Message ID (Number) nikalo
        # URL format: /stream/123 (jahan 123 message id hai)
        msg_id = int(request.match_info['id'])
        
        # Channel se wo message dhundo
        message = await app.get_messages(chat_id=CHANNEL_ID, message_ids=msg_id)
        
        media = message.video or message.document or message.audio
        if not media:
            return web.Response(status=404, text="Media not found inside this message")

        # Stream Setup
        resp = web.StreamResponse()
        resp.headers['Content-Type'] = media.mime_type
        resp.headers['Content-Disposition'] = f'inline; filename="video.mp4"'
        resp.content_length = media.file_size
        
        await resp.prepare(request)

        # Download & Stream directly from Telegram servers
        async for chunk in app.download_media(media.file_id, in_memory=True, chunk_size=1024*1024):
             await resp.write(chunk)
             
        return resp
    except Exception as e:
        return web.Response(status=500, text=f"Server Error: {str(e)}")

async def init_app():
    if not app.is_connected: await app.start()
    server = web.Application()
    # Route ab 'id' (number) lega
    server.router.add_get('/stream/{id}', stream_handler)
    return server

if __name__ == "__main__":
    web.run_app(init_app(), port=8080)
