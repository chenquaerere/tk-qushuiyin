import json
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "output"

DEFAULTS = {
    "output_root": str(DEFAULT_OUTPUT_ROOT),
    "date_folder": True,
    "face_enhance": False,
    "face_work_side": 4096,
    "image_model": "realesr-general-x4v3",
    "image_scale": 4,
    "tile": 0,
    "half": True,
    "video_model": "realesr-general-x4v3",
    "video_scale": 2,
    "video_encoder": "auto",
    "video_crf": 18,
    "interpolate": False,
    "skip_existing": True,
    "keep_frames": False,
    "max_output_size": 4096,
    "video_max_side": 1920,
    "video_skip_similar": True,
    "video_skip_thr": 1.5,
    "video_sharp": True,
    "beep_on_done": True,
    "lan_access": False,
    "lan_password": "",
    # 已展示过更新通知的版本号（用于「本次更新」提示只出现一次）
    "last_seen_version": "",
}

_lock = threading.Lock()


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save(cfg: dict) -> None:
    with _lock:
        CONFIG_PATH.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def get(key: str):
    return load()[key]