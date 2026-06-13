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

def show_message_box(title, text, is_error=False):
    """Shows a native Windows MessageBox to inform user about install progress when console is hidden"""
    if sys.platform == "win32":
        try:
            import ctypes
            style = 0x10 if is_error else 0x40  # 0x10: MB_ICONERROR, 0x40: MB_ICONINFORMATION
            ctypes.windll.user32.MessageBoxW(0, text, title, style | 0x0)
        except Exception:
            pass

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
        if getattr(sys, 'frozen', False):
            show_message_box(
                "助手初始化",
                "系统检测到未安装或未激活 Chromium 浏览器驱动组件。\n\n点击[确定]后，程序将在后台自动开始下载组件（大约耗时 1-2 分钟，请勿重复点击运行本软件）。\n下载期间请耐心等待...",
                is_error=False
            )
            
        print("未检测到 Playwright 浏览器，正在自动安装 Chromium...")
        try:
            # Import playwright's internal driver execution logic
            from playwright._impl._driver import compute_driver_executable, get_driver_env
            driver_executable, driver_cli = compute_driver_executable()
            
            # Execute the node driver subprocess to install chromium.
            # This avoids self-execution (infinite loop) and does not rely on non-existent Python modules.
            subprocess.run(
                [driver_executable, driver_cli, "install", "chromium"],
                env=get_driver_env(),
                check=True
            )
            print("Chromium 浏览器安装成功！")
            
            if getattr(sys, 'frozen', False):
                show_message_box(
                    "安装完成",
                    "Chromium 浏览器驱动组件下载成功！即将为您启动直播间助手系统。",
                    is_error=False
                )
        except Exception as err:
            error_msg = f"自动安装 Playwright 浏览器失败: {err}\n\n请尝试手动运行: python -m playwright install chromium"
            print(error_msg)
            if getattr(sys, 'frozen', False):
                show_message_box("安装失败", error_msg, is_error=True)
            raise RuntimeError("由于未检测到且自动安装 Playwright 浏览器失败，程序无法运行。") from err

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
