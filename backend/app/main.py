import asyncio
import datetime
import os
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .asyncio_compat import configure_windows_event_loop_policy
from .config import settings
from .database import load_config, save_config, update_config
from .schemas.models import AppConfig
from .core.automation import DouyinBot
from .core.douyin_login import DouyinLoginManager
from .core.scheduler import AnnouncementScheduler
from .core.reply_engine import evaluate_comment

configure_windows_event_loop_policy()

app = FastAPI(title="Douyin Live Auto-Assistant")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
bot: DouyinBot = None
scheduler: AnnouncementScheduler = None
login_manager: DouyinLoginManager = None
active_sockets: List[WebSocket] = []

class StartRequest(BaseModel):
    live_url: str

# Helper broadcast function
async def broadcast(message: dict):
    disconnected = []
    for ws in active_sockets:
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        if ws in active_sockets:
            active_sockets.remove(ws)

# Callbacks for automation bot
def log_callback(level: str, text: str):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [{level}] {text}\n"
    print(log_line, end="")
    
    try:
        log_file = settings.DATA_DIR / "backend.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception:
        pass
    
    # Broadcast to UI
    log_entry = {
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
        "type": "system",
        "level": level,
        "text": text
    }
    loop = asyncio.get_event_loop()
    if loop.is_running():
        loop.create_task(broadcast(log_entry))

def chat_callback(username: str, content: str, event_type: str = "chat", metadata: dict = None):
    metadata = metadata or {}
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    chat_entry = {
        "timestamp": timestamp,
        "type": event_type,
        "username": username,
        "content": content,
        "metadata": metadata
    }
    label = "GIFT" if event_type == "gift" else "CHAT"
    print(f"[{timestamp}] [{label}] {username}: {content}")
    
    # Broadcast to UI
    loop = asyncio.get_event_loop()
    if loop.is_running():
        loop.create_task(broadcast(chat_entry))
        if event_type == "chat":
            loop.create_task(process_chat_reply(username, content))

async def process_chat_reply(username: str, content: str):
    global bot
    if not bot or bot.status != "running":
        return
        
    config = load_config()
    result = evaluate_comment(username, content, config)
    if result:
        reply_content, source = result
        
        # Log and broadcast the generated reply
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        reply_entry = {
            "timestamp": timestamp,
            "type": "reply",
            "source": source,
            "username": username,
            "comment": content,
            "reply": reply_content
        }
        await broadcast(reply_entry)
        
        # Send reply message to live chat
        log_callback("INFO", f"自动回复 ({'规则' if source == 'rule' else 'AI'}): {reply_content}")
        await bot.send_message(reply_content)

def status_callback(status: str):
    global bot
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    status_entry = {
        "timestamp": timestamp,
        "type": "status",
        "status": status,
        "like_count": bot.like_count if bot else 0
    }
    loop = asyncio.get_event_loop()
    if loop.is_running():
        loop.create_task(broadcast(status_entry))

# Initialize bot and scheduler
@app.on_event("startup")
async def startup_event():
    global bot, scheduler, login_manager
    log_callback("INFO", f"Asyncio event loop: {asyncio.get_running_loop().__class__.__name__}")
    login_manager = DouyinLoginManager()
    bot = DouyinBot(
        log_callback=log_callback,
        chat_callback=chat_callback,
        status_callback=status_callback
    )
    scheduler = AnnouncementScheduler(bot)

@app.on_event("shutdown")
async def shutdown_event():
    global bot, scheduler, login_manager
    if scheduler:
        await scheduler.stop()
    if bot:
        await bot.stop()
    if login_manager:
        await login_manager.close()

# REST Endpoints
@app.get("/api/config", response_model=AppConfig)
async def get_config():
    return load_config()

@app.post("/api/config")
async def save_app_config(config: AppConfig):
    save_config(config)
    log_callback("INFO", "已更新系统配置参数")
    return {"status": "success"}

@app.get("/api/status")
async def get_status():
    global bot
    return {
        "status": bot.status if bot else "stopped",
        "like_count": bot.like_count if bot else 0
    }

@app.get("/api/douyin/login/status")
async def get_douyin_login_status():
    global login_manager
    if not login_manager:
        raise HTTPException(status_code=500, detail="登录管理器未初始化")
    return await login_manager.get_cached_status()

@app.post("/api/douyin/login/start")
async def start_douyin_login():
    global bot, login_manager
    if not login_manager:
        raise HTTPException(status_code=500, detail="登录管理器未初始化")
    if bot and bot.status != "stopped":
        raise HTTPException(status_code=409, detail="直播助手运行中，无法同时打开登录会话。")
    return await login_manager.start()

@app.get("/api/douyin/login/poll")
async def poll_douyin_login():
    global login_manager
    if not login_manager:
        raise HTTPException(status_code=500, detail="登录管理器未初始化")
    return await login_manager.status(include_screenshot=True)

@app.post("/api/douyin/login/logout")
async def logout_douyin_login():
    global bot, login_manager
    if not login_manager:
        raise HTTPException(status_code=500, detail="登录管理器未初始化")
    if bot and bot.status != "stopped":
        raise HTTPException(status_code=409, detail="直播助手运行中，请先停止后再退出登录。")
    return await login_manager.logout()

@app.post("/api/control/start")
async def start_bot(req: StartRequest):
    global bot, scheduler, login_manager
    if not bot:
        raise HTTPException(status_code=500, detail="机器人未初始化")
        
    if bot.status != "stopped":
        return {"status": "already_running"}
        
    config = load_config()
    # Update live URL in configuration
    config.live_url = req.live_url
    save_config(config)
    
    # Start bot and scheduler
    if login_manager:
        await login_manager.close()
    await bot.start(req.live_url, config)
    await scheduler.start()
    
    return {"status": "success"}

@app.post("/api/control/stop")
async def stop_bot():
    global bot, scheduler
    if not bot:
        raise HTTPException(status_code=500, detail="机器人未初始化")
        
    await scheduler.stop()
    await bot.stop()
    
    return {"status": "success"}

class SendRequest(BaseModel):
    message: str

@app.post("/api/control/send")
async def send_message_manual(req: SendRequest):
    global bot
    if not bot or bot.status != "running":
        raise HTTPException(status_code=400, detail="机器人未处于运行状态")
    success = await bot.send_message(req.message)
    if success:
        return {"status": "success"}
    else:
        raise HTTPException(status_code=500, detail="发送消息失败，请检查浏览器是否已进入直播间且已登录。")

@app.post("/api/control/snapshot")
async def save_snapshot_manual():
    global bot
    if not bot or bot.status != "running":
        raise HTTPException(status_code=400, detail="机器人未处于运行状态")
    await bot.save_snapshot()
    return {"status": "success"}

# WebSocket Endpoint
@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    active_sockets.append(websocket)
    
    # Send initial status
    global bot
    initial_status = {
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
        "type": "status",
        "status": bot.status if bot else "stopped",
        "like_count": bot.like_count if bot else 0
    }
    try:
        await websocket.send_json(initial_status)
        # Keep connection open
        while True:
            # We don't expect messages from client for now, but need to listen to detect disconnects
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in active_sockets:
            active_sockets.remove(websocket)

# Serve Frontend Static Files
frontend_dir = settings.BASE_DIR / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
async def read_index():
    index_path = settings.BASE_DIR / "frontend" / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="前端网页未找到，请确认前端文件夹结构是否正确。")
    return FileResponse(index_path)
