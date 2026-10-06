"""TK去水印高清程序 · 桌面版入口（v4.0 第 2 期）。

双击 exe → 本文件 → 原生窗口（WebView2），**不再打开浏览器**。

进程模型
--------
主线程   : pywebview 原生窗口（WebView2），必须占用主线程
后台线程 : uvicorn 跑 FastAPI（127.0.0.1:动态端口，daemon 线程）
关窗即退 : demo.close()/uvicorn 停止 → 释放端口 → 清理 runtime → 退出

设计要点（都对应审计中发现的真实缺陷）
--------------------------------------
1. 动态端口：原来写死 7860，被残留进程占用时直接 OSError 崩掉且
   启动器静默退出 —— 用户看到「双击没反应」。现在自动挑空闲端口。
2. 不依赖 gradio 运行：通过 server.gradio_shim 注入替身，
   业务函数照旧可用，但整个后端不再 import 真正的 gradio。
3. 单实例：Windows 用 FindWindowW 探测已存在的桌面窗口；
   重复启动只提示、不再抢端口。
4. 服务线程必须是 daemon，否则 threading._shutdown 会永久 join。
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---- 1) 无控制台兜底（pythonw 下 sys.stdout/stderr 为 None）--------------
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = sys.stdout

# ---- 2) 直接使用服务层（业务内核已与界面解耦，不再需要 gradio 替身） ----
APP_NAME = "TK去水印高清程序"
WINDOW_TITLE = APP_NAME
RUNTIME_DIR = ROOT / "runtime"
PORT_FILE = RUNTIME_DIR / "server.json"
LOG_PATH = ROOT / "app.log"


# --------------------------------------------------------------- 日志

def setup_logging() -> None:
    handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler]
    for noisy in ("httpx", "httpcore", "urllib3", "uvicorn.error",
                  "huggingface_hub", "pythonnet", "clr_loader"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


log = logging.getLogger("tk.desktop")


# --------------------------------------------------------------- 工具

def port_in_use(port: int) -> bool:
    """端口是否真的被占用。

    注意：**不能**只靠 bind 判断。Windows 上带 SO_REUSEADDR 的 bind 在端口
    已被监听时仍可能成功（实测 0.0.0.0:7860 被旧进程占用却「绑定成功」），
    所以必须先做一次 connect 探测。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.35)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            return True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
        except OSError:
            return True
    return False


def pick_free_port(lo: int = 7860, hi: int = 7879) -> int:
    for p in range(lo, hi + 1):
        if not port_in_use(p):
            return p
    raise RuntimeError(f"{lo}-{hi} 端口全部被占用，请关闭其他实例后重试")


def write_runtime(port: int, host: str) -> None:
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        PORT_FILE.write_text(json.dumps(
            {"port": port, "host": host, "pid": os.getpid(),
             "version": _version(), "time": time.strftime("%Y-%m-%d %H:%M:%S")},
            ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning(f"写 runtime 文件失败: {e}")


def clear_runtime() -> None:
    try:
        PORT_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _version() -> str:
    try:
        import core.version as v
        return v.VERSION
    except Exception:
        return "4.0.0"


def wait_for_port(port: int, timeout: float = 90.0) -> bool:
    """等服务就绪（TCP 可连）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.25)
    return False


def load_lan_config() -> tuple[bool, str]:
    """读局域网访问开关（v4.0.1：已移除密码要求）。

    现在只看 `lan_access` 这一个开关：
      - 关闭（默认）→ 只监听 127.0.0.1，外部访问不到；
      - 开启 → 监听 0.0.0.0，同一 WiFi 下的设备可直接打开（无需登录）。

    返回值第二项保留为密码位（恒为空），仅为兼容旧调用点。
    """
    try:
        import core.config as cfgmod
        cfg = cfgmod.load()
        lan = bool(cfg.get("lan_access", False))
        if lan:
            log.info("局域网访问已开启（无密码）。请确认当前网络可信 —— "
                     "同一网络内的设备都能访问本程序。")
        return lan, ""
    except Exception as e:
        log.warning(f"读取局域网配置失败（按仅本机处理）: {e}")
        return False, ""


def lan_ip() -> str:
    """取本机局域网 IP（用于日志/诊断里给出手机访问地址）。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return ""


# --------------------------------------------------------------- 单实例

_MUTEX_HANDLE = None
MUTEX_NAME = "Global\\TKNoWatermarkDesktopV4"


def acquire_single_instance() -> bool:
    """用命名互斥体实现单实例。返回 True 表示本进程是唯一实例。

    为什么不用隐藏窗口 + FindWindowW：
    那需要注册窗口类、维护 WNDPROC 回调并自己跑消息循环，
    ctypes 里极易踩句柄截断/回调引用被 GC 的坑（实测确实踩了）。
    命名互斥体由内核维护，几行代码且不会随进程存活期出问题。
    """
    global _MUTEX_HANDLE
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                          wintypes.LPCWSTR]
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            log.warning("CreateMutexW 失败，单实例检查降级为放行")
            return True
        _MUTEX_HANDLE = handle          # 必须持有，释放即失效
        already = (ctypes.get_last_error() == 183)   # ERROR_ALREADY_EXISTS
        return not already
    except Exception as e:
        log.warning(f"单实例检查失败（降级为放行）: {e}")
        return True


def already_running() -> bool:
    """兼容旧调用：是否已有实例在跑（探测用，不持有句柄）。"""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenMutexW.restype = wintypes.HANDLE
        kernel32.OpenMutexW.argtypes = [ctypes.c_uint, wintypes.BOOL,
                                        wintypes.LPCWSTR]
        SYNCHRONIZE = 0x00100000
        h = kernel32.OpenMutexW(SYNCHRONIZE, False, MUTEX_NAME)
        if h:
            kernel32.CloseHandle(h)
            return True
        return False
    except Exception:
        return False


def _notify_already_running() -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, f"{APP_NAME} 已经在运行了。\n请查看任务栏或托盘图标。",
            APP_NAME, 0x40)
    except Exception:
        pass


