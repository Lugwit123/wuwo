#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
wuwo One-Click Installer
========================
全流程自动化安装 wuwo 环境：
  1. 下载 Python 3.12.x 标准安装包（含 pip / 完整标准库）
  2. 静默安装到 wuwo/py_312/
  3. 安装依赖（rez / PyYAML / pywin32 / requests）
  4. 弹窗询问 rez 包路径，自动或手动更新 config.yaml
  5. 克隆 l_tray 与 Lugwit_PackageRegistry 到 rez-package-source；其余包在首次 ``wuwo.bat rez env ...`` 时按需拉取

用法（由 install.bat 调用）:
    python install.py [--wuwo-dir <path>]

参数:
    --wuwo-dir       wuwo 仓库目录（默认 = 本脚本所在目录）
    --skip-config    跳过 rez 路径配置弹窗（测试/CI 用）
    --skip-packages  跳过拉取 rez 包（测试/CI 用）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# ─────────────────────────────────────────────
#  常量配置
# ─────────────────────────────────────────────
PYTHON_FULL_VER = "3.12.10"
# 标准安装包（含 pip、完整标准库）
INSTALLER_NAME = f"python-{PYTHON_FULL_VER}-amd64.exe"
INSTALLER_URL  = f"https://www.python.org/ftp/python/{PYTHON_FULL_VER}/{INSTALLER_NAME}"
MIN_INSTALLER_BYTES = 20_000_000  # 标准安装包约 25 MB，小于 20 MB 视为损坏

# PySide6 / PyQt5 由各子包按需声明依赖，wuwo 核心只装最小集合
REQUIRED_PACKAGES = [
    ("rez",      "rez"),
    ("PyYAML",   "PyYAML"),
    ("pywin32",  "pywin32"),
    ("requests", "requests"),
    ("six",      "six"),
]

