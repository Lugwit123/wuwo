#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
auto_fetch_packages.py
自动检测并从 GitHub 下载缺失的 rez 包到 rez-package-source 目录

用法:
    python auto_fetch_packages.py                       # 手动：检查并下载全部注册表包（非 wuwo 默认行为）
    python auto_fetch_packages.py --check-only          # 仅检查，不下载
    python auto_fetch_packages.py --package l_tray      # 仅处理指定包
    python auto_fetch_packages.py --for-package l_tray  # 读取 l_tray requires，只下载其依赖中注册的缺失包
    python auto_fetch_packages.py --for-rez-env "rez env l_tray -- ..."  # wuwo.bat rez env 前：解析包名（不含 rez/env 子命令）
"""

import argparse
import ast
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

GITHUB_OWNER = "Lugwit123"
GITHUB_BASE_URL = f"https://github.com/{GITHUB_OWNER}"

# 由 load_live_registry() 从 rez-package-source/Lugwit_PackageRegistry/999.0/package_registry.yaml 填充（无内置回退）
_REGISTRY_GITHUB_OWNER = GITHUB_OWNER
_GITHUB_PACKAGES: Dict[str, Any] = {}
_PIP_PACKAGES: Dict[str, Any] = {}
_NUGET_PACKAGES: Dict[str, Any] = {}
PACKAGE_REGISTRY: Dict[str, Any] = {}

# pip 镜像列表：依次尝试，任意一个成功即可
PIP_INDEX_URLS = [
    "https://pypi.mirrors.ustc.edu.cn/simple/",   # 中科大（首选）
    "https://mirrors.aliyun.com/pypi/simple/",     # 阿里云
    "https://pypi.org/simple",                     # 官方
]

# pip 包装成 rez 时追加的 requires（隐式 pip 依赖，保证解析顺序）
_PIP_REZ_EXTRA_REQUIRES: Dict[str, List[str]] = {
    "winshell": ["pywin32"],
}


def _pip_rez_requires_literal(pkg_name: str, python_ver: str) -> str:
    nxt = (
        f'{python_ver.rsplit(".", 1)[0]}.{int(python_ver.rsplit(".", 1)[-1]) + 1}'
        if "." in python_ver
        else python_ver
    )
    parts: List[str] = [f"python-{python_ver}+<{nxt}"] + _PIP_REZ_EXTRA_REQUIRES.get(pkg_name, [])
    return "[" + ", ".join(f'"{p}"' for p in parts) + "]"


def _pip_rez_pythonpath_commands(pkg_name: str) -> str:
    """pywin32 用 ``pip install --target`` 时目录内 .pth 不会被加载，须显式加入 win32/lib 等路径。"""
    if pkg_name == "pywin32":
        h = pkg_name
        return (
            f'    env.PYTHONPATH.append("{{root}}/.{h}")\n'
            f'    env.PYTHONPATH.append("{{root}}/.{h}/win32")\n'
            f'    env.PYTHONPATH.append("{{root}}/.{h}/win32/lib")\n'
            f'    env.PYTHONPATH.append("{{root}}/.{h}/Pythonwin")\n'
        )
    return f'    env.PYTHONPATH.append("{{root}}/.{pkg_name}")\n'


# rez 子命令短名（小写）：不得当作包名，但若与 package_registry 中家族名冲突则保留为包（如 python）。
_REZ_SUBCOMMAND_ROOTS: frozenset = frozenset(
    {
        "env",
        "bind",
        "context",
        "contexts",
        "forward",
        "implicit",
        "view",
        "gui",
        "prompt",
        "suite",
        "plugins",
        "config",
        "complete",
        "version",
        "help",
        "selftest",
        "memcache",
        "depends",
        "cache",
        "pkg-cache",
    }
)

# rez env 常见「选项 + 一个参数」
_REZ_ENV_ONE_ARG_OPTS: frozenset = frozenset(
    {
        "-i",
        "--interpret",
        "-t",
        "--time",
        "--title",
    }
)


def _skip_rez_cli_flag_tokens(tokens: List[str], i: int, n: int) -> int:
    while i < n:
        tok = tokens[i]
        if not tok.startswith("-"):
            break
        low = tok.lower()
        if low in _REZ_ENV_ONE_ARG_OPTS and i + 1 < n and not tokens[i + 1].startswith("-"):
            i += 2
            continue
        i += 1
    return i


def parse_rez_env_root_packages(tokens: List[str], registry: Dict[str, Any]) -> List[str]:
    """从 ``rez [flags] env|… [flags] PKG …`` 或 ``PKG …`` 得到 Rez 包家族短名；去掉 rez、子命令与 CLI 选项。

    若某子命令名同时出现在 registry 中（如 python），则不作为子命令剥掉。
    """
    tl = [x for x in tokens if x]
    n = len(tl)
    reg_roots = {str(k).split("-")[0].lower() for k in registry.keys()}
    i = 0
    if i < n and tl[i].lower() == "rez":
        i += 1
    i = _skip_rez_cli_flag_tokens(tl, i, n)
    if i < n:
        root = tl[i].split("-")[0].lower()
        if root in _REZ_SUBCOMMAND_ROOTS and root not in reg_roots:
            i += 1
    i = _skip_rez_cli_flag_tokens(tl, i, n)
    rest = tl[i:]
    out: List[str] = []
    for t in rest:
        if not t or t.startswith("-") or t.startswith("."):
            continue
        root = t.split("-")[0].lower()
        if not root:
            continue
        if root in _REZ_SUBCOMMAND_ROOTS and root not in reg_roots:
            continue
        out.append(root)
    return out


def has_update_ephemeral(tokens: List[str]) -> bool:
    """检测是否包含 '.updata' / '.update' 临时请求。"""
    eph = {t.strip().lower() for t in tokens if t.startswith(".")}
    return (".updata" in eph) or (".update" in eph)


def registry_yaml_path(source_dir: Path) -> Path:
    """唯一注册表路径（固定 999.0）。"""
    return source_dir / "Lugwit_PackageRegistry" / "999.0" / "package_registry.yaml"


def load_live_registry(source_dir: Path) -> None:
    """从 package_registry.yaml 填充 _GITHUB_PACKAGES / _PIP_PACKAGES / _NUGET_PACKAGES / PACKAGE_REGISTRY。缺失或非法则退出进程。"""
    global _REGISTRY_GITHUB_OWNER, PACKAGE_REGISTRY
    yaml_path = registry_yaml_path(source_dir)
    if not yaml_path.is_file():
        print(
            "[错误] 缺少注册表（请先运行 install 克隆 Lugwit_PackageRegistry 或放置 yaml）:\n"
            f"  {yaml_path}",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        import yaml
    except ImportError:
        print("[错误] 需要 PyYAML: pip install PyYAML", file=sys.stderr)
        sys.exit(2)
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"[错误] 无法解析注册表 YAML: {yaml_path}\n  {e}", file=sys.stderr)
        sys.exit(2)
    owner = data.get("github_owner") or GITHUB_OWNER
    _REGISTRY_GITHUB_OWNER = str(owner)
    pkgs = data.get("packages")
    if not isinstance(pkgs, dict) or not pkgs:
        print("[错误] package_registry.yaml 中 packages 必须为非空 dict", file=sys.stderr)
        sys.exit(2)
    gh: Dict[str, Any] = {}
    pip: Dict[str, Any] = {}
    nu: Dict[str, Any] = {}
    for name, meta in pkgs.items():
        if not isinstance(meta, dict):
            continue
        kind = meta.get("kind")
        nm = str(name)
        if kind == "github":
            entry: Dict[str, Any] = {}
            if meta.get("repo"):
                entry["repo"] = meta["repo"]
            gh[nm] = entry
        elif kind == "pip":
            pip[nm] = {
                "pip_name": meta.get("pip_name", nm),
                "python_ver": str(meta.get("python_ver", "3.12")),
            }
        elif kind == "nuget":
            nu[nm] = {k: v for k, v in meta.items() if k != "kind"}
    _GITHUB_PACKAGES.clear()
    _GITHUB_PACKAGES.update(gh)
    _PIP_PACKAGES.clear()
    _PIP_PACKAGES.update(pip)
    _NUGET_PACKAGES.clear()
    _NUGET_PACKAGES.update(nu)
    PACKAGE_REGISTRY.clear()
    PACKAGE_REGISTRY.update({**_GITHUB_PACKAGES, **_PIP_PACKAGES, **_NUGET_PACKAGES})


def _github_clone_url(package_name: str, entry: Dict[str, Any]) -> str:
    r = entry.get("repo")
    if r and "/" in str(r):
        return f"https://github.com/{r}.git"
    repo = (r or package_name)
    return f"https://github.com/{_REGISTRY_GITHUB_OWNER}/{repo}.git"


def _extract_payload_paths_from_ast(package_py: Path) -> Optional[List[str]]:
    """仅 ast：无 _REZ_WUWO_PAYLOAD_RELATIVE_PATHS 则 None；多赋值只认最后一次 Assign；非法形状抛 ValueError。"""
    text = package_py.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(package_py))
    last_assign: Optional[ast.Assign] = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "_REZ_WUWO_PAYLOAD_RELATIVE_PATHS":
                    last_assign = node
    if last_assign is None:
        return None
    val = last_assign.value
    if not isinstance(val, (ast.List, ast.Tuple)):
        raise ValueError("_REZ_WUWO_PAYLOAD_RELATIVE_PATHS must be a list or tuple of string literals")
    out: List[str] = []
    for elt in val.elts:
        if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
            raise ValueError("_REZ_WUWO_PAYLOAD_RELATIVE_PATHS entries must be string literals")
        out.append(elt.value)
    return out


def check_github_pkg_payload(source_dir: Path, pkg_name: str) -> Tuple[bool, Optional[str]]:
    """载荷就绪或无需检查 → (True, None)；缺文件 → (False, msg)；AST 非法 → (False, msg)。"""
    pkg_dir = source_dir / pkg_name
    pkg_files = list(pkg_dir.glob("*/package.py")) if pkg_dir.is_dir() else []
    if not pkg_files:
        return True, None
    package_py = pkg_files[0]
    root = package_py.parent
    try:
        paths = _extract_payload_paths_from_ast(package_py)
    except SyntaxError as e:
        return False, f"{package_py}: syntax error: {e}"
    except ValueError as e:
        return False, str(e)
    if paths is None:
        return True, None
    for rel in paths:
        p = root / rel
        if not p.is_file():
            return False, f"payload file missing: {p}"
    return True, None


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


def github_pkg_local_ready(source_dir: Path, pkg_name: str) -> bool:
    """rez-package-source 下该 GitHub 包是否已有有效 ``*/package.py``。"""
    pkg_dir = source_dir / pkg_name
    return bool(list(pkg_dir.glob("*/package.py"))) if pkg_dir.is_dir() else False


def collect_transitive_github_packages(
    root_github_pkgs: List[str], source_dir: Path
) -> List[str]:
    """从根包出发 BFS 得到传递闭包内所有 _GITHUB_PACKAGES 包名（有序、去重）。"""
    out: List[str] = []
    visited: set[str] = set()
    queue: List[str] = [p for p in root_github_pkgs if p in _GITHUB_PACKAGES]

    while queue:
        pkg = queue.pop(0)
        if pkg in visited:
            continue
        visited.add(pkg)
        out.append(pkg)
        for r in get_requires_for_package(pkg, source_dir):
            if r in _GITHUB_PACKAGES:
                queue.append(r)
    return out


def ensure_github_packages_for_rez_env(
    known: List[str], source_dir: Path, *, skip_init: bool = False
) -> int:
    """按需克隆并校验载荷；clone 就绪但缺载荷时仅运行 999.0/init.bat（若存在）。返回失败次数。"""
    if not source_dir.exists():
        source_dir.mkdir(parents=True, exist_ok=True)

    fails = 0
    max_rounds = 256
    for _ in range(max_rounds):
        chain = collect_transitive_github_packages(known, source_dir)
        target: Optional[str] = None
        mode: Optional[str] = None  # "clone" | "init_only"
        for pkg_name in chain:
            if not github_pkg_local_ready(source_dir, pkg_name):
                target, mode = pkg_name, "clone"
                break
            pay_ok, pay_err = check_github_pkg_payload(source_dir, pkg_name)
            if pay_ok:
                continue
            # AST / 形状错误：不尝试 init
            if pay_err and "payload file missing" not in pay_err:
                print(f"[for-rez-env] [错误] 包 {pkg_name}: {pay_err}", file=sys.stderr)
                fails += 1
                return fails
            if not skip_init and (source_dir / pkg_name / "999.0" / "init.bat").is_file():
                target, mode = pkg_name, "init_only"
                break
            print(
                f"[for-rez-env] [错误] 包 {pkg_name} 缺载荷且无 999.0/init.bat: {pay_err}",
                file=sys.stderr,
            )
            fails += 1
            return fails
        if target is None:
            break
        pkg_name = target
        pkg_dir = source_dir / pkg_name
        if mode == "clone":
            if not _check_git_available():
                print("[for-rez-env] [错误] git 不可用，无法克隆缺失包", file=sys.stderr)
                fails += 1
                break
            print(f"[for-rez-env] 克隆缺失包: {pkg_name} ...")
            ok, msg = clone_package(pkg_name, source_dir)
            print(f"  [{'OK' if ok else 'FAIL'}] {pkg_name}: {msg}")
            if not ok:
                fails += 1
                break
            if not skip_init:
                init_ok, init_msg = run_convention_init_if_present(pkg_dir)
                print(f"      init: {init_msg}")
                if not init_ok:
                    print(f"      [WARN] {init_msg}")
        elif mode == "init_only":
            if skip_init:
                fails += 1
                break
            print(f"[for-rez-env] 载荷未就绪，运行 999.0/init.bat: {pkg_name} ...")
            init_ok, init_msg = run_convention_init_if_present(pkg_dir)
            print(f"  [{'OK' if init_ok else 'FAIL'}] init: {init_msg}")
            if not init_ok:
                fails += 1
                break
            pay_ok2, pay_err2 = check_github_pkg_payload(source_dir, pkg_name)
            if not pay_ok2:
                print(f"[for-rez-env] [错误] init 后仍缺载荷: {pay_err2}", file=sys.stderr)
                fails += 1
                return fails
    else:
        print("[for-rez-env] [WARN] 处理轮次过多，中止", file=sys.stderr)
        fails += 1

    return fails


def update_github_packages_for_rez_env(known: List[str], source_dir: Path) -> int:
    """更新当前 env 子图中的 GitHub 包（git pull --ff-only）。"""
    if not known:
        return 0
    if not _check_git_available():
        print("[for-rez-env] [错误] git 不可用，无法更新 GitHub 包", file=sys.stderr)
        return 1

    fails = 0
    chain = collect_transitive_github_packages(known, source_dir)
    for pkg_name in chain:
        pkg_dir = source_dir / pkg_name
        if not (pkg_dir / ".git").is_dir():
            continue
        entry = _GITHUB_PACKAGES.get(pkg_name, {})
        repo_url = _github_clone_url(pkg_name, entry)
        ok_pull, pull_msg = _git_pull_with_mirrors(pkg_dir, repo_url)
        if ok_pull:
            print(f"  [OK] github update {pkg_name}")
        else:
            print(f"  [WARN] github update {pkg_name} 失败: {pull_msg}", file=sys.stderr)
            fails += 1
    return fails


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


def _build_git_mirror_urls(url: str) -> List[str]:
    urls = [url]
    if url.startswith("https://github.com/"):
        urls.append("https://ghproxy.com/" + url)
        urls.append(url.replace("https://github.com/", "https://gitclone.com/github.com/"))
    out: List[str] = []
    seen = set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _git_clone_with_mirrors(dest: Path, repo_url: str, timeout: int = 300) -> Tuple[bool, str]:
    last_err = ""
    for url in _build_git_mirror_urls(repo_url):
        result = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return True, f"git clone 成功: {url}"
        last_err = (result.stderr or result.stdout or "").strip()
    return False, f"git clone 全部镜像失败: {last_err}"


def _git_pull_with_mirrors(repo_dir: Path, repo_url: str) -> Tuple[bool, str]:
    base = subprocess.run(
        ["git", "-C", str(repo_dir), "pull", "--ff-only"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if base.returncode == 0:
        return True, "origin pull 完成"
    branch = "HEAD"
    b = subprocess.run(
        ["git", "-C", str(repo_dir), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    if b.returncode == 0 and b.stdout.strip():
        branch = b.stdout.strip()

    last_err = (base.stderr or base.stdout or "").strip()
    for url in _build_git_mirror_urls(repo_url):
        res = subprocess.run(
            ["git", "-C", str(repo_dir), "pull", "--ff-only", url, branch],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if res.returncode == 0:
            return True, f"镜像 pull 完成: {url}"
        last_err = (res.stderr or res.stdout or "").strip()
    return False, f"git pull 全部镜像失败: {last_err}"


def clone_package(package_name: str, target_dir: Path) -> Tuple[bool, str]:
    """从 GitHub clone 包到目标目录（URL 由注册表 entry 与 github_owner 决定）。"""
    entry = _GITHUB_PACKAGES.get(package_name, {})
    url = _github_clone_url(package_name, entry)
    dest = target_dir / package_name

    try:
        ok_clone, clone_msg = _git_clone_with_mirrors(dest, url, timeout=300)
        if not ok_clone:
            return False, clone_msg

        # 设置 core.longpaths = true
        subprocess.run(
            ["git", "config", "core.longpaths", "true"],
            cwd=str(dest),
            capture_output=True,
            text=True,
        )

        return True, clone_msg

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
    if not init_path.is_file():
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


def run_convention_init_if_present(package_root: Path) -> Tuple[bool, str]:
    """仅当存在 999.0/init.bat（文件）时执行；路径不从 yaml 读取。"""
    rel = Path("999.0") / "init.bat"
    init_path = package_root / rel
    if not init_path.is_file():
        return True, "no 999.0/init.bat"
    return run_init_script(package_root, rel.as_posix().replace("/", os.sep))


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


def _requires_names_from_package_py_text(content: str) -> List[str]:
    """解析 package.py 文本中的 requires 列表，返回包名（不含版本段，如 python-3.12 → python）。"""
    import re

    m = re.search(r'requires\s*=\s*\[([^\]]+)\]', content, re.S)
    if not m:
        return []
    raw = m.group(1)
    return re.findall(r'["\']([\w]+)', raw)


def get_requires_for_package(pkg_name: str, source_dir: Path) -> List[str]:
    """从 rez-package-source/<pkg_name>/*/package.py 读取 requires 列表。

    返回包名列表（去除版本约束，如 'python-3.12+<3.13' 取 'python'）。
    """
    pkg_files = list((source_dir / pkg_name).glob("*/package.py"))
    if not pkg_files:
        print(f"[WARN] {pkg_name}/package.py 未找到，无法读取 requires", file=sys.stderr)
        return []
    content = pkg_files[0].read_text(encoding="utf-8")
    return _requires_names_from_package_py_text(content)


