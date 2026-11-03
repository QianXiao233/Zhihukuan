#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X-AnyLabeling 启动器（配合 start_labeler.bat 使用）。

单独放一个 .py 而不是在 bat 里写 python -c：cmd 里嵌套引号非常脆弱，
路径带空格/反斜杠时经常被截断。这里用文件参数传目录，干净可靠。

用法：
    python launch_labeler.py                      # 打开当前目录
    python launch_labeler.py raw_v2/images         # 打开指定目录
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    # 参数：第一个非选项参数当作图片目录
    target = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    path = Path(target).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.is_dir():
        print(f"[launcher] 目录不存在：{path}", file=sys.stderr)
        return 2

    # Qt5 在 Windows 上需要字体目录，指向系统字体以消除告警
    if os.name == "nt" and Path(r"C:\Windows\Fonts").is_dir():
        os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

    print(f"[launcher] 打开目录：{path}")
    try:
        from anylabeling.app import main as any_main
    except ImportError as exc:
        print(f"[launcher] 导入失败：{exc}", file=sys.stderr)
        print("[launcher] 请确认当前 Python 是标注专用环境（D:\\tools\\labeler-venv）", file=sys.stderr)
        return 3

    sys.argv = ["xanylabeling", "--filename", str(path)]
    return int(any_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