# pip 默认/回退源：默认优先阿里云，失败再回退其他源
DEFAULT_PIP_INDEX_URL = "https://mirrors.aliyun.com/pypi/simple"
PIP_INDEX_URLS = [
    "https://mirrors.aliyun.com/pypi/simple",
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://pypi.org/simple",
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


def _build_git_mirror_urls(url: str) -> list[str]:
    """给 GitHub URL 生成可重试镜像列表（首个为原始 URL）。"""
    out = [url]
    if url.startswith("https://github.com/"):
        out.append("https://ghproxy.com/" + url)
        out.append(url.replace("https://github.com/", "https://gitclone.com/github.com/"))
    # 去重保序
    seen = set()
    uniq = []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def _git_clone_with_mirrors(repo_url: str, dest: Path, timeout: int = 300) -> tuple[bool, str]:
    """按镜像列表重试 git clone。"""
    last_err = ""
    for url in _build_git_mirror_urls(repo_url):
        info(f"git clone 进度: {url}")
        result = subprocess.run(
            ["git", "clone", "--progress", "--depth", "1", url, str(dest)],
            timeout=timeout,
        )
        if result.returncode == 0:
            return True, f"clone 成功: {url}"
        last_err = f"exit {result.returncode}"
        warn(f"git clone 失败: {url} -> {last_err}")
    return False, f"git clone 全部镜像失败: {last_err}"


def _git_pull_with_mirrors(repo_dir: Path, repo_url: str) -> tuple[bool, str]:
    """强制同步：fetch + reset --hard + clean -fd，覆盖本地改动。"""
    branch = "main"
    b = subprocess.run(
        ["git", "-C", str(repo_dir), "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True,
        text=True,
    )
    if b.returncode == 0 and b.stdout.strip():
        branch = b.stdout.strip()
    else:
        warn("检测到 detached HEAD，按镜像 FETCH_HEAD 强制覆盖本地。")

    last_err = "unknown"
    for url in _build_git_mirror_urls(repo_url):
        info(f"git fetch 进度: {url}")
        if b.returncode == 0 and b.stdout.strip():
            fetch_cmd = ["git", "-C", str(repo_dir), "fetch", "--progress", url, branch]
        else:
            fetch_cmd = ["git", "-C", str(repo_dir), "fetch", "--progress", url]
        f = subprocess.run(fetch_cmd)
        if f.returncode != 0:
            last_err = f"fetch exit {f.returncode}"
            warn(f"git fetch 失败: {url} -> {last_err}")
            continue

        r = subprocess.run(["git", "-C", str(repo_dir), "reset", "--hard", "FETCH_HEAD"])
        if r.returncode != 0:
            last_err = f"reset exit {r.returncode}"
            warn(f"git reset 失败: {url} -> {last_err}")
            continue

        # 清理未跟踪文件，确保本地与远端一致
        c = subprocess.run(["git", "-C", str(repo_dir), "clean", "-fd"])
        if c.returncode != 0:
            last_err = f"clean exit {c.returncode}"
            warn(f"git clean 失败: {url} -> {last_err}")
            continue

        return True, f"镜像强制同步完成: {url}"

    return False, f"git 强制同步全部镜像失败: {last_err}"


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
    arg_list = list(args)
    has_index_opt = any(a in ("-i", "--index-url") for a in arg_list)
    if not has_index_opt:
        host = urllib.parse.urlparse(DEFAULT_PIP_INDEX_URL).hostname or ""
        arg_list += ["-i", DEFAULT_PIP_INDEX_URL, "--trusted-host", host]
    cmd = [str(python_exe), "-m", "pip"] + arg_list + ["--progress-bar", "on", "--no-warn-script-location"]
    return subprocess.run(cmd).returncode


def _run_pip_with_env(
    python_exe: Path,
    args: list[str],
    env: dict | None = None,
    isolated: bool = False,
) -> int:
    arg_list = list(args)
    has_index_opt = any(a in ("-i", "--index-url") for a in arg_list)
    if not has_index_opt:
        host = urllib.parse.urlparse(DEFAULT_PIP_INDEX_URL).hostname or ""
        arg_list += ["-i", DEFAULT_PIP_INDEX_URL, "--trusted-host", host]
    if isolated:
        # 忽略 pip 配置文件和环境变量，防止残留代理污染安装。
        arg_list = ["--isolated"] + arg_list
    cmd = [str(python_exe), "-m", "pip"] + arg_list + ["--progress-bar", "on", "--no-warn-script-location"]
    return subprocess.run(cmd, env=env).returncode


def _env_without_proxy() -> dict:
    env = dict(os.environ)
    for k in [
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
        "PIP_PROXY", "pip_proxy",
        "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL",
        "PIP_TRUSTED_HOST",
    ]:
        env.pop(k, None)
    return env


def _test_pip_index_url(index_url: str, timeout: int = 6, use_no_proxy: bool = False) -> tuple[bool, str]:
    """测试某个 pip 源是否可用。"""
    test_url = index_url.rstrip("/") + "/pip/"
    try:
        req = urllib.request.Request(
            test_url,
            headers={"User-Agent": "wuwo-installer/1.0"},
            method="GET",
        )
        opener = urllib.request.build_opener()
        if use_no_proxy:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            if int(code) < 500:
                return True, f"HTTP {code}"
            return False, f"HTTP {code}"
    except Exception as exc:
        return False, str(exc)


def select_best_pip_index_url() -> None:
    """运行时先探测可用 pip 源，并更新默认源。"""
    global DEFAULT_PIP_INDEX_URL
    info("探测可用 pip 源（默认优先阿里云）...")
    for index_url in PIP_INDEX_URLS:
        ok1, msg1 = _test_pip_index_url(index_url, use_no_proxy=False)
        if ok1:
            DEFAULT_PIP_INDEX_URL = index_url
            ok(f"选择 pip 源: {index_url} ({msg1})")
            return
        ok2, msg2 = _test_pip_index_url(index_url, use_no_proxy=True)
        if ok2:
            DEFAULT_PIP_INDEX_URL = index_url
            ok(f"选择 pip 源: {index_url} (no-proxy, {msg2})")
            return
        warn(f"pip 源不可用: {index_url} | env={msg1} | no-proxy={msg2}")
    warn(f"所有探测源都不可用，继续使用默认源: {DEFAULT_PIP_INDEX_URL}")


def run_pip_install_with_fallback(python_exe: Path, *install_args: str) -> int:
    """pip install 回退策略：默认 -> 无代理 -> 多镜像（无代理）。"""
    base_args = ["install"] + list(install_args)

    # 1) 默认环境（尊重用户现有 pip/代理设置）
    ret = _run_pip_with_env(python_exe, base_args)
    if ret == 0:
        return 0

    warn("pip install 失败，尝试禁用代理后重试...")
    no_proxy_env = _env_without_proxy()

    # 2) 去代理再试官方源（常见于错误代理配置）
    ret = _run_pip_with_env(python_exe, base_args, env=no_proxy_env, isolated=True)
    if ret == 0:
        return 0

    # 3) 镜像源回退（去代理）
    for index_url in PIP_INDEX_URLS:
        host = urllib.parse.urlparse(index_url).hostname or ""
        info(f"pip 回退源重试: {index_url}")
        mirror_args = base_args + ["-i", index_url, "--trusted-host", host]
        ret = _run_pip_with_env(python_exe, mirror_args, env=no_proxy_env, isolated=True)
        if ret == 0:
            ok(f"pip 回退成功: {index_url}")
            return 0

    return ret


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
    """静默安装 Python 到 python_dir，包含 pip。"""
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
    #   InstallAllUsers=0  仅当前用户（无需管理员）
    #   PrependPath=0   不修改系统 PATH
    cmd = [
        str(installer),
        "/quiet",
        f"TargetDir={python_dir}",
        "Include_pip=1",
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
        ret = run_pip_install_with_fallback(python_exe, pip_name)
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


def ensure_legacy_six_compat(python_exe: Path) -> None:
    """兼容旧代码硬编码 six.py 路径（Python27 site-packages）。"""
    legacy_six = Path(r"D:\TD_Depot\plug_in\Python\Python27\Lib\site-packages\six.py")
    if legacy_six.exists():
        info(f"兼容 six.py 已存在: {legacy_six}")
        return
    try:
        probe = subprocess.run(
            [str(python_exe), "-c", "import six,sys;print(six.__file__)"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if probe.returncode != 0 or not (probe.stdout or "").strip():
            warn("无法定位 six.py，跳过旧路径兼容。")
            return
        six_src = Path((probe.stdout or "").strip())
        if six_src.name.lower() != "six.py" or not six_src.exists():
            warn(f"six 源文件异常，跳过兼容: {six_src}")
            return
        legacy_six.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(six_src, legacy_six)
        ok(f"已创建 six 旧路径兼容文件: {legacy_six}")
    except Exception as exc:
        warn(f"创建 six 旧路径兼容文件失败: {exc}")


# ─────────────────────────────────────────────
#  Step 4: 弹窗询问 rez 包路径并更新 config.yaml
# ─────────────────────────────────────────────

def _ask_use_default_paths(build_path: Path, release_path: Path, third_party_path: Path) -> bool:
    """弹出对话框询问是否使用默认路径。优先 PowerShell，其次命令行。"""
    build_str         = str(build_path).replace("\\", "/")
    release_str       = str(release_path).replace("\\", "/")
    third_party_str   = str(third_party_path).replace("\\", "/")
    title = "wuwo Installer - Package Paths"
    # PowerShell：使用 WinForms 自定义窗口
    try:
        ps_title = json.dumps(title, ensure_ascii=False)
        ps_build = json.dumps(build_str, ensure_ascii=False)
        ps_release = json.dumps(release_str, ensure_ascii=False)
        ps_third = json.dumps(third_party_str, ensure_ascii=False)
        ps_cmd = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "Add-Type -AssemblyName System.Drawing; "
            f"$title = {ps_title}; "
            f"$build = {ps_build}; "
            f"$release = {ps_release}; "
            f"$third = {ps_third}; "
            "$form = New-Object System.Windows.Forms.Form; "
            "$form.Text = $title; "
            "$form.StartPosition = 'CenterScreen'; "
            "$form.Size = New-Object System.Drawing.Size(820, 380); "
            "$form.FormBorderStyle = 'FixedDialog'; "
            "$form.MaximizeBox = $false; "
            "$form.MinimizeBox = $false; "
            "$form.TopMost = $true; "
            "$font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9); "
            "$mono = New-Object System.Drawing.Font('Consolas', 9); "
            "$label1 = New-Object System.Windows.Forms.Label; "
            "$label1.Text = 'Use recommended default paths for rez packages?'; "
            "$label1.Location = New-Object System.Drawing.Point(20, 15); "
            "$label1.Size = New-Object System.Drawing.Size(760, 24); "
            "$label1.Font = $font; "
            "$form.Controls.Add($label1); "
            "$label2 = New-Object System.Windows.Forms.Label; "
            "$label2.Text = 'Selected paths:'; "
            "$label2.Location = New-Object System.Drawing.Point(20, 45); "
            "$label2.Size = New-Object System.Drawing.Size(760, 20); "
            "$label2.Font = $font; "
            "$form.Controls.Add($label2); "
            "$box = New-Object System.Windows.Forms.TextBox; "
            "$box.Multiline = $true; "
            "$box.ReadOnly = $true; "
            "$box.ScrollBars = 'Vertical'; "
            "$box.Font = $mono; "
            "$box.Location = New-Object System.Drawing.Point(20, 70); "
            "$box.Size = New-Object System.Drawing.Size(760, 210); "
            "$box.Text = ('build      : ' + $build + [Environment]::NewLine + "
            "             'release    : ' + $release + [Environment]::NewLine + "
            "             'third_party: ' + $third + [Environment]::NewLine + [Environment]::NewLine + "
            "             'Yes = auto update config.yaml' + [Environment]::NewLine + "
            "             'No  = open config.yaml for manual editing'); "
            "$form.Controls.Add($box); "
            "$btnYes = New-Object System.Windows.Forms.Button; "
            "$btnYes.Text = 'Use Defaults (Yes)'; "
            "$btnYes.Location = New-Object System.Drawing.Point(470, 295); "
            "$btnYes.Size = New-Object System.Drawing.Size(150, 34); "
            "$btnYes.Font = $font; "
            "$btnYes.Add_Click({ $form.Tag = 'YES'; $form.Close() }); "
            "$form.Controls.Add($btnYes); "
            "$btnNo = New-Object System.Windows.Forms.Button; "
            "$btnNo.Text = 'Edit Manually (No)'; "
            "$btnNo.Location = New-Object System.Drawing.Point(630, 295); "
            "$btnNo.Size = New-Object System.Drawing.Size(150, 34); "
            "$btnNo.Font = $font; "
            "$btnNo.Add_Click({ $form.Tag = 'NO'; $form.Close() }); "
            "$form.Controls.Add($btnNo); "
            "$form.AcceptButton = $btnYes; "
            "$form.CancelButton = $btnNo; "
            "$null = $form.ShowDialog(); "
            "if ($form.Tag -eq 'YES') { exit 0 } else { exit 1 }"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode in (0, 1):
            return result.returncode == 0
        warn("PowerShell 弹窗返回异常，使用命令行询问。")
    except Exception as exc:
        warn(f"PowerShell 弹窗失败: {exc}，使用命令行询问。")

    # 回退：命令行
    while True:
        choice = input("\n是否使用推荐默认路径？[Y/N]: ").strip().upper()
        if choice in ("Y", "YES"):
            return True
        if choice in ("N", "NO"):
            return False
        print("  请输入 Y 或 N。")


def _update_config_yaml(config_yaml: Path, build_path: Path, release_path: Path, third_party_path: Path) -> None:
    """用正则替换 config.yaml 中的 build/release/third_party 路径。"""
    build_str         = str(build_path).replace("\\", "/")
    release_str       = str(release_path).replace("\\", "/")
    third_party_str   = str(third_party_path).replace("\\", "/")

    content = config_yaml.read_text(encoding="utf-8")
    content = re.sub(
        r'(^\s+build:\s+")[^"]*(")' ,
        lambda m: m.group(1) + build_str + m.group(2),
        content, flags=re.MULTILINE,
    )
    content = re.sub(
        r'(^\s+release:\s+")[^"]*(")' ,
        lambda m: m.group(1) + release_str + m.group(2),
        content, flags=re.MULTILINE,
    )
    content = re.sub(
        r'(^\s+third_party:\s+")[^"]*(")' ,
        lambda m: m.group(1) + third_party_str + m.group(2),
        content, flags=re.MULTILINE,
    )
    config_yaml.write_text(content, encoding="utf-8")
    ok("config.yaml 已更新:")
    ok(f"  packages.build         = {build_str}")
    ok(f"  packages.release       = {release_str}")
    ok(f"  packages.third_party   = {third_party_str}")


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
    default_build         = parent / "rez-package-build"
    default_release       = parent / "rez-package-release"
    default_third_party   = parent / "rez-package-3rd"

    print("\n  推荐默认路径:")
    print(f"    packages.build         = {default_build}")
    print(f"    packages.release       = {default_release}")
    print(f"    packages.third_party   = {default_third_party}")

    if _ask_use_default_paths(default_build, default_release, default_third_party):
        info("使用默认路径，自动更新 config.yaml ...")
        _update_config_yaml(config_yaml, default_build, default_release, default_third_party)
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
    repo_url = "https://github.com/Lugwit123/l_tray.git"
    if pkg_dir.exists():
        # 已存在则 pull 最新
        info("l_tray 已存在，尝试 git pull ...")
        ok_pull, pull_msg = _git_pull_with_mirrors(pkg_dir, repo_url)
        if ok_pull:
            ok("l_tray git pull 完成。")
        else:
            warn(f"{pull_msg}（可能有本地改动），继续使用现有版本。")
        return

    info(f"克隆 l_tray → {pkg_dir}")
    info(f"  {repo_url}")
    ok_clone, clone_msg = _git_clone_with_mirrors(repo_url, pkg_dir, timeout=300)
    if not ok_clone:
        raise RuntimeError(f"git clone l_tray 失败，请检查网络或 GitHub 访问权限。\n  {clone_msg}")
    # 设置长路径支持
    subprocess.run(
        ["git", "config", "core.longpaths", "true"],
        cwd=str(pkg_dir), capture_output=True
    )
    ok(f"l_tray 克隆完成: {pkg_dir}")


def fetch_lugwit_package_registry(rez_source_dir: Path) -> None:
    """克隆或拉取 Lugwit_PackageRegistry（内含 999.0/package_registry.yaml，供 auto_fetch 使用）。"""
    pkg_dir = rez_source_dir / "Lugwit_PackageRegistry"
    reg_yaml = pkg_dir / "999.0" / "package_registry.yaml"
    repo_url = "https://github.com/Lugwit123/Lugwit_PackageRegistry.git"

    if (pkg_dir / ".git").is_dir():
        info("Lugwit_PackageRegistry 已存在，尝试 git pull --ff-only …")
        ok_pull, pull_msg = _git_pull_with_mirrors(pkg_dir, repo_url)
        if ok_pull:
            ok("Lugwit_PackageRegistry git pull 完成。")
        else:
            warn(f"{pull_msg}（可能有本地改动），继续使用现有版本。")
        return

    if reg_yaml.is_file():
        info("注册表 yaml 已存在（非 git 工作副本），跳过克隆。")
        return

    if pkg_dir.exists():
        raise RuntimeError(
            f"Lugwit_PackageRegistry 目录存在但不完整（缺少 {reg_yaml} 且无 .git）。\n"
            f"  请删除或修复后重试: {pkg_dir}"
        )

    info(f"克隆 Lugwit_PackageRegistry → {pkg_dir}")
    info(f"  {repo_url}")
    ok_clone, clone_msg = _git_clone_with_mirrors(repo_url, pkg_dir, timeout=300)
    if not ok_clone:
        raise RuntimeError(
            "git clone Lugwit_PackageRegistry 失败，请检查网络或 GitHub 访问权限。\n"
            "  仓库需存在: https://github.com/Lugwit123/Lugwit_PackageRegistry\n"
            f"  详情: {clone_msg}"
        )
    subprocess.run(
        ["git", "config", "core.longpaths", "true"],
        cwd=str(pkg_dir),
        capture_output=True,
    )
    ok(f"Lugwit_PackageRegistry 克隆完成: {pkg_dir}")
    if not reg_yaml.is_file():
        warn(f"克隆完成但未找到 {reg_yaml}，请确认远端仓库已包含注册表文件。")


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

    ret = run_pip_install_with_fallback(
        python_exe,
        pip_name,
        "--target", str(hidden_dir),
    )
    if ret != 0:
        warn(f"  {pkg_name} pip install 失败，可手动安装: pip install {pip_name}")
        return

    # 生成 rez package.py（pywin32：--target 时 .pth 不生效，须显式追加 win32/lib 等路径）
    next_minor = (
        f'{python_ver.rsplit(".", 1)[0]}.{int(python_ver.rsplit(".", 1)[-1]) + 1}'
        if "." in python_ver
        else python_ver
    )
    req_inner = f'"python-{python_ver}+<{next_minor}"'
    if pkg_name == "winshell":
        req_inner += ', "pywin32"'
    if pkg_name == "pywin32":
        py_cmds = (
            '    env.PYTHONPATH.append("{root}/.pywin32")\n'
            '    env.PYTHONPATH.append("{root}/.pywin32/win32")\n'
            '    env.PYTHONPATH.append("{root}/.pywin32/win32/lib")\n'
            '    env.PYTHONPATH.append("{root}/.pywin32/Pythonwin")\n'
        )
    else:
        py_cmds = f'    env.PYTHONPATH.prepend("{{root}}/.{pkg_name}")\n'

    package_py = pkg_dir / "package.py"
    package_py.write_text(
        f'# -*- coding: utf-8 -*-\n'
        f'name = "{pkg_name}"\n'
        f'version = "{rez_ver}"\n'
        f'description = "{meta.get("description", pkg_name)}"\n'
        f"requires = [{req_inner}]\n"
        f'build_command = False\n'
        f'cachable = True\n'
        f'relocatable = True\n'
        f'\n'
        f'def commands():\n'
        f"{py_cmds}",
        encoding="utf-8"
    )
    ok(f"  {pkg_name} 安装完成: {pkg_dir}")


def _install_github_package(pkg_name: str, meta: dict, pkg_dir: Path) -> None:
    """git clone 到 pkg_dir 并运行 init_bat。"""
    repo = meta.get("repo", f"Lugwit123/{pkg_name}")
    repo_url = f"https://github.com/{repo}.git"
    ok_clone, clone_msg = _git_clone_with_mirrors(repo_url, pkg_dir, timeout=300)
    if not ok_clone:
        warn(f"  git clone {repo} 失败。{clone_msg}")
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
    parser.add_argument(
        "--ensure-registry-package",
        action="store_true",
        help="仅克隆/拉取 Lugwit_PackageRegistry 并校验 package_registry.yaml 后退出",
    )
    args = parser.parse_args()

    wuwo_dir   = Path(args.wuwo_dir).resolve() if args.wuwo_dir else Path(__file__).resolve().parent
    python_dir = wuwo_dir / "py_312"
    python_exe = python_dir / "python.exe"

    print("=" * 60)
    print("  wuwo One-Click Installer")
    print(f"  wuwo 目录: {wuwo_dir}")
    print("=" * 60)

    if args.ensure_registry_package:
        cfg_paths = read_config_paths(wuwo_dir)
        rez_source = cfg_paths["source"]
        rez_source.mkdir(parents=True, exist_ok=True)
        fetch_lugwit_package_registry(rez_source)
        reg_yaml = rez_source / "Lugwit_PackageRegistry" / "999.0" / "package_registry.yaml"
        if not reg_yaml.is_file():
            raise RuntimeError(
                f"Lugwit_PackageRegistry 已拉取但缺少注册表文件:\n  {reg_yaml}"
            )
        ok(f"注册表就绪: {reg_yaml}")
        return 0

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
    select_best_pip_index_url()
    install_packages(python_exe)
    ensure_legacy_six_compat(python_exe)

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
        step(5, TOTAL_STEPS, "拉取 l_tray 与 Lugwit_PackageRegistry（其余依赖由 wuwo.bat rez env 按需补全）")
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
        fetch_lugwit_package_registry(rez_source)
        reg_yaml = rez_source / "Lugwit_PackageRegistry" / "999.0" / "package_registry.yaml"
        if not reg_yaml.is_file():
            raise RuntimeError(
                f"缺少 Rez 包注册表，wuwo 无法解析依赖。请确认远端已推送该文件:\n  {reg_yaml}"
            )
        ok(f"package_registry.yaml 就绪: {reg_yaml}")
        # 其余依赖包由 wuwo.bat 在 ``rez env ...`` 时通过
        # auto_fetch_packages.py --for-rez-env 按需克隆 / 安装（无启动全量扫描）

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
