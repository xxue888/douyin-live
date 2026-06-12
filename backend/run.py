import os
import sys
import subprocess
import uvicorn
from pathlib import Path

from backend.app.asyncio_compat import configure_windows_event_loop_policy

configure_windows_event_loop_policy()

# Ensure Playwright finds/installs Chromium inside our custom data folder when packaged
if getattr(sys, 'frozen', False):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(sys.executable).parent / "data" / "playwright-browsers")

def setup_playwright():
    """Checks and installs Playwright browser dependencies if needed"""
    print("正在检查 Playwright 浏览器依赖...")
    try:
        # Check if playwright can find chromium
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        print("Playwright 浏览器检查完毕：就绪")
    except Exception as e:
        print("未检测到 Playwright 浏览器，正在自动安装 Chromium...")
        try:
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            print("Chromium 浏览器安装成功！")
        except subprocess.CalledProcessError as err:
            print(f"安装 Playwright 浏览器失败: {err}")
            print("请尝试手动运行: python -m playwright install chromium")

if __name__ == "__main__":
    # Ensure current working directory is correct
    if getattr(sys, 'frozen', False):
        os.chdir(Path(sys.executable).parent)
    else:
        current_dir = Path(__file__).resolve().parent
        os.chdir(current_dir.parent)
    
    # Run Playwright check/installer
    setup_playwright()
    
    # Load configuration port/host if defined in .env
    from dotenv import load_dotenv
    load_dotenv()
    
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    
    print(f"正在启动直播辅助后台管理系统...")
    print(f"请使用浏览器打开: http://{host}:{port}")
    
    if getattr(sys, 'frozen', False):
        # In frozen mode, import app directly and disable reload
        from backend.app.main import app
        uvicorn.run(app, host=host, port=port)
    else:
        # Playwright needs a subprocess-capable event loop on Windows. Uvicorn's
        # reload worker can create the loop before our app is imported, so keep
        # reload off there and restart the script manually during development.
        reload = sys.platform != "win32"
        uvicorn.run("backend.app.main:app", host=host, port=port, reload=reload)

