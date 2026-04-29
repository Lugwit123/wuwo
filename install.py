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
PYTHON_FULL_VER = "3.12.10"
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


def read_config_paths(wuwo_dir: Path) -> dict:
    """从 config.yaml 读取各路径配置，空值时返回相对于 wuwo_dir.parent 的默认路径。"""
    config_yaml = wuwo_dir / "config.yaml"
    parent = wuwo_dir.parent
    defaults = {
        "source":      parent / "rez-package-source",
        "third_party": parent / "rez-package-3rd",
        "build":       parent / "rez-package-build",
        "release":     parent / "rez-package-release",
        "local":       wuwo_dir / "packages",
    }
    if not config_yaml.exists():
        return defaults
    try:
        import yaml
        cfg = yaml.safe_load(config_yaml.read_text(encoding="utf-8")) or {}
        pkgs = cfg.get("packages", {})
        result = {}
        for key, default in defaults.items():
            val = pkgs.get(key, "")
            result[key] = Path(val).resolve() if val else default
        return result
    except Exception as e:
        warn(f"读取 config.yaml 失败: {e}，使用默认路径。")
        return defaults


def configure_rez_paths(wuwo_dir: Path) -> None:
    """询问用户是否使用默认 rez 包路径并更新 config.yaml。"""
    config_yaml = wuwo_dir / "config.yaml"
    if not config_yaml.exists():
        warn("config.yaml 不存在，跳过路径配置。")
        return

    parent = wuwo_dir.parent
    default_build   = parent / "rez-package-build"
    default_release = parent / "rez-package-release"

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
#  Step 5: 拉取 l_tray rez 包
# ─────────────────────────────────────────────

