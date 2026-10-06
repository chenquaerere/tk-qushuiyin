"""重新生成根目录的 CHANGELOG.md（v4.0 新增）。

CHANGELOG.md 是**产物**，数据源是 core/changelog.py 的 RELEASES。
以前靠手工同步，很容易漏（v4.0.0 就漏了：代码里加了条目，
但根目录 CHANGELOG.md 还停在 v3.0.1）。

用法：
    venv\\Scripts\\python.exe scripts\\gen_changelog.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.version import BUILD_DATE, VERSION          # noqa: E402
from core import changelog as cl                       # noqa: E402


def main() -> int:
    parts = [
        "# 更新日志",
        "",
        "> 本文件由 `core/changelog.py` 生成，请勿手工编辑。",
        "> 改版本时在 `RELEASES` 顶部新增一条记录，然后运行：",
        "> `venv\\Scripts\\python.exe scripts\\gen_changelog.py`",
        "",
        f"当前版本：**v{VERSION}** · 构建日期 {BUILD_DATE}",
        "",
        "---",
        "",
    ]
    for rel in cl.RELEASES:
        parts.append(cl.render_markdown(rel))
        parts.append("")
        parts.append("---")
        parts.append("")

    text = "\n".join(parts).rstrip() + "\n"
    out = ROOT / "CHANGELOG.md"
    out.write_text(text, encoding="utf-8")
    print(f"已生成 {out}")
    print(f"  版本 {VERSION} · 构建日期 {BUILD_DATE}")
    print(f"  收录 {len(cl.RELEASES)} 个版本，{len(text.splitlines())} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
