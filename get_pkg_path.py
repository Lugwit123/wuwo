#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
get_pkg_path.py  --  读取 config.yaml 中的包路径并输出到 stdout
供 wuwo.bat 通过 for /f 捕获路径使用。

用法:
    python get_pkg_path.py <key>

参数:
    key    config.yaml packages 节下的字段名，如 source / third_party / build / release

找不到或为空时，输出对应默认路径（相对于本脚本所在目录的上级目录）。
退出码: 0 正常，1 异常（但也会输出默认路径，不影响 wuwo.bat 使用）
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULTS = {
    "source":      SCRIPT_DIR.parent / "rez-package-source",
    "third_party": SCRIPT_DIR.parent / "rez-package-3rd",
    "build":       SCRIPT_DIR.parent / "rez-package-build",
    "release":     SCRIPT_DIR.parent / "rez-package-release",
    "local":       SCRIPT_DIR / "packages",
}


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: get_pkg_path.py <key>", file=sys.stderr)
        return 1

    key = sys.argv[1]
    default = DEFAULTS.get(key)
    if default is None:
        print(f"Unknown key: {key}", file=sys.stderr)
        return 1

    config_yaml = SCRIPT_DIR / "config.yaml"
    if not config_yaml.exists():
        print(str(default))
        return 0

    try:
        import yaml
        cfg = yaml.safe_load(config_yaml.read_text(encoding="utf-8")) or {}
        val = cfg.get("packages", {}).get(key, "")
        if val:
            # 支持相对路径（相对于 config.yaml 所在目录）
            p = Path(val)
            if not p.is_absolute():
                p = (SCRIPT_DIR / p).resolve()
            print(str(p))
        else:
            print(str(default))
    except Exception:
        print(str(default))

    return 0


if __name__ == "__main__":
    sys.exit(main())