def _registry_key_for_family(family: str) -> Optional[str]:
    """requires 中的家族短名（大小写不敏感）对应到 PACKAGE_REGISTRY 里的键。"""
    fl = family.split("-")[0].lower()
    for key in PACKAGE_REGISTRY:
        if str(key).split("-")[0].lower() == fl:
            return str(key)
    return None


def collect_for_rez_env_nuget_and_pip_closure(
    github_roots: List[str],
    top_level_families: List[str],
    source_dir: Path,
    extra_pip_meta: Dict[str, Any],
) -> Tuple[List[str], List[str], Dict[str, Any], Optional[str]]:
    """在 GitHub 闭包已就绪后，扫描所有 ``requires``，得到待安装的 nuget 键列表与 pip 键列表。

    - 传递链中 ``kind: nuget`` / ``kind: pip`` / PyPI 未登记名均会进入对应列表。
    - 未登记且非 PyPI：警告并跳过（不中断）；顶层 env 包名仍由调用方严格校验。
    - 返回 ``(nuget_keys_ordered, pip_keys_ordered, transitive_pypi_meta, err)``；``err`` 保留供扩展。
    """
    pypi_ok: Dict[str, bool] = {}
    transitive_pypi: Dict[str, Any] = dict(extra_pip_meta)
    nuget_seen: set[str] = set()
    nuget_order: List[str] = []
    pip_seen: set[str] = set()
    pip_order: List[str] = []

    def add_nuget(canonical: str) -> None:
        if canonical in _NUGET_PACKAGES and canonical not in nuget_seen:
            nuget_seen.add(canonical)
            nuget_order.append(canonical)

    def add_pip(canonical: str) -> None:
        if canonical not in pip_seen:
            pip_seen.add(canonical)
            pip_order.append(canonical)

    for t in top_level_families:
        k = _registry_key_for_family(t)
        if k and k in _NUGET_PACKAGES:
            add_nuget(k)
        elif k and k in _PIP_PACKAGES:
            add_pip(k)
        elif t in transitive_pypi:
            add_pip(t)
        elif k and k in transitive_pypi:
            add_pip(k)

    gh_chain = (
        collect_transitive_github_packages(github_roots, source_dir) if github_roots else []
    )

    for gpkg in gh_chain:
        for r in get_requires_for_package(gpkg, source_dir):
            k = _registry_key_for_family(r)
            if k and k in _GITHUB_PACKAGES:
                continue
            if k and k in _NUGET_PACKAGES:
                add_nuget(k)
                continue
            if k and k in _PIP_PACKAGES:
                add_pip(k)
                continue
            if r in transitive_pypi:
                add_pip(r)
                continue
            if k and k in transitive_pypi:
                add_pip(k)
                continue
            if k and k in PACKAGE_REGISTRY:
                continue
            if r not in pypi_ok:
                pypi_ok[r] = is_pypi_package(r)
            if pypi_ok[r]:
                transitive_pypi[r] = {"pip_name": r, "python_ver": "3.12"}
                add_pip(r)
            else:
                print(
                    f"[for-rez-env] [WARN] 传递依赖 {r!r} 未登记且非 PyPI，已跳过 "
                    f"（由 {gpkg!r} 的 requires 引用）；rez 若缺包请写入 package_registry.yaml。",
                    file=sys.stderr,
                )

    if "python" in nuget_order:
        nuget_order = ["python"] + [x for x in nuget_order if x != "python"]

    return (nuget_order, pip_order, transitive_pypi, None)


