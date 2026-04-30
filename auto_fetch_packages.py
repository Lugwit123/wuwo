#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
auto_fetch_packages.py
自动检测并从 GitHub 下载缺失的 rez 包到 rez-package-source 目录

用法:
    python auto_fetch_packages.py                       # 检查并下载全部注册包
    python auto_fetch_packages.py --check-only          # 仅检查，不下载
    python auto_fetch_packages.py --package l_tray      # 仅处理指定包
    python auto_fetch_packages.py --for-package l_tray  # 读取 l_tray requires，只下载其依赖中注册的缺失包
"""

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

GITHUB_OWNER = "Lugwit123"
GITHUB_BASE_URL = f"https://github.com/{GITHUB_OWNER}"

# pip 镜像列表：依次尝试，任意一个成功即可
PIP_INDEX_URLS = [
    "https://pypi.mirrors.ustc.edu.cn/simple/",   # 中科大（首选）
    "https://mirrors.aliyun.com/pypi/simple/",     # 阿里云
    "https://pypi.org/simple",                     # 官方
]

# 一方包：从 Lugwit123 GitHub 克隆安装
# repo: GitHub 仓库名（与包名同名）
# init_bat: clone 后需要运行的初始化脚本（相对于包目录），None 表示无需初始化
_GITHUB_PACKAGES: Dict[str, Any] = {
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
    "pytracemp": {"repo": "pytracemp", "init_bat": None},
    "start_multi_app": {"repo": "start_multi_app", "init_bat": None},
    "view_pkl_tool": {"repo": "view_pkl_tool", "init_bat": None},
}

# 第三方包：通过 pip 安装，自动生成 rez 包装到 rez-package-3rd
# pip_name: pip 包名（可含版本约束，如 PyQt5==5.15.11）
# python_ver: 适配的 Python 版本
_PIP_PACKAGES: Dict[str, Any] = {
    "psutil":   {"pip_name": "psutil",          "python_ver": "3.12"},
    "pyqt5":    {"pip_name": "PyQt5==5.15.11",  "python_ver": "3.12"},
    "pyside6":  {"pip_name": "PySide6==6.7.0",  "python_ver": "3.12"},
    "pywin32":  {"pip_name": "pywin32",          "python_ver": "3.12"},
    "pyyaml":   {"pip_name": "PyYAML",           "python_ver": "3.12"},
    "watchdog": {"pip_name": "watchdog",         "python_ver": "3.12"},
}

# nuget 包：下载全量绿色 Python 包到 rez-package-3rd（优先复用已有 wuwo/py_312，避免重复下载）
_NUGET_PACKAGES: Dict[str, Any] = {
    "python": {
        "nuget_name": "python",
        "nuget_ver": "3.12.10",
        "rez_ver": "3.12.10",
        "description": "Python 3.12.10 portable (green, no system install)",
    },
}

# 合并为统一注册表（下游代码不需要改动）
PACKAGE_REGISTRY: Dict[str, Any] = {**_GITHUB_PACKAGES, **_PIP_PACKAGES, **_NUGET_PACKAGES}


def _show_error_popup(title: str, message: str) -> None:
    """在 Windows 上弹出错误对话框（MB_ICONERROR）。非 Windows 或无 GUI 时静默。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # 0x10 = MB_ICONERROR
    except Exception:
        pass


def is_pypi_package(name: str, timeout: int = 5) -> bool:
    """查询 PyPI 判断包名是否存在于公共索引上。"""
    url = f"https://pypi.org/pypi/{name}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except Exception:
        return False


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
        has_package_py = bool(list(pkg_dir.glob("*/package.py"))) if pkg_dir.is_dir() else False
        if has_package_py:
            existing.append(pkg_name)
        else:
            # 目录存在但无有效版本时，视为缺失（会触发重新 clone）
            missing.append(pkg_name)

    return existing, missing


def _safe_rmtree(path: Path) -> None:
    """尽量删除目录（处理 Windows 只读文件导致的删除失败）。"""
    if not path.exists():
        return

    def _onerror(func, p, exc_info):
        try:
            os.chmod(p, 0o777)
            func(p)
        except Exception:
            pass

    shutil.rmtree(path, onerror=_onerror)


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

        return True, "克隆完成 OK"

    except subprocess.TimeoutExpired:
        # 超时后清理不完整的目录
        if dest.exists():
            _safe_rmtree(dest)
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
        return True, "init 脚本执行完成 OK"

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
        status = "[OK]" if exists else "[MISS]"
        state = "已存在" if exists else "缺失"
        print(f"  {status} {name:<{max_name_len}}  {state}")

    print()


