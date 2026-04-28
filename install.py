#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
wuwo One-Click Installer
========================
负责全流程自动化安装 wuwo 环境：
  1. 下载 Python 3.12.x embeddable zip
  2. 解压到 wuwo/py_312/
  3. 修改 ._pth 启用 site-packages
  4. 安装 pip 及全部依赖（rez / PyYAML / pywin32 / PySide6 / PyQt5 / requests）
  5. 弹窗询问 rez 包路径，自动或手动更新 config.yaml
  6. 调用 auto_fetch_packages.py 拉取所有 rez 包

用法（由 install.bat 调用）:
    python install.py [--wuwo-dir <path>]

参数:
    --wuwo-dir   wuwo 仓库目录（默认 = 本脚本所在目录）
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# ─────────────────────────────────────────────
#  常量配置
# ─────────────────────────────────────────────
PYTHON_FULL_VER = "3.12.8"
PTH_PREFIX = "python312"
ZIP_NAME = f"python-{PYTHON_FULL_VER}-embed-amd64.zip"
ZIP_URL = f"https://www.python.org/ftp/python/{PYTHON_FULL_VER}/{ZIP_NAME}"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
MIN_ZIP_BYTES = 5_000_000  # 5 MB

REQUIRED_PACKAGES = [
    ("rez", "rez"),           # (pip install name, display name)
    ("PyYAML", "PyYAML"),
    ("pywin32", "pywin32"),
    ("PySide6", "PySide6"),
    ("PyQt5", "PyQt5"),
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


def err(msg: str) -> None:
    print(f"  [ERROR] {msg}", file=sys.stderr)


def download_with_progress(url: str, dest: Path) -> None:
    """下载文件并显示进度条。"""
    print(f"  URL : {url}")
    print(f"  → {dest}")

    def reporthook(block_num, block_size, total_size):
        downloaded = block_num * block_size
        if total_size > 0:
            pct = min(100, downloaded * 100 // total_size)
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            print(f"\r  [{bar}] {pct:3d}%  {downloaded // 1024 // 1024} MB", end="", flush=True)

    urllib.request.urlretrieve(url, dest, reporthook=reporthook)
    print()  # 换行


def run_pip(python_exe: Path, *args: str) -> int:
    """运行 pip 命令，返回退出码。"""
    cmd = [str(python_exe), "-m", "pip"] + list(args) + ["--no-warn-script-location"]
    result = subprocess.run(cmd)
    return result.returncode


# ─────────────────────────────────────────────
#  Step 1: 下载 Python embeddable zip
# ─────────────────────────────────────────────

def download_python(wuwo_dir: Path) -> Path:
    """下载 Python embeddable zip，若已有且大小正常则复用。返回本地 zip 路径。"""
    temp_zip = wuwo_dir / ZIP_NAME

    if temp_zip.exists():
        sz = temp_zip.stat().st_size
        if sz >= MIN_ZIP_BYTES:
            info(f"复用已有 zip ({sz // 1024 // 1024} MB): {temp_zip.name}")
            return temp_zip
        else:
            info(f"已有 zip 过小 ({sz} bytes)，重新下载。")
            temp_zip.unlink()

    download_with_progress(ZIP_URL, temp_zip)

    sz = temp_zip.stat().st_size
    if sz < MIN_ZIP_BYTES:
        temp_zip.unlink()
        raise RuntimeError(f"下载的 zip 过小 ({sz} bytes)，可能下载失败或网络错误，请重试。")

    ok(f"下载完成，大小 {sz // 1024 // 1024} MB")
    return temp_zip


# ─────────────────────────────────────────────
#  Step 2: 解压
# ─────────────────────────────────────────────

def extract_python(temp_zip: Path, python_dir: Path) -> None:
    """解压到 py_312 目录。"""
    if python_dir.exists():
        info(f"删除已有目录: {python_dir}")
        shutil.rmtree(python_dir)

    python_dir.mkdir(parents=True)
    info(f"解压 {temp_zip.name} → {python_dir}")
    with zipfile.ZipFile(temp_zip, "r") as zf:
        zf.extractall(python_dir)
    ok("解压完成。")


# ─────────────────────────────────────────────
#  Step 3: 配置 ._pth 启用 site-packages
# ─────────────────────────────────────────────

def configure_pth(python_dir: Path) -> None:
    """取消 ._pth 中 import site 的注释，启用 site-packages。"""
    pth_file = python_dir / f"{PTH_PREFIX}._pth"

    if pth_file.exists():
        content = pth_file.read_text(encoding="utf-8")
        new_content = re.sub(r"^\s*#\s*import site", "import site", content, flags=re.MULTILINE)
        if new_content != content:
            pth_file.write_text(new_content, encoding="utf-8")
            ok(f"已启用 site-packages（取消 import site 注释）。")
        else:
            info("import site 已处于启用状态。")
    else:
        warn(f"{PTH_PREFIX}._pth 不存在，手动创建默认 ._pth 文件...")
        pth_file.write_text(
            f"{PTH_PREFIX}.zip\n.\nimport site\n",
            encoding="utf-8",
        )
        ok("已创建默认 ._pth 文件。")


# ─────────────────────────────────────────────
#  Step 4: 安装 pip
# ─────────────────────────────────────────────

def install_pip(python_exe: Path, wuwo_dir: Path) -> None:
    """下载并运行 get-pip.py。"""
    get_pip_path = wuwo_dir / "get-pip.py"

    if not get_pip_path.exists():
        info(f"下载 get-pip.py ...")
        download_with_progress(GET_PIP_URL, get_pip_path)

    info("运行 get-pip.py ...")
    ret = subprocess.run([str(python_exe), str(get_pip_path), "--no-warn-script-location"]).returncode
    if ret != 0:
        raise RuntimeError("pip 安装失败！")
    ok("pip 安装成功。")


# ─────────────────────────────────────────────
#  Step 5: 安装依赖包
# ─────────────────────────────────────────────

def install_packages(python_exe: Path) -> None:
    """逐个安装 REQUIRED_PACKAGES 列表。"""
    for pip_name, display_name in REQUIRED_PACKAGES:
        info(f"安装 {display_name} ...")
        ret = run_pip(python_exe, "install", pip_name)
        if ret != 0:
            warn(f"{display_name} 安装失败，请稍后手动安装：pip install {pip_name}")
        else:
            ok(f"{display_name} 安装成功。")

        # pywin32 安装后运行 post-install 脚本
        if pip_name == "pywin32" and ret == 0:
            scripts_dir = python_exe.parent / "Scripts"
            post_install = scripts_dir / "pywin32_postinstall.py"
            if post_install.exists():
                subprocess.run(
                    [str(python_exe), str(post_install), "-install"],
                    capture_output=True,
                )
                ok("pywin32 post-install 完成。")


# ─────────────────────────────────────────────
#  Step 6: 弹窗询问 rez 包路径并更新 config.yaml
# ─────────────────────────────────────────────

def _ask_use_default_paths(build_path: Path, release_path: Path) -> bool:
    """弹出 MessageBox 询问是否使用默认路径，返回 True = 使用默认。"""
    build_str   = str(build_path).replace("\\", "/")
    release_str = str(release_path).replace("\\", "/")
    msg = (
        f"Use recommended default paths for rez packages?\n\n"
        f"  build:   {build_str}\n"
        f"  release: {release_str}\n\n"
        f"YES = use defaults (auto-update config.yaml)\n"
        f"NO  = open config.yaml in Notepad to edit manually"
    )

    # 优先使用 ctypes 调用 MessageBoxW（无需额外依赖）
    try:
        import ctypes
        MB_YESNO = 0x00000004
        MB_ICONQUESTION = 0x00000020
        result = ctypes.windll.user32.MessageBoxW(
            0,
            msg,
            "wuwo Installer - Package Paths",
            MB_YESNO | MB_ICONQUESTION,
        )
        IDYES = 6
        return result == IDYES
    except Exception as exc:
        warn(f"无法弹出 GUI 对话框: {exc}，将使用命令行询问。")

    # 回退：命令行询问
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
        content,
        flags=re.MULTILINE,
    )
    content = re.sub(
        r'(^\s+release:\s+")[^"]+(")',
        lambda m: m.group(1) + release_str + m.group(2),
        content,
        flags=re.MULTILINE,
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

    # 默认路径 = wuwo 上级目录 / rez-package-build  /  rez-packages-release
    parent = wuwo_dir.parent
    default_build   = parent / "rez-package-build"
    default_release = parent / "rez-packages-release"

    print(f"\n  推荐默认路径:")
    print(f"    packages.build   = {default_build}")
    print(f"    packages.release = {default_release}")

    use_default = _ask_use_default_paths(default_build, default_release)

    if use_default:
        info("使用默认路径，自动更新 config.yaml ...")
        _update_config_yaml(config_yaml, default_build, default_release)
    else:
        info("打开 Notepad 供手动编辑 config.yaml，保存并关闭后继续 ...")
        subprocess.run(["notepad.exe", str(config_yaml)])
        info("config.yaml 编辑完成。")


# ─────────────────────────────────────────────
#  Step 7: 拉取 rez 包
# ─────────────────────────────────────────────

def fetch_rez_packages(python_exe: Path, wuwo_dir: Path) -> None:
    """调用 auto_fetch_packages.py 下载所有 rez 包。"""
    script = wuwo_dir / "auto_fetch_packages.py"
    if not script.exists():
        warn(f"auto_fetch_packages.py 不存在，跳过包拉取。")
        return

    info("开始从 GitHub 拉取 rez 包 ...")
    ret = subprocess.run([str(python_exe), str(script)]).returncode
    if ret != 0:
        warn("部分 rez 包下载失败，可稍后手动运行:")
        warn(f"  {python_exe} {script}")
    else:
        ok("所有 rez 包拉取完成。")


# ─────────────────────────────────────────────
#  idempotency check
# ─────────────────────────────────────────────

def check_existing_python(python_exe: Path) -> bool:
    """检查 python.exe 是否可用，可用则返回 True。"""
    if not python_exe.exists():
        return False
    try:
        result = subprocess.run(
            [str(python_exe), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
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
    parser.add_argument(
        "--wuwo-dir",
        default=None,
        help="wuwo 仓库目录路径（默认 = 本脚本所在目录）",
    )
    args = parser.parse_args()

    wuwo_dir = Path(args.wuwo_dir).resolve() if args.wuwo_dir else Path(__file__).resolve().parent
    python_dir = wuwo_dir / "py_312"
    python_exe = python_dir / "python.exe"
    temp_zip   = wuwo_dir / ZIP_NAME

    print("=" * 60)
    print("  wuwo One-Click Installer")
    print(f"  wuwo 目录: {wuwo_dir}")
    print("=" * 60)

    TOTAL_STEPS = 7

    # ── Step 1-4: Python 环境（幂等，已安装则跳过）──
    python_already_ok = check_existing_python(python_exe)

    if not python_already_ok:
        step(1, TOTAL_STEPS, f"下载 Python {PYTHON_FULL_VER} embeddable 包")
        temp_zip = download_python(wuwo_dir)

        step(2, TOTAL_STEPS, "解压 Python 到 py_312/")
        extract_python(temp_zip, python_dir)

        step(3, TOTAL_STEPS, f"配置 {PTH_PREFIX}._pth 启用 site-packages")
        configure_pth(python_dir)

        step(4, TOTAL_STEPS, "安装 pip")
        install_pip(python_exe, wuwo_dir)

        # 清理临时文件
        for tmp in [temp_zip, wuwo_dir / "get-pip.py"]:
            if tmp.exists():
                tmp.unlink()
                info(f"已清理: {tmp.name}")
    else:
        info("跳过 Step 1-4（Python 已安装）。")

    step(5, TOTAL_STEPS, "安装依赖包")
    install_packages(python_exe)

    step(6, TOTAL_STEPS, "配置 rez 包路径 (config.yaml)")
    configure_rez_paths(wuwo_dir)

    step(7, TOTAL_STEPS, "拉取 rez 包（l_tray / ChatRoom / ...）")
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