def check_python_executable() -> Optional[Path]:
    """查找当前 Python 可执行文件路径。"""
    try:
        import sys
        return Path(sys.executable)
    except Exception:
        return None


def install_pip_package_to_3rd(
    pkg_name: str, meta: dict, third_party_dir: Path, *, force_reinstall: bool = False
) -> Tuple[bool, str]:
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

    # 已存在则跳过（更新模式可强制重装）
    if (pkg_dir / "package.py").exists() and not force_reinstall:
        return True, f"已存在: {pkg_dir}"
    if force_reinstall and pkg_dir.exists():
        _safe_rmtree(pkg_dir)

    # pip install
    python_exe = check_python_executable()
    if not python_exe:
        return False, "找不到 Python 可执行文件"

    print(f"      pip install {pip_name} → {hidden_dir}")
    last_err = ""
    mirror_labels = ["中科大", "阿里云", "PyPI 官方"]
    for idx_url, label in zip(PIP_INDEX_URLS, mirror_labels):
        try:
            cmd = [
                str(python_exe),
                "-m",
                "pip",
                "install",
                pip_name,
                "--target",
                str(hidden_dir),
                "-i",
                idx_url,
                "--no-warn-script-location",
                "--quiet",
            ]
            if force_reinstall:
                cmd.append("--upgrade")
            result = subprocess.run(
                cmd,
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
    req_lit = _pip_rez_requires_literal(pkg_name, python_ver)
    cmd_blk = _pip_rez_pythonpath_commands(pkg_name)
    package_py.write_text(
        f'# -*- coding: utf-8 -*-\n'
        f'name = "{pkg_name}"\n'
        f'version = "{rez_ver}"\n'
        f'description = "{meta.get("description", pkg_name)}"\n'
        f"requires = {req_lit}\n"
        f'build_command = False\n'
        f'cachable = True\n'
        f'relocatable = True\n'
        f'\n'
        f'def commands():\n'
        f"{cmd_blk}",
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


def install_nuget_package_to_3rd(
    pkg_name: str, meta: dict, third_party_dir: Path, *, force_reinstall: bool = False
) -> Tuple[bool, str]:
    """安装 nuget 包（如 python）到 rez-package-3rd。

    与 rez-package-source 中声明的 python 依赖一致：默认从 NuGet 解压完整运行时到
    ``rez-package-3rd/python/<rez_ver>/``，便于独立分发、不依赖 wuwo/py_312 路径。

    若 NuGet 下载或解压失败，且存在 ``wuwo/py_312/python.exe``，则回退为仅生成指向
    py_312 的 ``package.py`` 包装。
    """
    rez_ver = meta.get("rez_ver", "3.12.10")
    pkg_dir = third_party_dir / pkg_name / rez_ver

    if (pkg_dir / "package.py").exists() and not force_reinstall:
        return True, f"已存在: {pkg_dir}"
    if force_reinstall and pkg_dir.exists():
        _safe_rmtree(pkg_dir)

    pkg_dir.mkdir(parents=True, exist_ok=True)

    ok, msg = _download_nuget_python(pkg_name, meta, pkg_dir, third_party_dir)
    if ok:
        return ok, msg

    wuwo_dir = Path(__file__).resolve().parent
    py312_exe = wuwo_dir / "py_312" / "python.exe"
    if py312_exe.exists():
        print(f"      [WARN] NuGet Python 未就绪，回退使用 wuwo/py_312 包装: {msg}")
        try:
            if pkg_dir.exists():
                shutil.rmtree(pkg_dir)
            pkg_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return False, f"NuGet 失败且无法清理目录 {pkg_dir}: {exc}; 原因为: {msg}"
        return _write_python_rez_wrapper(pkg_dir, py312_exe.parent, rez_ver)

    return ok, msg


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
        help=(
            "解析 'rez env ...'：按需克隆 GitHub 包、安装依赖树内全部 nuget/pip（含传递与 PyPI 未登记名）"
        ),
    )

    args = parser.parse_args()

    # --for-rez-env：GitHub 克隆/载荷 + 闭包内全部 nuget（registry）与 pip（含传递 PyPI）
    if args.for_rez_env:
        source_dir = find_rez_package_source(args.source_dir)
        load_live_registry(source_dir)
        raw_args = args.for_rez_env.split("--")[0]
        raw_tokens = raw_args.split()
        update_mode = has_update_ephemeral(raw_tokens)
        pkg_names = parse_rez_env_root_packages(raw_tokens, PACKAGE_REGISTRY)
        if update_mode:
            print("[for-rez-env] 检测到 .updata/.update，启用依赖更新模式（GitHub pull + nuget/pip 重装）")
        dynamic_pip: Dict[str, Any] = {}
        for p in pkg_names:
            if p not in PACKAGE_REGISTRY:
                if not is_pypi_package(p):
                    print(
                        f"[for-rez-env] [错误] 依赖名未在 package_registry.yaml 且非 PyPI 包: {p}\n"
                        f"  请在 {registry_yaml_path(source_dir)} 中登记（如 kind: github）或修正名称。",
                        file=sys.stderr,
                    )
                    return 1
                dynamic_pip[p] = {"pip_name": p, "python_ver": "3.12"}
        merged_registry: Dict[str, Any] = {**PACKAGE_REGISTRY, **dynamic_pip}

        third_party_dir = source_dir.parent / "rez-package-3rd"
        third_party_dir.mkdir(parents=True, exist_ok=True)

        github_known = [p for p in pkg_names if p in _GITHUB_PACKAGES]
        fail = 0
        if github_known:
            fail = ensure_github_packages_for_rez_env(
                github_known, source_dir, skip_init=args.skip_init
            )
            if fail:
                return fail
            if update_mode:
                fail += update_github_packages_for_rez_env(github_known, source_dir)

        nuget_keys, pip_deps, trans_pip_meta, pip_collect_err = (
            collect_for_rez_env_nuget_and_pip_closure(
                github_known, pkg_names, source_dir, dynamic_pip
            )
        )
        if pip_collect_err:
            print(f"[for-rez-env] [错误] {pip_collect_err}", file=sys.stderr)
            return 1
        merged_registry = {**merged_registry, **trans_pip_meta}

        if nuget_keys:
            print(f"[for-rez-env] 依赖树中的 nuget 包，安装到 rez-package-3rd: {nuget_keys}")
            for nk in nuget_keys:
                meta = _NUGET_PACKAGES[nk]
                ok, msg = install_nuget_package_to_3rd(
                    nk, meta, third_party_dir, force_reinstall=update_mode
                )
                print(f"  [{'OK' if ok else 'FAIL'}] {nk}: {msg}")
                if not ok:
                    fail += 1

        if not pip_deps:
            if not nuget_keys:
                print("[for-rez-env] 无需安装 nuget / pip 第三方包")
            return 1 if fail else 0

        print(f"[for-rez-env] 将安装 pip 包: {pip_deps}")
        for pkg in pip_deps:
            meta = merged_registry[pkg]
            ok, msg = install_pip_package_to_3rd(
                pkg, meta, third_party_dir, force_reinstall=update_mode
            )
            print(f"  [{'OK' if ok else 'FAIL'}] {pkg}: {msg}")
            if not ok:
                fail += 1
        return 1 if fail else 0

    # --for-package / 全量模式：确定 rez-package-source 路径
    source_dir = find_rez_package_source(args.source_dir)
    load_live_registry(source_dir)
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
                    _ok, _msg = clone_package(args.for_package, source_dir)
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

            # 未在注册表：须为 PyPI 包，否则失败（与 --for-rez-env 一致）
            if not_in_registry:
                print(f"[信息] 以下依赖不在注册表中，校验 PyPI…: {not_in_registry}")
                for r in not_in_registry:
                    if is_pypi_package(r):
                        print(f"        [OK] {r} 在 PyPI 上存在，加入 pip 安装列表")
                        pip_deps.append(r)
                        PACKAGE_REGISTRY[r] = {"pip_name": r, "python_ver": "3.12"}
                    else:
                        err_msg = (
                            f"[错误] 依赖 {r} 未在 package_registry.yaml 且非 PyPI 包。\n"
                            f"  请登记: {registry_yaml_path(source_dir)}"
                        )
                        print(err_msg, file=sys.stderr)
                        _show_error_popup("wuwo: 未注册依赖", err_msg)
                        return 1

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

    # 全量模式下同步收集所有 pip 包以便后续安装（不扫全树装 python；python 见 --for-rez-env）
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
                pkg_dir = source_dir / pkg_name
                entry = _GITHUB_PACKAGES.get(pkg_name, {})
                clone_url = _github_clone_url(pkg_name, entry)

                print(f"[{idx}/{len(missing)}] 正在克隆 {pkg_name} ...")
                print(f"      git clone --depth 1 {clone_url}")

                # --force 模式下先删除已有目录
                if args.force and pkg_dir.exists():
                    print("      (--force) 删除已有目录...")
                    try:
                        _safe_rmtree(pkg_dir)
                    except Exception as e:
                        print(f"      [错误] 删除失败: {e}")
                        fail_count += 1
                        continue

                ok, msg = clone_package(pkg_name, source_dir)

                if not ok:
                    print(f"      [错误] {msg}")
                    fail_count += 1
                    continue

                print(f"      {msg}")
                success_count += 1

                if not args.skip_init:
                    print("      检查 999.0/init.bat …")
                    init_ok, init_msg = run_convention_init_if_present(pkg_dir)
                    if "no 999.0" not in init_msg:
                        print(f"      {init_msg}")
                    if not init_ok:
                        print(f"      [警告] {init_msg}")
                        init_fail_count += 1

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