def fetch_ltray_package(rez_source_dir: Path) -> None:
    """仅 clone l_tray 到 rez-package-source，rez 会自动解析依赖。"""
    import subprocess
    pkg_dir = rez_source_dir / "l_tray"
    if pkg_dir.exists():
        # 已存在则 pull 最新
        info(f"l_tray 已存在，尝试 git pull ...")
        result = subprocess.run(
            ["git", "-C", str(pkg_dir), "pull", "--ff-only"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            ok("l_tray git pull 完成。")
        else:
            warn(f"git pull 失败（可能有本地改动），继续使用现有版本。")
        return

    url = "https://github.com/Lugwit123/l_tray.git"
    info(f"克隆 l_tray → {pkg_dir}")
    info(f"  {url}")
    result = subprocess.run(
        ["git", "clone", "--depth", "1", url, str(pkg_dir)],
        timeout=300
    )
    if result.returncode != 0:
        raise RuntimeError("git clone l_tray 失败，请检查网络或 GitHub 访问权限。")
    # 设置长路径支持
    subprocess.run(
        ["git", "config", "core.longpaths", "true"],
        cwd=str(pkg_dir), capture_output=True
    )
    ok(f"l_tray 克隆完成: {pkg_dir}")


# ─────────────────────────────────────────────
#  Step 6: 按需安装第三方包到 rez-package-3rd
# ─────────────────────────────────────────────

def _parse_ltray_requires(rez_source_dir: Path) -> list[str]:
    """从 l_tray/package.py 读取 requires 列表，返回包名列表（去除版本约束）。"""
    import re
    pkg_files = list((rez_source_dir / "l_tray").glob("*/package.py"))
    if not pkg_files:
        warn("l_tray/package.py 未找到，跳过第三方包安装。")
        return []
    content = pkg_files[0].read_text(encoding="utf-8")
    # 提取 requires = [...] 列表
    m = re.search(r'requires\s*=\s*\[([^\]]+)\]', content, re.S)
    if not m:
        return []
    raw = m.group(1)
    # 提取各字符串内容，取包名部分（去除 -3.12+<3.13 等版本约束）
    names = re.findall(r'["\']([\w]+)', raw)
    return [n.lower() for n in names]


def install_third_party_packages(python_exe: Path, wuwo_dir: Path, rez_source_dir: Path, rez_3rd_dir: Path) -> None:
    """读取 third_party_packages.yaml，对照 l_tray requires，按需安装到 rez-package-3rd。"""
    yaml_file = wuwo_dir / "third_party_packages.yaml"
    if not yaml_file.exists():
        warn("third_party_packages.yaml 不存在，跳过第三方包安装。")
        return

    try:
        import yaml
        registry = yaml.safe_load(yaml_file.read_text(encoding="utf-8")).get("packages", {})
    except ImportError:
        warn("PyYAML 未安装，跳过第三方包安装。可手动运行: pip install PyYAML")
        return

    # 获取 l_tray 的实际需求列表
    ltray_requires = _parse_ltray_requires(rez_source_dir)
    info(f"l_tray requires: {ltray_requires}")

    # 对照：只安装 requires 里有的第三方包
    to_install = {
        name: meta for name, meta in registry.items()
        if name.lower() in ltray_requires
    }

    if not to_install:
        info("无需要安装的第三方包。")
        return

    info(f"将安装 {len(to_install)} 个第三方包: {list(to_install.keys())}")

    for pkg_name, meta in to_install.items():
        rez_ver = meta.get("rez_ver", "999.0")
        pkg_dir = rez_3rd_dir / pkg_name / rez_ver

        if (pkg_dir / "package.py").exists():
            info(f"[skip] {pkg_name} 已存在: {pkg_dir}")
            continue

        info(f"安装 {pkg_name} ({meta.get('description', '')}) ...")
        pkg_dir.mkdir(parents=True, exist_ok=True)
        pkg_type = meta.get("type", "pip")

        if pkg_type == "pip":
            _install_pip_package(python_exe, pkg_name, meta, pkg_dir)
        elif pkg_type == "github":
            _install_github_package(pkg_name, meta, pkg_dir)
        else:
            warn(f"  未知安装类型: {pkg_type}，跳过。")


def _install_pip_package(python_exe: Path, pkg_name: str, meta: dict, pkg_dir: Path) -> None:
    """pip install 安装到 pkg_dir/.{pkg_name}/ 并生成 package.py。"""
    pip_name = meta.get("pip_name", pkg_name)
    python_ver = meta.get("python_ver", "3.12")
    rez_ver = meta.get("rez_ver", "999.0")
    hidden_dir = pkg_dir / f".{pkg_name}"

    ret = run_pip(python_exe, "install", pip_name,
                  "--target", str(hidden_dir),
                  "--no-warn-script-location",
                  "--quiet")
    if ret != 0:
        warn(f"  {pkg_name} pip install 失败，可手动安装: pip install {pip_name}")
        return

    # 生成 rez package.py
    package_py = pkg_dir / "package.py"
    package_py.write_text(
        f'# -*- coding: utf-8 -*-\n'
        f'name = "{pkg_name}"\n'
        f'version = "{rez_ver}"\n'
        f'description = "{meta.get("description", pkg_name)}"\n'
        f'requires = ["python-{python_ver}+<{python_ver.rsplit(".", 1)[0] + "." + str(int(python_ver.rsplit(".", 1)[-1]) + 1) if "." in python_ver else python_ver}"]\n'
        f'build_command = False\n'
        f'cachable = True\n'
        f'relocatable = True\n'
        f'\n'
        f'def commands():\n'
        f'    env.PYTHONPATH.prepend("{{root}}/.{pkg_name}")\n',
        encoding="utf-8"
    )
    ok(f"  {pkg_name} 安装完成: {pkg_dir}")


def _install_github_package(pkg_name: str, meta: dict, pkg_dir: Path) -> None:
    """git clone 到 pkg_dir 并运行 init_bat。"""
    repo = meta.get("repo", f"Lugwit123/{pkg_name}")
    url = f"https://github.com/{repo}.git"
    result = subprocess.run(
        ["git", "clone", "--depth", "1", url, str(pkg_dir)],
        timeout=300
    )
    if result.returncode != 0:
        warn(f"  git clone {repo} 失败。")
        return
    init_bat = meta.get("init_bat")
    if init_bat:
        init_path = pkg_dir / init_bat
        if init_path.exists():
            subprocess.run(["cmd", "/c", str(init_path)], cwd=str(init_path.parent))
    ok(f"  {pkg_name} clone 完成: {pkg_dir}")


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

    # ── Step 5: 拉取 l_tray 包 ──
    if args.skip_packages:
        info("--skip-packages: 跳过 rez 包拉取。")
    else:
        step(5, TOTAL_STEPS, "拉取 l_tray 包（其余依赖由 wuwo.bat 启动时自动补全）")
        # 从 config.yaml 读取路径（空值时用默认）
        cfg_paths   = read_config_paths(wuwo_dir)
        rez_source  = cfg_paths["source"]
        rez_3rd     = cfg_paths["third_party"]
        rez_release = cfg_paths["release"]
        for d in (rez_source, rez_3rd, rez_release):
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                ok(f"创建目录: {d}")
            else:
                info(f"目录已存在: {d}")
        fetch_ltray_package(rez_source)
        # 注意：其余依赖包（lperforce/L_Tools/pyqt5/pywin32 等）
        # 由 wuwo.bat 在开启时通过 auto_fetch_packages.py --for-package l_tray 自动补全

    print("\n" + "=" * 60)
    print("  安装完成！")
    print("=" * 60)
    print(f"  Python : {python_exe}")
    print(f"  wuwo   : {wuwo_dir}")
    print(f"  配置   : {wuwo_dir / 'config.yaml'}")
    print()
    print("  启动托盘请运行:")
    print(f"    {wuwo_dir / 'wuwo.bat'} rez env l_tray -- python {{root}}/src/l_tray/plugSync.py")
    print("  或直接双击:")
    print(f"    {wuwo_dir / 'wuwo.bat'}")
    print("=" * 60)

    # 安装完成后提示启动
    wuwo_bat = wuwo_dir / "wuwo.bat"
    print()
    print("  启动托盘请在新窗口运行:")
    print(f"    {wuwo_bat}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