def get_requires_for_package(pkg_name: str, source_dir: Path) -> List[str]:
    """从 rez-package-source/<pkg_name>/*/package.py 读取 requires 列表。

    返回包名列表（去除版本约束，如 'python-3.12+<3.13' 取 'python'）。
    """
    import re
    pkg_files = list((source_dir / pkg_name).glob("*/package.py"))
    if not pkg_files:
        print(f"[WARN] {pkg_name}/package.py 未找到，无法读取 requires", file=sys.stderr)
        return []
    content = pkg_files[0].read_text(encoding="utf-8")
    m = re.search(r'requires\s*=\s*\[([^\]]+)\]', content, re.S)
    if not m:
        return []
    raw = m.group(1)
    # 提取包名（去除 -version 约束，只保留名称部分）
    names = re.findall(r'["\']([\w]+)', raw)
    return names


def collect_transitive_pip_deps(start_requires: List[str], source_dir: Path) -> List[str]:
    """从 start_requires 出发递归收集所有传递性 pip 包依赖。

    对每个 GitHub 包，继续读取其 requires 并递归处理，
    直到没有新包为止。pip 包自身不再继续展开。
    """
    pip_deps: List[str] = []
    visited: set[str] = set()
    queue: List[str] = list(start_requires)

    while queue:
        pkg = queue.pop(0)
        if pkg in visited:
            continue
        visited.add(pkg)

        if pkg in _PIP_PACKAGES:
            pip_deps.append(pkg)
        elif pkg in _GITHUB_PACKAGES:
            sub = get_requires_for_package(pkg, source_dir)
            for r in sub:
                if r not in visited:
                    queue.append(r)

    return pip_deps


def check_python_executable() -> Optional[Path]:
    """查找当前 Python 可执行文件路径。"""
    try:
        import sys
        return Path(sys.executable)
    except Exception:
        return None


