import os
from pyrogram import Client
from aiohttp import web
# --- APNA DATA YAHAN DALEN (Updated) ---
API_ID = 33833846              
API_HASH = "08293ed11f6189993b0337b852ed1446"   
BOT_TOKEN = "8532091150:AAETyfRm0InvlHa-f4sFhdDB4y5_E5ZV8q4" 
CHANNEL_ID = -1003266040653    # ✅ Apka Chat ID

app = Client("beuhub_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN, in_memory=True)

async def stream_handler(request):
    try:
        # ✅ FIX: अब हम ID को सीधे नंबर (Integer) की तरह ले रहे हैं
        msg_id = int(request.match_info['id'])
        
        # उस मैसेज को ढूंढो
        message = await app.get_messages(chat_id=CHANNEL_ID, message_ids=msg_id)
        
        media = message.video or message.document or message.audio
        if not media:
            return web.Response(status=404, text="Media not found")

        # Stream Headers
        resp = web.StreamResponse()
        resp.headers['Content-Type'] = media.mime_type or "video/mp4"
        resp.headers['Content-Length'] = str(media.file_size)
        resp.headers['Content-Disposition'] = f'inline; filename="video.mp4"'
        
        await resp.prepare(request)

        # Download & Stream
        async for chunk in app.download_media(media.file_id, in_memory=True, chunk_size=1024*1024):
             await resp.write(chunk)
             
        return resp
    except Exception as e:
        return web.Response(status=500, text=f"Server Error: {str(e)}")

async def init_app():
    if not app.is_connected: await app.start()
    server = web.Application()
    server.router.add_get('/stream/{id}', stream_handler)
    return server

if __name__ == "__main__":
    web.run_app(init_app(), port=8080)
