#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
auto_fetch_packages.py
自动检测并从 GitHub 下载缺失的 rez 包到 rez-package-source 目录

用法:
    python auto_fetch_packages.py                    # 自动检查并下载
    python auto_fetch_packages.py --check-only       # 仅检查，不下载
    python auto_fetch_packages.py --package l_tray   # 仅处理指定包
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

GITHUB_OWNER = "Lugwit123"
GITHUB_BASE_URL = f"https://github.com/{GITHUB_OWNER}"

# 包名 → GitHub 仓库名 的映射
# repo: GitHub 仓库名（与包名同名）
# init_bat: clone 后需要运行的初始化脚本（相对于包目录），None 表示无需初始化
PACKAGE_REGISTRY: Dict[str, dict] = {
    "ChatRoom": {"repo": "ChatRoom", "init_bat": None},
    "L_Tools": {"repo": "L_Tools", "init_bat": None},
    "Lugwit_Module": {"repo": "Lugwit_Module", "init_bat": None},
    "conemu": {"repo": "conemu", "init_bat": None},
    "l_notepad": {"repo": "l_notepad", "init_bat": None},
    "l_scheduler": {"repo": "l_scheduler", "init_bat": None},
    "l_tray": {"repo": "l_tray", "init_bat": None},
    "lperforce": {"repo": "lperforce", "init_bat": None},
    "lugwit_auth": {"repo": "lugwit_auth", "init_bat": None},
    "postgresql": {"repo": "postgresql", "init_bat": "999.0/init.bat"},
    "pyfory": {"repo": "pyfory", "init_bat": None},
    "pyqt5": {"repo": "pyqt5", "init_bat": None},
    "pyside6": {"repo": "pyside6", "init_bat": None},
    "python": {"repo": "python", "init_bat": "init.bat"},
    "pytracemp": {"repo": "pytracemp", "init_bat": None},
    "pywin32": {"repo": "pywin32", "init_bat": None},
    "start_multi_app": {"repo": "start_multi_app", "init_bat": None},
    "view_pkl_tool": {"repo": "view_pkl_tool", "init_bat": None},
}


def find_rez_package_source(override: Optional[str] = None) -> Path:
    """从脚本位置推算 rez-package-source 路径，或使用手动指定的路径。

    目录结构: trayapp/wuwo/auto_fetch_packages.py
              trayapp/rez-package-source/

    Args:
        override: 手动指定的路径，为 None 时自动推算

    Returns:
        rez-package-source 目录的 Path 对象
    """
    if override:
        return Path(override).resolve()
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent / "rez-package-source"


def check_missing_packages(
    source_dir: Path, filter_packages: Optional[List[str]] = None
) -> Tuple[List[str], List[str]]:
    """检查哪些注册表中的包在本地不存在。

    Args:
        source_dir: rez-package-source 目录路径
        filter_packages: 仅检查指定的包名列表，为 None 时检查全部

    Returns:
        (existing, missing) 两个列表
    """
    registry = PACKAGE_REGISTRY
    if filter_packages:
        registry = {k: v for k, v in registry.items() if k in filter_packages}

    existing: List[str] = []
    missing: List[str] = []

    for pkg_name in sorted(registry.keys()):
        pkg_dir = source_dir / pkg_name
        if pkg_dir.is_dir():
            existing.append(pkg_name)
        else:
            missing.append(pkg_name)

    return existing, missing