def install_pip_package_to_3rd(pkg_name: str, meta: dict, third_party_dir: Path) -> Tuple[bool, str]:
    """通过 pip install 安装第三方包到 rez-package-3rd 目录。

    Args:
        pkg_name: 包名
        meta: 包元数据（包含 pip_name、python_ver 等）
        third_party_dir: rez-package-3rd 目录

    Returns:
        (success, message)
    """
    pip_name = meta.get("pip_name", pkg_name)
    python_ver = meta.get("python_ver", "3.12")
    rez_ver = meta.get("rez_ver", f"999.0-py{python_ver}")

    pkg_dir = third_party_dir / pkg_name / rez_ver
    hidden_dir = pkg_dir / f".{pkg_name}"

    # 已存在则跳过
    if (pkg_dir / "package.py").exists():
        return True, f"已存在: {pkg_dir}"

    # pip install
    python_exe = check_python_executable()
    if not python_exe:
        return False, "找不到 Python 可执行文件"

    print(f"      pip install {pip_name} → {hidden_dir}")
    last_err = ""
    mirror_labels = ["中科大", "阿里云", "PyPI 官方"]
    for idx_url, label in zip(PIP_INDEX_URLS, mirror_labels):
        try:
            result = subprocess.run(
                [str(python_exe), "-m", "pip", "install", pip_name,
                 "--target", str(hidden_dir),
                 "-i", idx_url,
                 "--no-warn-script-location", "--quiet"],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                print(f"      [{label} 成功]")
                break
            last_err = result.stderr.strip()
            print(f"      [{label} 失败] {last_err[:120]}")
        except subprocess.TimeoutExpired:
            last_err = f"{label} pip install 超时（300s）"
            print(f"      [{label} 超时]")
        except Exception as e:
            last_err = f"{label} pip install 异常: {e}"
            print(f"      [{label} 异常] {e}")
    else:
        return False, f"pip install 失败 (全部 {len(PIP_INDEX_URLS)} 个镜像失败): {last_err}"

    # 生成 rez package.py
    pkg_dir.mkdir(parents=True, exist_ok=True)
    package_py = pkg_dir / "package.py"
    next_ver = f"{python_ver.rsplit('.', 1)[0]}.{int(python_ver.rsplit('.', 1)[-1]) + 1}"
    package_py.write_text(
        f'# -*- coding: utf-8 -*-\n'
        f'name = "{pkg_name}"\n'
        f'version = "{rez_ver}"\n'
        f'description = "{meta.get("description", pkg_name)}"\n'
        f'requires = ["python-{python_ver}+<{next_ver}"]\n'
        f'build_command = False\n'
        f'cachable = True\n'
        f'relocatable = True\n'
        f'\n'
        f'def commands():\n'
        f'    env.PYTHONPATH.append("{{root}}/.{pkg_name}")\n',
        encoding="utf-8"
    )

    return True, f"安装完成: {pkg_dir}"


def _write_python_rez_wrapper(pkg_dir: Path, python_root: Path, rez_ver: str) -> Tuple[bool, str]:
    """用现有 Python 安装目录生成 rez package.py（不重复下载）。"""
    root_str     = str(python_root).replace("\\", "/")
    scripts_str  = str(python_root / "Scripts").replace("\\", "/")
    lib_str      = str(python_root / "Lib").replace("\\", "/")
    site_str     = str(python_root / "Lib" / "site-packages").replace("\\", "/")
    (pkg_dir / "package.py").write_text(
        f'# -*- coding: utf-8 -*-\n'
        f'name = "python"\n'
        f'version = "{rez_ver}"\n'
        f'description = "Python {rez_ver} (wuwo py_312, no system install)"\n'
        f'build_command = False\n'
        f'cachable = False\n'
        f'relocatable = False\n'
        f'\n'
        f'def commands():\n'
        f'    env.PATH.prepend("{root_str}")\n'
        f'    env.PATH.prepend("{scripts_str}")\n'
        f'    env.PYTHONPATH.prepend("{lib_str}")\n'
        f'    env.PYTHONPATH.prepend("{site_str}")\n'
        f'    alias("python", "{root_str}/python.exe")\n'
        f'    alias("python3", "{root_str}/python.exe")\n'
        f'    alias("pip", "{scripts_str}/pip.exe")\n',
        encoding="utf-8",
    )
    return True, f"python rez 包装创建完成 (指向 {python_root})"


def _download_nuget_python(pkg_name: str, meta: dict, pkg_dir: Path, third_party_dir: Path) -> Tuple[bool, str]:
    """从 nuget 下载 Python 全量包并解压到 pkg_dir。"""
    import zipfile
    nuget_name = meta.get("nuget_name", pkg_name)
    nuget_ver  = meta.get("nuget_ver", "3.12.10")
    rez_ver    = meta.get("rez_ver", nuget_ver)
    url        = f"https://www.nuget.org/api/v2/package/{nuget_name}/{nuget_ver}"
    nupkg_file = third_party_dir / f"{nuget_name}.{nuget_ver}.nupkg"
    extract_tmp = third_party_dir / f".{nuget_name}_tmp"

    print(f"      从 nuget 下载 Python {nuget_ver} ...")
    print(f"      URL: {url}")
    try:
        urllib.request.urlretrieve(url, str(nupkg_file))
    except Exception as e:
        return False, f"下载失败: {e}"

    sz = nupkg_file.stat().st_size if nupkg_file.exists() else 0
    if sz < 5_000_000:
        nupkg_file.unlink(missing_ok=True)
        return False, f"下载文件过小 ({sz} bytes)，可能损坏"

    try:
        if extract_tmp.exists():
            shutil.rmtree(extract_tmp)
        extract_tmp.mkdir(parents=True)
        with zipfile.ZipFile(str(nupkg_file), "r") as zf:
            zf.extractall(str(extract_tmp))
    except Exception as e:
        nupkg_file.unlink(missing_ok=True)
        return False, f"解压失败: {e}"
    finally:
        if nupkg_file.exists():
            nupkg_file.unlink(missing_ok=True)

    tools_dir = extract_tmp / "tools"
    src_dir = tools_dir if (tools_dir / "python.exe").exists() else (
        extract_tmp if (extract_tmp / "python.exe").exists() else None
    )
    if src_dir is None:
        shutil.rmtree(extract_tmp, ignore_errors=True)
        return False, "nuget 包结构异常：python.exe 未找到"

    for item in src_dir.iterdir():
        dst = pkg_dir / item.name
        if dst.exists():
            shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
        shutil.move(str(item), str(dst))
    shutil.rmtree(extract_tmp, ignore_errors=True)

    if not (pkg_dir / "python.exe").exists():
        return False, "解压后未找到 python.exe"

    # 生成 rez package.py（使用 {root} 相对路径，可重定位）
    (pkg_dir / "package.py").write_text(
        f'# -*- coding: utf-8 -*-\n'
        f'name = "python"\n'
        f'version = "{rez_ver}"\n'
        f'description = "{meta.get("description", "Python " + rez_ver)}"\n'
        f'build_command = False\n'
        f'cachable = True\n'
        f'relocatable = True\n'
        f'\n'
        f'def commands():\n'
        f'    env.PATH.prepend("{{root}}")\n'
        f'    env.PATH.prepend("{{root}}/Scripts")\n'
        f'    env.PYTHONPATH.prepend("{{root}}/Lib")\n'
        f'    env.PYTHONPATH.prepend("{{root}}/Lib/site-packages")\n'
        f'    alias("python", "{{root}}/python.exe")\n'
        f'    alias("python3", "{{root}}/python.exe")\n'
        f'    alias("pip", "{{root}}/Scripts/pip.exe")\n',
        encoding="utf-8",
    )
    return True, f"python 安装完成 (nuget): {pkg_dir}"


def install_nuget_package_to_3rd(pkg_name: str, meta: dict, third_party_dir: Path) -> Tuple[bool, str]:
    """安装 nuget 包（如 python）到 rez-package-3rd。

    优先复用 wuwo/py_312（只写 package.py wrapper），不存在时才下载 nuget 包。
    """
    rez_ver = meta.get("rez_ver", "3.12.10")
    pkg_dir = third_party_dir / pkg_name / rez_ver

    if (pkg_dir / "package.py").exists():
        return True, f"已存在: {pkg_dir}"

    pkg_dir.mkdir(parents=True, exist_ok=True)

    wuwo_dir = Path(__file__).resolve().parent
    py312_exe = wuwo_dir / "py_312" / "python.exe"
    if py312_exe.exists():
        return _write_python_rez_wrapper(pkg_dir, py312_exe.parent, rez_ver)

    return _download_nuget_python(pkg_name, meta, pkg_dir, third_party_dir)


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
    parser.add_argument(
        "--for-package",
        metavar="NAME",
        help="读取该包的 requires，只下载其依赖中在 REGISTRY 里注册的缺失包",
    )
    parser.add_argument(
        "--for-rez-env",
        metavar="REZ_ENV_ARGS",
        help="解析 'rez env' 参数字符串，自动安装所有传递性 pip 包依赖（由 wuwo.bat 调用）",
    )

    args = parser.parse_args()

    # --for-rez-env 模式：解析 rez env 参数字符串，提取包名并安装其传递性 pip 依赖
    if args.for_rez_env:
        source_dir = find_rez_package_source(args.source_dir)
        # 取 '--' 之前的部分，去除版本约束（如 python-3.12 → python）
        raw_args = args.for_rez_env.split("--")[0]
        tokens = raw_args.split()
        pkg_names = [t.split("-")[0] for t in tokens if not t.startswith("-")]
        # 只处理注册表里有的包
        known = [p for p in pkg_names if p in _GITHUB_PACKAGES]
        if not known:
            print("[for-rez-env] 未发现注册表内的 GitHub 包，跳过")
            return 0
        print(f"[for-rez-env] 检测到包: {known}，递归收集 pip 依赖...")
        pip_deps: List[str] = collect_transitive_pip_deps(known, source_dir)
        if not pip_deps:
            print("[for-rez-env] 无需安装额外 pip 包")
            return 0
        print(f"[for-rez-env] 将安装 pip 包: {pip_deps}")
        third_party_dir = source_dir.parent / "rez-package-3rd"
        third_party_dir.mkdir(parents=True, exist_ok=True)
        fail = 0
        for pkg in pip_deps:
            meta = PACKAGE_REGISTRY[pkg]
            ok, msg = install_pip_package_to_3rd(pkg, meta, third_party_dir)
            print(f"  [{'OK' if ok else 'FAIL'}] {pkg}: {msg}")
            if not ok:
                fail += 1
        return 1 if fail else 0

    # --for-package / 全量模式：确定 rez-package-source 路径
    source_dir = find_rez_package_source(args.source_dir)
    if not source_dir.exists():
        print(f"[信息] rez-package-source 目录不存在，自动创建: {source_dir}")
        source_dir.mkdir(parents=True, exist_ok=True)

    print(f"[信息] rez-package-source: {source_dir}")

    # --for-package 模式：读取目标包 requires，只处理其在 REGISTRY 中的依赖
    if args.for_package:
        # 若目标包在 _GITHUB_PACKAGES 但本地不存在，先克隆它再读 requires
        if args.for_package in _GITHUB_PACKAGES:
            pkg_dir = source_dir / args.for_package
            pkg_files = list(pkg_dir.glob("*/package.py")) if pkg_dir.exists() else []
            if (not pkg_dir.exists()) or (not pkg_files):
                if pkg_dir.exists() and not pkg_files:
                    print(f"[信息] {args.for_package} 目录存在但缺少 package.py，先清理后重克隆...")
                    try:
                        _safe_rmtree(pkg_dir)
                    except Exception as e:
                        print(f"[WARN] 清理损坏目录失败: {e}")
                else:
                    print(f"[信息] {args.for_package} 不在 rez-package-source，先克隆...")
                if _check_git_available():
                    _info = _GITHUB_PACKAGES[args.for_package]
                    _ok, _msg = clone_package(args.for_package, _info["repo"], source_dir)
                    print(f"  [{'OK' if _ok else 'WARN'}] {_msg}")
                else:
                    print("[WARN] git 不可用，无法克隆目标包")

        requires = get_requires_for_package(args.for_package, source_dir)
        if not requires:
            # 诊断根本原因
            pkg_dir = source_dir / args.for_package
            if not pkg_dir.exists():
                reason = (
                    f"目录不存在: {pkg_dir}\n"
                    f"git clone 失败或 rez-package-source 路径配置有误。"
                )
            else:
                pkg_files = list(pkg_dir.glob("*/package.py"))
                if not pkg_files:
                    reason = (
                        f"未找到 {args.for_package}/*/package.py\n"
                        f"目录存在但没有版本子目录或 package.py。"
                    )
                else:
                    reason = (
                        f"{pkg_files[0]} 中 requires 为空或解析失败。\n"
                        f"请检查 package.py 的 requires 列表是否正确。"
                    )
            err_msg = (
                f"[错误] 无法读取 {args.for_package} 的 requires\n\n"
                f"原因: {reason}\n\n"
                f"pip / nuget 包安装已跳过，托盘启动可能失败。\n"
                f"请修复上述问题后重新运行 install.bat。"
            )
            print(err_msg, file=sys.stderr)
            _show_error_popup(f"wuwo: {args.for_package} 依赖读取失败", err_msg)
            args.pip_packages = []
            args.nuget_packages = []
        else:
            # 区分 GitHub 包、pip 包和未在注册表中的依赖
            github_deps = [r for r in requires if r in _GITHUB_PACKAGES]
            # 只取直接 requires 里的 pip 包，不递归进子包
            # （子包的 pip 依赖由 --for-rez-env 在各自的 rez env 调用时处理）
            pip_deps    = [r for r in requires if r in _PIP_PACKAGES]
            nuget_deps  = [r for r in requires if r in _NUGET_PACKAGES]
            not_in_registry = [r for r in requires if r not in PACKAGE_REGISTRY]

            # 对于未注册的依赖：自动查询 PyPI，如果存在就动态加入 pip_deps
            if not_in_registry:
                print(f"[信息] 以下依赖不在注册表中，查询 PyPI…: {not_in_registry}")
                for r in not_in_registry:
                    if is_pypi_package(r):
                        print(f"        [OK] {r} 在 PyPI 上存在，加入 pip 安装列表")
                        pip_deps.append(r)
                        # 动态加入注册表（仅当前运行有效）
                        PACKAGE_REGISTRY[r] = {"pip_name": r, "python_ver": "3.12"}
                    else:
                        print(f"        [WARN] {r} 在 PyPI 上未找到，跳过")

            if github_deps:
                print(f"[信息] 将检查 GitHub 包: {github_deps}")
            if pip_deps:
                print(f"[信息] 将检查 pip 包: {pip_deps}")
            if nuget_deps:
                print(f"[信息] 将检查 nuget 包 (如 python): {nuget_deps}")

            # 对于 --for-package，分别处理各类型的包
            args.packages = github_deps or None
            args.pip_packages = pip_deps
            args.nuget_packages = nuget_deps

    # 将 --package 指定的包按类型拆分（非 --for-package 模式）
    if not args.for_package and args.packages:
        extra_pip: list[str] = []
        github_only: list[str] = []
        for p in args.packages:
            if p in _PIP_PACKAGES:
                extra_pip.append(p)
            else:
                github_only.append(p)
        args.packages = github_only or None
        # 合并到 pip_packages（可能已由 --for-package 设置）
        existing_pip: List[str] = getattr(args, "pip_packages", None) or []
        args.pip_packages = existing_pip + extra_pip

    # 扫描包状态（仅 GitHub 包）
    # 全量模式下只扫描 GitHub 包，pip 包不在 rez-package-source 里不应被当作缺失 GitHub 包
    github_to_scan = args.packages if args.packages else list(_GITHUB_PACKAGES.keys())
    existing, missing = check_missing_packages(source_dir, github_to_scan)

    # 全量模式下同步收集所有 pip 包以便后续安装
    if not args.for_package and not args.packages:
        base_pip: List[str] = getattr(args, "pip_packages", None) or []
        args.pip_packages = base_pip + list(_PIP_PACKAGES.keys())

    # --force 模式：将已存在的包也视为需要处理
    if args.force and existing:
        force_targets = list(existing)
        missing = sorted(set(missing + force_targets))
        existing = [e for e in existing if e not in force_targets]

    # 打印状态
    print_status_table(existing, missing)

    if not missing:
        print("[完成] 所有 GitHub 包已就绪，无需下载")
    else:
        if args.check_only:
            print(f"[信息] 共 {len(missing)} 个 GitHub 包缺失（--check-only 模式，不下载）")
        else:
            # 检查 git
            if not _check_git_available():
                print("[错误] git 命令不可用，请确保 git 已安装并在 PATH 中", file=sys.stderr)
                return 1

            # 下载缺失包
            print(f"\n[下载] 开始下载 {len(missing)} 个缺失 GitHub 包...\n")

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
                    print("      (--force) 删除已有目录...")
                    try:
                        _safe_rmtree(pkg_dir)
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
                print(f"[完成] 全部 {success_count} 个 GitHub 包下载成功")
            else:
                print(f"[完成] {success_count} 个成功, {fail_count} 个失败")

            if init_fail_count > 0:
                print(f"[警告] {init_fail_count} 个 init 脚本执行失败（不影响包可用性）")

    # 处理 pip 包（--for-package 模式下）
    pip_packages = getattr(args, 'pip_packages', None) or []
    if pip_packages:
        # 计算 third_party_dir
        third_party_dir = source_dir.parent / "rez-package-3rd"
        if not third_party_dir.exists():
            print(f"\n[信息] 创建 rez-package-3rd 目录: {third_party_dir}")
            third_party_dir.mkdir(parents=True, exist_ok=True)

        print("\n[检查] pip 第三方包...")
        pip_success = 0
        pip_fail = 0

        for pkg_name in pip_packages:
            meta = PACKAGE_REGISTRY[pkg_name]
            print(f"  [{pkg_name}]")
            ok, msg = install_pip_package_to_3rd(pkg_name, meta, third_party_dir)
            if ok:
                print(f"  [OK] {msg}")
                pip_success += 1
            else:
                print(f"  [FAIL] {msg}")
                pip_fail += 1

        print(f"\n[pip] {pip_success} 个成功, {pip_fail} 个失败")

    # 处理 nuget 包（如 python）
    nuget_packages = getattr(args, "nuget_packages", None) or []
    if nuget_packages:
        third_party_dir = source_dir.parent / "rez-package-3rd"
        if not third_party_dir.exists():
            print(f"\n[信息] 创建 rez-package-3rd 目录: {third_party_dir}")
            third_party_dir.mkdir(parents=True, exist_ok=True)

        print("\n[检查] nuget 包 (如 python)...")
        nuget_success = 0
        nuget_fail = 0

        for pkg_name in nuget_packages:
            meta = PACKAGE_REGISTRY[pkg_name]
            print(f"  [{pkg_name}]")
            ok, msg = install_nuget_package_to_3rd(pkg_name, meta, third_party_dir)
            if ok:
                print(f"  [OK] {msg}")
                nuget_success += 1
            else:
                print(f"  [FAIL] {msg}")
                nuget_fail += 1

        if nuget_fail:
            print(f"\n[nuget] {nuget_success} 个成功, {nuget_fail} 个失败")
            return 1
        print(f"\n[nuget] {nuget_success} 个成功")

    return 0


if __name__ == "__main__":
    sys.exit(main())
