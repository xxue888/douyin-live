import asyncio
import random
import time
from typing import Dict, Any, List
from ..database import load_config
from .automation import DouyinBot

class AnnouncementScheduler:
    def __init__(self, bot: DouyinBot):
        self.bot = bot
        self.running = False
        self.task = None
        
        # State for periodic announcements
        # Maps index -> next_trigger_timestamp
        self.scheduled_triggers: Dict[int, float] = {}
        
        # State for smart silence triggers
        self.silence_5m_fired = False
        self.silence_10m_fired = False
        self.last_known_msg_time = 0.0
        
        # State for like triggers
        self.last_thanked_likes = 0

    async def start(self):
        if self.running:
            return
        self.running = True
        self.last_known_msg_time = self.bot.last_message_time
        self.task = asyncio.create_task(self._run_loop())
        self.bot.log_callback("INFO", "调度管理器已启动")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        self.bot.log_callback("INFO", "调度管理器已停止")

    async def _run_loop(self):
        # Initial sleep to let the browser boot up and settle
        await asyncio.sleep(5)
        
        while self.running:
            if self.bot.status != "running":
                await asyncio.sleep(1)
                continue
                
            try:
                current_time = time.time()
                config = load_config()
                
                # --- 1. Periodic Announcements ---
                for idx, item in enumerate(config.scheduled_messages):
                    if not item.enabled:
                        continue
                        
                    # Initialize trigger time if not present
                    if idx not in self.scheduled_triggers:
                        # Stagger the first trigger time slightly
                        jitter = random.randint(-15, 15)
                        self.scheduled_triggers[idx] = current_time + item.interval + jitter
                        
                    if current_time >= self.scheduled_triggers[idx]:
                        # Trigger!
                        self.bot.log_callback("INFO", f"触发定时消息(间隔 {item.interval}秒)")
                        success = await self.bot.send_message(item.content)
                        
                        # Calculate next trigger with randomized delay to avoid anti-bot detection
                        # Allow +/- 10% jitter (max 60 seconds)
                        max_jitter = min(60, int(item.interval * 0.10))
                        jitter = random.randint(-max_jitter, max_jitter) if max_jitter > 2 else 0
                        self.scheduled_triggers[idx] = current_time + item.interval + jitter
                
                # --- 2. Smart Silence Triggers ---
                if config.smart_triggers.enabled:
                    # Reset silence states if new messages arrived
                    if self.bot.last_message_time > self.last_known_msg_time:
                        self.last_known_msg_time = self.bot.last_message_time
                        self.silence_5m_fired = False
                        self.silence_10m_fired = False
                        
                    silence_duration = current_time - self.bot.last_message_time
                    
                    # 5 Minutes Silence (300s)
                    if silence_duration >= 300 and not self.silence_5m_fired:
                        self.bot.log_callback("INFO", "检测到直播间公屏已安静5分钟，自动活跃气氛...")
                        success = await self.bot.send_message(config.smart_triggers.silence_5m_content)
                        if success:
                            self.silence_5m_fired = True
                            
                    # 10 Minutes Silence (600s)
                    if silence_duration >= 600 and not self.silence_10m_fired:
                        self.bot.log_callback("INFO", "检测到直播间公屏已安静10分钟，自动发送福利提醒...")
                        success = await self.bot.send_message(config.smart_triggers.silence_10m_content)
                        if success:
                            self.silence_10m_fired = True
                            
                # --- 3. Smart Like Count Triggers ---
                if config.smart_triggers.enabled and self.bot.like_count >= 100:
                    # Trigger every 100 likes increment
                    current_milestone = (self.bot.like_count // 100) * 100
                    if current_milestone > self.last_thanked_likes:
                        # Format thank you message
                        # Substitute the current like count if template supports it, or send direct text
                        thank_msg = config.smart_triggers.like_100_content
                        # E.g. "点赞到100啦！感谢家人们的支持" -> replace "100" with actual count
                        thank_msg = thank_msg.replace("100", str(current_milestone))
                        
                        self.bot.log_callback("INFO", f"触发点赞里程碑: {self.bot.like_count} 赞")
                        success = await self.bot.send_message(thank_msg)
                        if success:
                            self.last_thanked_likes = current_milestone
                            
            except Exception as e:
                self.bot.log_callback("ERROR", f"调度管理器运行出错: {e}")
                
            await asyncio.sleep(2)
