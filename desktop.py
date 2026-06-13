import sys

class DummyStream:
    def write(self, data):
        pass
    def flush(self):
        pass

if sys.stdout is None:
    sys.stdout = DummyStream()
if sys.stderr is None:
    sys.stderr = DummyStream()

import os
import socket
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn
import webview
from dotenv import load_dotenv

from backend.app.asyncio_compat import configure_windows_event_loop_policy
from backend.run import setup_playwright


configure_windows_event_loop_policy()


def configure_runtime_paths():
    if getattr(sys, "frozen", False):
        app_dir = Path(sys.executable).parent
        os.chdir(app_dir)
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(app_dir / "data" / "playwright-browsers")
    else:
        os.chdir(Path(__file__).resolve().parent)


def wait_for_server(host: str, port: int, timeout: float = 20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def run_server(host: str, port: int):
    from backend.app.main import app

    uvicorn.run(app, host=host, port=port, log_level="info")


def open_fallback_browser(url: str):
    webbrowser.open(url)


def main():
    configure_runtime_paths()
    load_dotenv()
    setup_playwright()

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    url = f"http://{host}:{port}"

    server_thread = threading.Thread(target=run_server, args=(host, port), daemon=True)
    server_thread.start()

    if not wait_for_server(host, port):
        raise RuntimeError(f"服务启动超时，请检查端口是否被占用: {url}")

    window = webview.create_window(
        "抖音直播智能助手",
        url,
        width=1400,
        height=900,
        min_size=(1100, 720),
    )

    try:
        webview.start()
    except Exception:
        open_fallback_browser(url)
        while server_thread.is_alive():
            time.sleep(1)


if __name__ == "__main__":
    main()
