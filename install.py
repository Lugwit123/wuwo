#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
wuwo One-Click Installer
========================
全流程自动化安装 wuwo 环境：
  1. 下载 Python 3.12.x 标准安装包（含 pip / tkinter / 完整标准库）
  2. 静默安装到 wuwo/py_312/
  3. 安装依赖（rez / PyYAML / pywin32 / requests）
  4. 弹窗询问 rez 包路径，自动或手动更新 config.yaml
  5. 调用 auto_fetch_packages.py 拉取所有 rez 包

用法（由 install.bat 调用）:
    python install.py [--wuwo-dir <path>]

参数:
    --wuwo-dir       wuwo 仓库目录（默认 = 本脚本所在目录）
    --skip-config    跳过 rez 路径配置弹窗（测试/CI 用）
    --skip-packages  跳过拉取 rez 包（测试/CI 用）
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

# ─────────────────────────────────────────────
#  常量配置
# ─────────────────────────────────────────────
PYTHON_FULL_VER = "3.12.8"
# 标准安装包（含 pip、tkinter、完整标准库）
INSTALLER_NAME = f"python-{PYTHON_FULL_VER}-amd64.exe"
INSTALLER_URL  = f"https://www.python.org/ftp/python/{PYTHON_FULL_VER}/{INSTALLER_NAME}"
MIN_INSTALLER_BYTES = 20_000_000  # 标准安装包约 25 MB，小于 20 MB 视为损坏

# PySide6 / PyQt5 由各子包按需声明依赖，wuwo 核心只装最小集合
REQUIRED_PACKAGES = [
    ("rez",      "rez"),
    ("PyYAML",   "PyYAML"),
    ("pywin32",  "pywin32"),
    ("requests", "requests"),
]


# ─────────────────────────────────────────────
#  工具函数
# ─────────────────────────────────────────────

def step(n: int, total: int, msg: str) -> None:
    print(f"\n[{n}/{total}] {msg}")
    print("─" * 60)


def ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def info(msg: str) -> None:
    print(f"  [INFO] {msg}")


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}", file=sys.stderr)