def _check_git_available() -> bool:
    """检查 git 是否可用。"""
    try:
        subprocess.run(
            ["git", "--version"],
            capture_output=True,
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def clone_package(package_name: str, repo_name: str, target_dir: Path) -> Tuple[bool, str]:
    """从 GitHub clone 包到目标目录。

    Args:
        package_name: 包名（同时用作本地目录名）
        repo_name: GitHub 仓库名
        target_dir: rez-package-source 目录

    Returns:
        (success, message)
    """
    url = f"https://github.com/{GITHUB_OWNER}/{repo_name}.git"
    dest = target_dir / package_name

    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            return False, f"git clone 失败: {stderr}"

        # 设置 core.longpaths = true
        subprocess.run(
            ["git", "config", "core.longpaths", "true"],
            cwd=str(dest),
            capture_output=True,
            text=True,
        )

        return True, "克隆完成 ✓"

    except subprocess.TimeoutExpired:
        # 超时后清理不完整的目录
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        return False, "git clone 超时（300s）"
    except FileNotFoundError:
        return False, "git 命令未找到，请确保 git 已安装并在 PATH 中"
    except Exception as e:
        return False, f"克隆异常: {e}"


def run_init_script(package_dir: Path, init_bat_path: str) -> Tuple[bool, str]:
    """运行 init.bat 初始化脚本。

    Args:
        package_dir: 包目录路径
        init_bat_path: init.bat 相对于包目录的路径

    Returns:
        (success, message)
    """
    init_path = package_dir / init_bat_path
    if not init_path.exists():
        return True, f"init 脚本不存在，跳过: {init_bat_path}"

    try:
        result = subprocess.run(
            ["cmd", "/c", str(init_path)],
            cwd=str(init_path.parent),
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() if result.stderr else "(无错误输出)"
            return False, f"init 脚本执行失败 (exit {result.returncode}): {stderr}"
        return True, "init 脚本执行完成 ✓"

    except subprocess.TimeoutExpired:
        return False, f"init 脚本执行超时（600s）: {init_bat_path}"
    except Exception as e:
        return False, f"init 脚本异常: {e}"


def print_status_table(existing: List[str], missing: List[str]) -> None:
    """打印包状态表格。"""
    print("\n[检查] 扫描 rez-package-source 目录...")

    # 合并排序后按状态输出
    all_pkgs = [(name, True) for name in existing] + [(name, False) for name in missing]
    all_pkgs.sort(key=lambda x: x[0])

    max_name_len = max((len(name) for name, _ in all_pkgs), default=0)

    for name, exists in all_pkgs:
        status = "[✓]" if exists else "[✗]"
        state = "已存在" if exists else "缺失"
        print(f"  {status} {name:<{max_name_len}}  {state}")

    print()


def main() -> int:
    """主入口。"""
    parser = argparse.ArgumentParser(
        description="自动检测并从 GitHub 下载缺失的 rez 包到 rez-package-source 目录"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="仅检查缺失包，不下载",
    )
    parser.add_argument(
        "--package",
        action="append",
        dest="packages",
        metavar="NAME",
        help="仅处理指定包（可多次指定）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="即使包已存在也重新下载（删除后重新 clone）",
    )
    parser.add_argument(
        "--skip-init",
        action="store_true",
        help="clone 后不运行 init.bat",
    )
    parser.add_argument(
        "--source-dir",
        metavar="DIR",
        help="手动指定 rez-package-source 路径",
    )

    args = parser.parse_args()

    # 验证指定的包名
    if args.packages:
        unknown = [p for p in args.packages if p not in PACKAGE_REGISTRY]
        if unknown:
            print(f"[错误] 未知的包名: {', '.join(unknown)}", file=sys.stderr)
            print(f"       可用的包: {', '.join(sorted(PACKAGE_REGISTRY.keys()))}", file=sys.stderr)
            return 1

    # 确定 rez-package-source 路径
    source_dir = find_rez_package_source(args.source_dir)
    if not source_dir.exists():
        print(f"[错误] rez-package-source 目录不存在: {source_dir}", file=sys.stderr)
        return 1

    print(f"[信息] rez-package-source: {source_dir}")

    # 扫描包状态
    existing, missing = check_missing_packages(source_dir, args.packages)

    # --force 模式：将已存在的包也视为需要处理
    if args.force and existing:
        force_targets = list(existing)
        missing = sorted(set(missing + force_targets))
        existing = [e for e in existing if e not in force_targets]

    # 打印状态
    print_status_table(existing, missing)

    if not missing:
        print("[完成] 所有包已就绪，无需下载")
        return 0

    if args.check_only:
        print(f"[信息] 共 {len(missing)} 个包缺失（--check-only 模式，不下载）")
        return 0

    # 检查 git
    if not _check_git_available():
        print("[错误] git 命令不可用，请确保 git 已安装并在 PATH 中", file=sys.stderr)
        return 1

    # 下载缺失包
    print(f"[下载] 开始下载 {len(missing)} 个缺失包...\n")

    success_count = 0
    fail_count = 0
    init_fail_count = 0

    for idx, pkg_name in enumerate(missing, 1):
        info = PACKAGE_REGISTRY[pkg_name]
        repo_name = info["repo"]
        init_bat = info["init_bat"]
        pkg_dir = source_dir / pkg_name

        print(f"[{idx}/{len(missing)}] 正在克隆 {pkg_name} ...")
        print(f"      git clone --depth 1 https://github.com/{GITHUB_OWNER}/{repo_name}.git")

        # --force 模式下先删除已有目录
        if args.force and pkg_dir.exists():
            print(f"      (--force) 删除已有目录...")
            try:
                shutil.rmtree(pkg_dir)
            except Exception as e:
                print(f"      [错误] 删除失败: {e}")
                fail_count += 1
                continue

        ok, msg = clone_package(pkg_name, repo_name, source_dir)

        if not ok:
            print(f"      [错误] {msg}")
            fail_count += 1
            continue

        print(f"      {msg}")
        success_count += 1

        # 运行 init.bat
        if init_bat and not args.skip_init:
            print(f"      运行初始化脚本: {init_bat}")
            init_ok, init_msg = run_init_script(pkg_dir, init_bat)
            if not init_ok:
                print(f"      [警告] {init_msg}")
                init_fail_count += 1
            else:
                print(f"      {init_msg}")

    # 汇总
    print()
    if fail_count == 0:
        print(f"[完成] 全部 {success_count} 个包下载成功")
    else:
        print(f"[完成] {success_count} 个成功, {fail_count} 个失败")

    if init_fail_count > 0:
        print(f"[警告] {init_fail_count} 个 init 脚本执行失败（不影响包可用性）")

    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
