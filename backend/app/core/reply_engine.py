import random
from typing import Optional, List, Tuple
from ..schemas.models import AppConfig
from .llm import generate_reply

# Track recent replies to avoid repeating ourselves
_recent_replies: List[str] = []
MAX_RECENT_HISTORY = 10

def _is_duplicate_or_similar(reply: str) -> bool:
    """Check if the proposed reply is identical to recent replies"""
    # Clean string to compare
    clean_reply = reply.strip().strip("～!！.。?？")
    for r in _recent_replies:
        clean_r = r.strip().strip("～!！.。?？")
        if clean_reply == clean_r:
            return True
    return False

def _de_duplicate(reply: str) -> str:
    """Slightly alter the reply to avoid repetition if it matches recent history"""
    endings = ["哦", "呀", "哈", "啦", "！", "～", "呢", "哒"]
    # If it is duplicate, try to append/change punctuation
    attempts = 0
    altered = reply
    while _is_duplicate_or_similar(altered) and attempts < 5:
        char = random.choice(endings)
        if altered.endswith("～") or altered.endswith("！"):
            altered = altered[:-1] + char
        else:
            altered = altered + char
        attempts += 1
    return altered

def evaluate_comment(username: str, comment: str, config: AppConfig) -> Optional[Tuple[str, str]]:
    """
    Evaluates an incoming comment against keyword rules first, then calls AI if enabled.
    Returns: Tuple[reply_content, source_type] or None if no response should be sent.
    source_type is either "rule" or "ai".
    """
    global _recent_replies
    
    # 1. Check Keyword Rules (Rule-first priority)
    comment_lower = comment.lower().strip()
    for rule in config.rules:
        if rule.keyword.lower().strip() in comment_lower:
            reply = rule.reply
            # Keep history updated
            _recent_replies.append(reply)
            if len(_recent_replies) > MAX_RECENT_HISTORY:
                _recent_replies.pop(0)
            return reply, "rule"
            
    # 2. Call AI if enabled
    if config.ai_reply_enabled:
        prompt = f"用户 {username}: {comment}"
        # Inject context/constraints directly in system prompt to ensure LLM compliance
        custom_system = config.system_prompt + "\n【重要限制】: 回复字数控制在20字以内。不要重复，必须是简短的一句话，不要有违规词。"
        
        reply = generate_reply(prompt, custom_system, config)
        
        # Deduplicate
        if _is_duplicate_or_similar(reply):
            reply = _de_duplicate(reply)
            
        # Ensure under 20 chars limit
        if len(reply) > 20:
            reply = reply[:19] + "～"
            
        # Keep history updated
        _recent_replies.append(reply)
        if len(_recent_replies) > MAX_RECENT_HISTORY:
            _recent_replies.pop(0)
            
        return reply, "ai"
        
    return None
