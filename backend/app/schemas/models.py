from pydantic import BaseModel, Field
from typing import List, Optional

class KeywordRule(BaseModel):
    keyword: str
    reply: str

class ScheduledMessage(BaseModel):
    interval: int
    content: str
    enabled: bool = True

class SmartTriggers(BaseModel):
    enabled: bool = True
    silence_5m_content: str = "大家来自哪里呀？可以在公屏上打出来哦～"
    silence_10m_content: str = "今天福利非常多，大家有什么想看的品吗？"
    like_100_content: str = "点赞到100啦！感谢家人们的支持，么么哒～"

class AppConfig(BaseModel):
    live_url: str = Field(default="https://live.douyin.com/")
    ai_reply_enabled: bool = True
    llm_provider: str = Field(default="openai")  # openai, gemini, deepseek
    openai_api_key: Optional[str] = ""
    openai_api_base: Optional[str] = "https://api.openai.com/v1"
    openai_model: Optional[str] = "gpt-3.5-turbo"
    gemini_api_key: Optional[str] = ""
    gemini_model: Optional[str] = "gemini-1.5-flash"
    system_prompt: str = Field(default="你是一个热情的直播间主播助理，回复在20字以内，不要泄露你是AI。")
    rules: List[KeywordRule] = Field(default_factory=list)
    scheduled_messages: List[ScheduledMessage] = Field(default_factory=list)
    smart_triggers: SmartTriggers = Field(default_factory=SmartTriggers)
