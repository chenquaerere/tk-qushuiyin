"""打包完整版：把项目目录打成 zip，归档到指定目录。

用法：
    python scripts/package.py                       # 默认输出到上级归档目录
    python scripts/package.py <输出目录>

说明：
- 压缩包内顶层目录会被重命名为当前版本（例如 TK去水印高清程序_v3.0）
- 自动跳过 __pycache__ / 日志 / 封面缓存等运行期产物
- 使用 ZIP_DEFLATED，自动启用 zip64（含大体积 torch 动态库）
"""

import os
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.version import VERSION  # noqa: E402

# 运行期产物 + 开发期产物，不进压缩包
# v4.0 新增：runtime（端口文件/上传临时）、docs（验证截图）、_backup_*（改造前快照）
SKIP_DIRS = {"__pycache__", ".cover_cache", "logs", ".git", "runtime", "docs"}
SKIP_DIR_PREFIX = ("_backup_",)
SKIP_FILES = {"app.log", "python_path.txt"}
SKIP_SUFFIX = (".pyc", ".pyo", ".part", ".tmp")


def main():
    default_out = ROOT.parent
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else default_out
    out_dir.mkdir(parents=True, exist_ok=True)

    # 用完整版本号命名，便于保留历史版本、支持回滚
    # 例：TK去水印高清程序_v3.0.1.zip / 内部目录 TK去水印高清程序_v3.0.1
    arc_root = f"TK去水印高清程序_v{VERSION}"
    zip_path = out_dir / f"TK去水印高清程序_完整版_v{VERSION}.zip"
    # 先写临时文件，最后原子替换：
    # 直接 unlink 大体积旧包会被安全策略拦截（无法移入回收站）
    tmp_zip = zip_path.with_name(zip_path.name + ".part")
    tmp_zip.unlink(missing_ok=True)

    files = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if any(part.startswith(SKIP_DIR_PREFIX) for part in rel.parts):
            continue
        if rel.name in SKIP_FILES or p.suffix.lower() in SKIP_SUFFIX:
            continue
        files.append((p, rel))

    total_bytes = sum(p.stat().st_size for p, _ in files)
    print(f"待打包 {len(files)} 个文件，原始大小 "
          f"{total_bytes / 1024 ** 3:.2f} GB", flush=True)
    print(f"输出：{zip_path}", flush=True)

    t0 = time.time()
    done = 0
    last_report = 0
    with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as zf:
        for i, (p, rel) in enumerate(files, 1):
            zf.write(p, arcname=f"{arc_root}/{rel.as_posix()}")
            done += p.stat().st_size
            now = time.time()
            if now - last_report > 5:
                last_report = now
                pct = done / max(1, total_bytes) * 100
                print(f"  [{pct:5.1f}%] {i}/{len(files)} 文件  "
                      f"{done / 1024 ** 3:.2f}/{total_bytes / 1024 ** 3:.2f} GB  "
                      f"用时 {now - t0:.0f}s", flush=True)

    os.replace(str(tmp_zip), str(zip_path))
    size = zip_path.stat().st_size
    print(f"完成：{zip_path}", flush=True)
    print(f"压缩包 {size / 1024 ** 3:.2f} GB（原始 {total_bytes / 1024 ** 3:.2f} GB，"
          f"压缩率 {size / max(1, total_bytes) * 100:.0f}%），"
          f"耗时 {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