# --------------------------------------------------------------- 退出

_stop_event = threading.Event()


def do_shutdown(reason: str = "窗口关闭") -> None:
    """协作式关停：停任务 → 停服务 → 清 runtime。"""
    if _stop_event.is_set():
        return
    _stop_event.set()
    log.info(f"开始关停：{reason}")
    try:
        from ui import bus
        n = bus.cancel_all()
        if n:
            log.info(f"已请求取消 {n} 个进行中的任务")
    except Exception:
        pass
    try:
        # 让正在跑的任务有机会落盘
        time.sleep(0.3)
    except Exception:
        pass
    clear_runtime()
    log.info("关停完成")


# --------------------------------------------------------------- 主流程

def main() -> int:
    setup_logging()
    log.info(f"启动桌面版 v{_version()}")

    if not acquire_single_instance():
        log.info("检测到已有实例在运行，本次退出")
        _notify_already_running()
        return 0

    port = pick_free_port()

    # v4.0：按 config.json 决定监听地址。
    # v4.0.1：已移除账号密码登录 —— 开启局域网即直接可访问（同一 WiFi 内）。
    lan_access, _ = load_lan_config()
    host = "0.0.0.0" if lan_access else "127.0.0.1"
    write_runtime(port, host)
    log.info(f"服务端口: {port}，监听: {host}"
             + ("（局域网/手机可访问）" if lan_access else "（仅本机）"))

    # 预加载业务模块（会让界面更快出现）
    try:
        import server.api as api
        api.refresh_allowed_paths()
        api.set_lan_open(lan_access)
        log.info("业务模块加载完成")
    except Exception:
        log.exception("业务模块加载失败")
        _fatal("程序初始化失败，请查看 app.log")
        return 1

    # --- 后台线程跑 uvicorn（必须 daemon）---
    import uvicorn

    config = uvicorn.Config(
        api.app, host=host, port=port,
        log_level="warning", access_log=False, loop="asyncio",
    )
    server = uvicorn.Server(config)

    def _serve():
        try:
            server.run()
        except Exception:
            log.exception("HTTP 服务异常退出")

    threading.Thread(target=_serve, daemon=True, name="uvicorn").start()

    if not wait_for_port(port):
        log.error("服务启动超时")
        _fatal("服务启动失败（端口未就绪），请查看 app.log")
        return 1
    log.info("HTTP 服务就绪")
    if lan_access:
        ip = lan_ip()
        if ip:
            log.info(f"手机访问地址: http://{ip}:{port}（同一 WiFi 下直接打开，无需登录）")

    # --- 主线程：原生窗口 ---
    import webview

    url = f"http://127.0.0.1:{port}/"
    window = webview.create_window(
        WINDOW_TITLE, url,
        width=1440, height=920, min_size=(1080, 680),
        text_select=True, confirm_close=False,
    )

    def _on_closing():
        try:
            do_shutdown("窗口关闭")
        except Exception:
            log.exception("关停异常")
        return True

    try:
        window.events.closing += _on_closing
    except Exception:
        log.warning("注册 closing 事件失败（忽略）")

    icon = ROOT / "assets" / "icon.ico"
    try:
        webview.start(gui="edgechromium",
                      icon=str(icon) if icon.exists() else None)
    except Exception:
        log.exception("原生窗口启动失败，回退为浏览器模式")
        try:
            import webbrowser
            webbrowser.open(url)
            # 回退模式下阻塞，保持服务存活
            while not _stop_event.is_set():
                time.sleep(1)
        except Exception:
            pass
        return 1

    do_shutdown("主循环结束")
    log.info("程序退出")
    # 兜底：个别 worker/GPU 线程可能吊住解释器
    os._exit(0)
    return 0


def _fatal(message: str) -> None:
    log.error(message)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, APP_NAME, 0x10)
    except Exception:
        try:
            print(message)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
