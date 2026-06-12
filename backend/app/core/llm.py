import json
import urllib.request
import urllib.error
from openai import OpenAI
from ..schemas.models import AppConfig

def call_openai(prompt: str, system_prompt: str, config: AppConfig) -> str:
    """Calls OpenAI-compatible endpoints (including DeepSeek, local models, etc.)"""
    if not config.openai_api_key:
        return "⚠️ 未配置 OpenAI API Key"
    
    try:
        client = OpenAI(
            api_key=config.openai_api_key,
            base_url=config.openai_api_base
        )
        response = client.chat.completions.create(
            model=config.openai_model or "gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            max_tokens=50,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"OpenAI API error: {e}")
        return f"⚠️ OpenAI 接口调用失败: {str(e)}"

def call_gemini(prompt: str, system_prompt: str, config: AppConfig) -> str:
    """Calls Gemini API directly using HTTP POST request to avoid package dependency issues"""
    if not config.gemini_api_key:
        return "⚠️ 未配置 Gemini API Key"
        
    model = config.gemini_model or "gemini-1.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={config.gemini_api_key}"
    
    # Payload format for Gemini API
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"系统指令: {system_prompt}\n\n用户消息: {prompt}"}]
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 50
        }
    }
    
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            res_body = json.loads(response.read().decode("utf-8"))
            # Extract content from response
            text = res_body["candidates"][0]["content"]["parts"][0]["text"]
            return text.strip()
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode("utf-8")
        print(f"Gemini API HTTP Error: {error_msg}")
        try:
            err_json = json.loads(error_msg)
            return f"⚠️ Gemini 接口错误: {err_json['error']['message']}"
        except:
            return f"⚠️ Gemini 接口返回错误: {e.code}"
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return f"⚠️ Gemini 调用失败: {str(e)}"

def generate_reply(prompt: str, system_prompt: str, config: AppConfig) -> str:
    """Dispatches generation request to configured LLM provider"""
    if config.llm_provider == "gemini":
        reply = call_gemini(prompt, system_prompt, config)
    else:  # openai, deepseek, etc.
        reply = call_openai(prompt, system_prompt, config)
        
    # Apply safety limit on word count
    # Restrict to 20 characters as requested
    if len(reply) > 20:
        # Just truncate or try to extract a clean sentence
        reply = reply[:19] + "～"
        
    return reply
