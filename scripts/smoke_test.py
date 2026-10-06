"""启动冒烟测试（v4.0 桌面版）。

覆盖面：
  1. 业务内核（server/services.py）能导入，且**不依赖 gradio**
  2. 数据接口：模型表 / 卡片 / 预设 / 更新日志
  3. 预设套用逻辑（图片 / 视频 / 规划中拦截）
  4. 全部可选模型能真实加载推理
  5. 图标资源
  6. FastAPI 服务能起来并响应（含前端页面、越权拦截）
  7. 桌面入口关键函数（动态端口 / 单实例 / 关停）

用法：venv\Scripts\python.exe scripts\smoke_test.py [端口]
默认端口 7861（避开正式默认 7860），不会打开浏览器。
"""

import builtins
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Windows 控制台默认 GBK，打印 ✓/✗ 会抛 UnicodeEncodeError，这里统一成 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OK, FAIL = "✓", "✗"
results = []


def check(name, fn):
    try:
        ok, detail = fn()
        results.append((name, bool(ok), detail))
    except Exception as exc:
        results.append((name, False, f"{type(exc).__name__}: {exc}"))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7861
    from core.version import VERSION

    # ---- 业务内核（并且证明不需要 gradio）----
    svc = {}

    def _import_services():
        real = builtins.__import__

        def _blocked(name, *a, **k):
            if name == "gradio" or name.startswith("gradio."):
                raise ImportError("gradio 已被冒烟测试屏蔽")
            return real(name, *a, **k)

        builtins.__import__ = _blocked
        try:
            import server.services as s
            svc["s"] = s
        finally:
            builtins.__import__ = real
        return ("gradio" not in sys.modules,
                f"版本 {VERSION}，gradio 未加载")

    check("业务内核导入（无 gradio）", _import_services)

    def s():
        return svc["s"]

    check("模型清单表格", lambda: (bool(s().models_table()),
                              f"{len(s().models_table())} 行"))
    check("模型卡片墙", lambda: (bool(s().models_cards_html()),
                             f"{len(s().models_cards_html())} 字符"))
    check("预设总览", lambda: (bool(s().presets_html()),
                            f"{len(s().presets_html())} 字符"))
    check("更新日志渲染", lambda: (bool(s().changelog_markdown()),
                              f"{len(s().changelog_markdown())} 字符"))
    check("GPU 标签", lambda: (bool(s()._gpu_label()), s()._gpu_label()))

    def _preset_img():
        r = s()._apply_preset_image("photo", "realesr-general-x4v3",
                                    "自动（推荐）", False, "4096（推荐）")
        return r[0] == "4x-UltraSharp", f"高清照片 → {r[0]}"

    def _preset_vid():
        r = s()._apply_preset_video("anime_video", "realesr-general-x4v3",
                                    "自动（推荐）", 2560, False)
        return r[0] == "realesr-animevideov3", f"动漫视频 → {r[0]}"

    def _preset_planned():
        r = s()._apply_preset_image("deep_rebuild", "realesr-general-x4v3",
                                    "自动（推荐）", False, "4096（推荐）")
        return "后续版本" in r[4], "规划中预设给出友好提示"

    check("预设套用 · 图片", _preset_img)
    check("预设套用 · 视频", _preset_vid)
    check("预设套用 · 规划中拦截", _preset_planned)

    # ---- v4.0.3 回归：倍数解析必须容错 ----
    # 前端下拉框尚未填充完就被点击时会传空字符串；以前这里直接 int()
    # 抛 ValueError，而调用点在所有文件处理完之后，导致跑完的任务被判失败、产物丢失。
    def _scale_robust():
        vals = {None: None, "": None, "自动（推荐）": None, "自动": None, "2x": 2,
                "4x": 4, "4": 4, "4X": 4, " 4x ": 4, "abc": None, "x": None}
        bad = [f"{k!r}->{s()._scale_value(k)!r}" for k, want in vals.items()
               if s()._scale_value(k) != want]
        return not bad, f"{len(vals)} 种写法全部正确" + (f"，异常：{bad}" if bad else "")

    check("倍数解析容错（空串/自动/4x）", _scale_robust)

    def _remember_safe():
        # 空倍数不能让「记住上次参数」炸掉整个任务
        s()._remember_choices("image", "realesr-general-x4v3", "")
        s()._remember_choices("video", "realesr-general-x4v3", "", max_side="sharp")
        return True, "空倍数和平铺参数下不抛异常"

    check("参数记忆不影响任务结果", _remember_safe)

    def _ui_clear_all():
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
        need = {
            "清空按钮": 'id="hd-clear"' in html,
            "清空逻辑": "function clearPicked" in js,
            "按钮绑定": '$("hd-clear").addEventListener' in js,
            "清单工具条": "filelist-bar" in js,
            "忙碌判定": "isHdBusy" in js,
        }
        missing = [k for k, v in need.items() if not v]
        return not missing, f"{len(need)} 项就位" + (f"，缺：{missing}" if missing else "")

    check("高清输入区 · 一键清空列表", _ui_clear_all)

    # ---- 模型真实推理 ----
    def _load_all_models():
        import numpy as np
        from core.engines.models import selectable_keys, model_exists
        from core.engines.image import enhance_image
        img = (np.random.rand(48, 64, 3) * 255).astype("uint8")
        bad, good = [], []
        for k in selectable_keys():
            if not model_exists(k):
                bad.append(f"{k}(未下载)")
                continue
            try:
                enhance_image(img, k, outscale=None, face_enhance=False, max_side=0)
                good.append(k)
            except Exception as exc:
                bad.append(f"{k}({type(exc).__name__})")
        return not bad, f"{len(good)} 个可推理" + (f"，失败：{bad}" if bad else "")

    check("全部可选模型可加载推理", _load_all_models)

    check("图标资源", lambda: (
        (ROOT / "assets" / "icon.ico").exists()
        and (ROOT / "assets" / "icon.png").exists()
        and (ROOT / "assets" / "logo.svg").exists(),
        "icon.ico / icon.png / logo.svg"))

    # ---- 桌面入口 ----
    def _desktop_funcs():
        import desktop
        p = desktop.pick_free_port()
        busy = desktop.port_in_use(p)
        return (not busy), f"动态端口 {p}，占用检测={busy}"

    check("桌面入口 · 动态端口", _desktop_funcs)

    def _singleton():
        import desktop
        first = desktop.acquire_single_instance()
        return first, "互斥体获取成功" if first else "已被占用"

    check("桌面入口 · 单实例", _singleton)

    # ---- 起服务实测 ----
    def _serve():
        import server.api as api
        import uvicorn
        api.refresh_allowed_paths()
        srv = uvicorn.Server(uvicorn.Config(
            api.app, host="127.0.0.1", port=port,
            log_level="warning", access_log=False))
        threading.Thread(target=srv.run, daemon=True).start()
        for _ in range(40):
            time.sleep(0.5)
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                continue
        else:
            return False, "服务未在 20 秒内就绪"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as r:
            body = r.read().decode("utf-8", "ignore")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=10) as r:
            import json
            ping = json.loads(r.read().decode("utf-8"))
        ok = len(body) > 1000 and ping.get("ok") is True
        return ok, f"首页 {len(body)} 字节，版本 {ping.get('version')}"

    check("FastAPI 服务启动并响应", _serve)

    def _forbidden():
        import urllib.error
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/file?path=C%3A%5CWindows%5Cwin.ini",
                timeout=10)
            return False, "越权读取竟然成功了"
        except urllib.error.HTTPError as e:
            return e.code == 403, f"越权被拒（HTTP {e.code}）"

    check("结果文件服务越权拦截", _forbidden)

    print()
    print("=" * 66)
    failed = 0
    for name, ok, detail in results:
        print(f"  {OK if ok else FAIL}  {name:<24} {detail}")
        if not ok:
            failed += 1
    print("=" * 66)
    print(f"共 {len(results)} 项，失败 {failed} 项")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