def download_with_progress(url: str, dest: Path) -> None:
    """下载文件并显示进度条。"""
    print(f"  URL : {url}")
    print(f"  →   {dest.name}")

    def reporthook(block_num, block_size, total_size):
        downloaded = block_num * block_size
        if total_size > 0:
            pct = min(100, downloaded * 100 // total_size)
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            mb  = downloaded // 1024 // 1024
            total_mb = total_size // 1024 // 1024
            print(f"\r  [{bar}] {pct:3d}%  {mb}/{total_mb} MB", end="", flush=True)

    urllib.request.urlretrieve(url, dest, reporthook=reporthook)
    print()


def run_pip(python_exe: Path, *args: str) -> int:
    """运行 pip 命令，返回退出码。"""
    cmd = [str(python_exe), "-m", "pip"] + list(args) + ["--no-warn-script-location"]
    return subprocess.run(cmd).returncode


# ─────────────────────────────────────────────
#  Step 1-2: 下载 + 静默安装标准 Python
# ─────────────────────────────────────────────

def download_python_installer(wuwo_dir: Path) -> Path:
    """下载标准安装包，已有且大小正常则复用。"""
    dest = wuwo_dir / INSTALLER_NAME

    if dest.exists():
        sz = dest.stat().st_size
        if sz >= MIN_INSTALLER_BYTES:
            info(f"复用已有安装包 ({sz // 1024 // 1024} MB): {dest.name}")
            return dest
        info(f"已有安装包过小 ({sz} bytes)，重新下载。")
        dest.unlink()

    download_with_progress(INSTALLER_URL, dest)

    sz = dest.stat().st_size
    if sz < MIN_INSTALLER_BYTES:
        dest.unlink()
        raise RuntimeError(
            f"下载的安装包过小 ({sz} bytes)，可能损坏，请重试。"
        )
    ok(f"下载完成，大小 {sz // 1024 // 1024} MB")
    return dest


def install_python(installer: Path, python_dir: Path) -> None:
    """静默安装 Python 到 python_dir，包含 pip 与 tkinter。"""
    if python_dir.exists():
        info(f"删除已有目录: {python_dir}")
        shutil.rmtree(python_dir)

    python_dir.mkdir(parents=True)
    info(f"静默安装 Python {PYTHON_FULL_VER} → {python_dir}")
    info("（首次安装约需 1~2 分钟，请稍候…）")

    # 静默安装参数说明：
    #   /quiet          无 UI
    #   TargetDir       安装目录
    #   Include_pip=1   包含 pip
    #   Include_tcltk=1 包含 tkinter / tcl/tk
    #   InstallAllUsers=0  仅当前用户（无需管理员）
    #   PrependPath=0   不修改系统 PATH
    cmd = [
        str(installer),
        "/quiet",
        f"TargetDir={python_dir}",
        "Include_pip=1",
        "Include_tcltk=1",
        "InstallAllUsers=0",
        "PrependPath=0",
        "Shortcuts=0",
    ]
    result = subprocess.run(cmd, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"Python 安装失败（exit {result.returncode}）。\n"
            f"请尝试手动运行: {installer}"
        )
    ok(f"Python {PYTHON_FULL_VER} 安装完成。")


# ─────────────────────────────────────────────
#  Step 3: 安装依赖包
# ─────────────────────────────────────────────

def install_packages(python_exe: Path) -> None:
    """逐个安装 REQUIRED_PACKAGES。"""
    for pip_name, display_name in REQUIRED_PACKAGES:
        info(f"安装 {display_name} ...")
        ret = run_pip(python_exe, "install", pip_name)
        if ret != 0:
            warn(f"{display_name} 安装失败，稍后可手动运行: pip install {pip_name}")
        else:
            ok(f"{display_name} 安装成功。")

        # pywin32 安装后需执行 post-install 脚本
        if pip_name == "pywin32" and ret == 0:
            post = python_exe.parent / "Scripts" / "pywin32_postinstall.py"
            if post.exists():
                subprocess.run(
                    [str(python_exe), str(post), "-install"],
                    capture_output=True,
                )
                ok("pywin32 post-install 完成。")


# ─────────────────────────────────────────────
#  Step 4: 弹窗询问 rez 包路径并更新 config.yaml
# ─────────────────────────────────────────────

def _ask_use_default_paths(build_path: Path, release_path: Path) -> bool:
    """弹出对话框询问是否使用默认路径。优先用 tkinter，失败回退命令行。"""
    build_str   = str(build_path).replace("\\", "/")
    release_str = str(release_path).replace("\\", "/")
    title = "wuwo Installer - Package Paths"
    msg = (
        f"Use recommended default paths for rez packages?\n\n"
        f"  build:   {build_str}\n"
        f"  release: {release_str}\n\n"
        f"YES = use defaults (auto-update config.yaml)\n"
        f"NO  = open config.yaml in Notepad to edit manually"
    )

    # tkinter —— 标准安装版 Python 内置，直接可用
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        result = messagebox.askyesno(title, msg)
        root.destroy()
        return result
    except Exception as exc:
        warn(f"tkinter 弹窗失败: {exc}，使用命令行询问。")

    # 回退：命令行
    while True:
        choice = input("\n是否使用推荐默认路径？[Y/N]: ").strip().upper()
        if choice in ("Y", "YES"):
            return True
        if choice in ("N", "NO"):
            return False
        print("  请输入 Y 或 N。")


def _update_config_yaml(config_yaml: Path, build_path: Path, release_path: Path) -> None:
    """用正则替换 config.yaml 中的 build/release 路径。"""
    build_str   = str(build_path).replace("\\", "/")
    release_str = str(release_path).replace("\\", "/")

    content = config_yaml.read_text(encoding="utf-8")
    content = re.sub(
        r'(^\s+build:\s+")[^"]+(")',
        lambda m: m.group(1) + build_str + m.group(2),
        content, flags=re.MULTILINE,
    )
    content = re.sub(
        r'(^\s+release:\s+")[^"]+(")',
        lambda m: m.group(1) + release_str + m.group(2),
        content, flags=re.MULTILINE,
    )
    config_yaml.write_text(content, encoding="utf-8")
    ok(f"config.yaml 已更新:")
    ok(f"  packages.build   = {build_str}")
    ok(f"  packages.release = {release_str}")


def configure_rez_paths(wuwo_dir: Path) -> None:
    """询问用户是否使用默认 rez 包路径并更新 config.yaml。"""
    config_yaml = wuwo_dir / "config.yaml"
    if not config_yaml.exists():
        warn("config.yaml 不存在，跳过路径配置。")
        return

    parent = wuwo_dir.parent
    default_build   = parent / "rez-package-build"
    default_release = parent / "rez-packages-release"

    print(f"\n  推荐默认路径:")
    print(f"    packages.build   = {default_build}")
    print(f"    packages.release = {default_release}")

    if _ask_use_default_paths(default_build, default_release):
        info("使用默认路径，自动更新 config.yaml ...")
        _update_config_yaml(config_yaml, default_build, default_release)
    else:
        info("打开 Notepad 供手动编辑，保存并关闭后继续 ...")
        subprocess.run(["notepad.exe", str(config_yaml)])
        info("config.yaml 编辑完成。")


# ─────────────────────────────────────────────
#  Step 5: 拉取 rez 包
# ─────────────────────────────────────────────

def fetch_rez_packages(python_exe: Path, wuwo_dir: Path) -> None:
    """调用 auto_fetch_packages.py 下载所有 rez 包。"""
    script = wuwo_dir / "auto_fetch_packages.py"
    if not script.exists():
        warn("auto_fetch_packages.py 不存在，跳过包拉取。")
        return

    info("开始从 GitHub 拉取 rez 包 ...")
    ret = subprocess.run([str(python_exe), str(script)]).returncode
    if ret != 0:
        warn("部分 rez 包下载失败，可稍后手动运行:")
        warn(f"  {python_exe} {script}")
    else:
        ok("所有 rez 包拉取完成。")


# ─────────────────────────────────────────────
#  幂等检查
# ─────────────────────────────────────────────

def check_existing_python(python_exe: Path) -> bool:
    """python.exe 可用则返回 True。"""
    if not python_exe.exists():
        return False
    try:
        result = subprocess.run(
            [str(python_exe), "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            ver = result.stdout.strip() or result.stderr.strip()
            info(f"Python 已安装: {ver}")
            info("如需重新安装，请先删除 py_312 目录再运行此脚本。")
            return True
    except Exception:
        pass
    warn("python.exe 存在但不可用，将重新安装。")
    return False


# ─────────────────────────────────────────────
#  主入口
# ─────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="wuwo One-Click Installer")
    parser.add_argument("--wuwo-dir",      default=None,        help="wuwo 仓库目录")
    parser.add_argument("--skip-config",   action="store_true", help="跳过 rez 路径配置（测试/CI）")
    parser.add_argument("--skip-packages", action="store_true", help="跳过拉取 rez 包（测试/CI）")
    args = parser.parse_args()

    wuwo_dir   = Path(args.wuwo_dir).resolve() if args.wuwo_dir else Path(__file__).resolve().parent
    python_dir = wuwo_dir / "py_312"
    python_exe = python_dir / "python.exe"

    print("=" * 60)
    print("  wuwo One-Click Installer")
    print(f"  wuwo 目录: {wuwo_dir}")
    print("=" * 60)

    TOTAL_STEPS = 5

    # ── Step 1-2: Python 环境（幂等）──
    if check_existing_python(python_exe):
        info("跳过 Step 1-2（Python 已安装）。")
    else:
        step(1, TOTAL_STEPS, f"下载 Python {PYTHON_FULL_VER} 标准安装包")
        installer = download_python_installer(wuwo_dir)

        step(2, TOTAL_STEPS, f"静默安装 Python {PYTHON_FULL_VER} → py_312/")
        install_python(installer, python_dir)

        # 安装完成后清理安装包
        installer.unlink(missing_ok=True)
        info(f"已清理安装包: {installer.name}")

    # ── Step 3: 安装依赖包 ──
    step(3, TOTAL_STEPS, "安装依赖包")
    install_packages(python_exe)

    # ── Step 4: 配置 rez 路径 ──
    if args.skip_config:
        info("--skip-config: 跳过 rez 路径配置。")
    else:
        step(4, TOTAL_STEPS, "配置 rez 包路径 (config.yaml)")
        configure_rez_paths(wuwo_dir)

    # ── Step 5: 拉取 rez 包 ──
    if args.skip_packages:
        info("--skip-packages: 跳过 rez 包拉取。")
    else:
        step(5, TOTAL_STEPS, "拉取 rez 包（l_tray / ChatRoom / ...）")
        fetch_rez_packages(python_exe, wuwo_dir)

    print("\n" + "=" * 60)
    print("  安装完成！")
    print("=" * 60)
    print(f"  Python : {python_exe}")
    print(f"  wuwo   : {wuwo_dir}")
    print(f"  配置   : {wuwo_dir / 'config.yaml'}")
    print()
    print("  启动 wuwo 环境请运行:")
    print(f"    {wuwo_dir / 'wuwo.bat'}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
