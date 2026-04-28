# -*- coding: utf-8 -*-
"""
rez_pip_installer - 自动化添加第三方 pip 包到 rez-package-source

用法:
    python -m rez_pip_installer.install <pip_package_name> [选项]

示例:
    python -m rez_pip_installer.install requests
    python -m rez_pip_installer.install pyfury --import-name pyfory -py 3.12
    python -m rez_pip_installer.install numpy --force --no-deps
"""

from __future__ import print_function

import argparse
import os
import platform
import shutil
import subprocess
import sys
import textwrap


# ---------------------------------------------------------------------------
# 颜色输出辅助
# ---------------------------------------------------------------------------

def _supports_color():
    """简单判断终端是否支持 ANSI 颜色"""
    if os.environ.get("NO_COLOR"):
        return False
    if platform.system() == "Windows":
        return os.environ.get("ANSICON") or "WT_SESSION" in os.environ or "TERM_PROGRAM" in os.environ
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


_COLOR = _supports_color()


def _c(text, code):
    if _COLOR:
        return "\033[{}m{}\033[0m".format(code, text)
    return text


def info(msg):
    print(_c("[信息] ", "36") + msg)


def success(msg):
    print(_c("[成功] ", "32") + msg)


def warn(msg):
    print(_c("[警告] ", "33") + msg)


def error(msg):
    print(_c("[错误] ", "31") + msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# 路径探测
# ---------------------------------------------------------------------------

def find_rez_package_source():
    """自动检测 rez-package-source 目录"""
    # 方式1：从环境变量 WUWO_DIR
    wuwo_dir = os.environ.get("WUWO_DIR")
    if wuwo_dir:
        candidate = os.path.join(os.path.dirname(wuwo_dir), "rez-package-source")
        if os.path.isdir(candidate):
            return candidate

    # 方式2：从脚本位置向上推算
    # wuwo/packages/rez_pip_installer/1.0.0/src/rez_pip_installer/ → 上溯6级到 trayapp/
    script_dir = os.path.dirname(os.path.abspath(__file__))
    trayapp_dir = os.path.normpath(os.path.join(script_dir, *([".."] * 6)))
    candidate = os.path.join(trayapp_dir, "rez-package-source")
    if os.path.isdir(candidate):
        return candidate

    return None


def find_python(py_version, rez_source_dir):
    """在 rez-package-source/python/ 中查找对应版本的 Python 可执行文件"""
    py_exe = os.path.join(rez_source_dir, "python", py_version, ".python", "python.exe")
    if os.path.isfile(py_exe):
        return py_exe

    # 回退到系统 Python
    fallback = shutil.which("python{}".format(py_version)) or shutil.which("python")
    return fallback


# ---------------------------------------------------------------------------
# package.py 模板
# ---------------------------------------------------------------------------

_PACKAGE_TEMPLATE = textwrap.dedent("""\
    # -*- coding: utf-8 -*-
    name = "{name}"
    version = "{version}"
    description = "Auto-installed pip package: {pip_name}"
    authors = ["rez_pip_installer"]

    requires = ["python-{py_major}.{py_minor}+<{py_major}.{py_minor_next}"]

    build_command = False
    cachable = True
    relocatable = True


    def commands():
        import platform
        if platform.system() == "Windows":
            env.PYTHONPATH.prepend("{{root}}\\\\{hidden_dir}")
            env.{upper_name}_ROOT = "{{root}}\\\\{hidden_dir}"
        else:
            env.PYTHONPATH.prepend("{{root}}/{hidden_dir}")
            env.{upper_name}_ROOT = "{{root}}/{hidden_dir}"
""")


# ---------------------------------------------------------------------------
# 安装逻辑
# ---------------------------------------------------------------------------

def run_install(args):
    """执行安装流程"""
    pip_name = args.pip_package_name
    py_version = args.python_version
    rez_version = args.rez_version
    import_name = args.import_name or pip_name
    no_deps = args.no_deps
    force = args.force

    # --- 1. 确定目标目录 ---
    target_dir = args.target_dir
    if not target_dir:
        target_dir = find_rez_package_source()
    if not target_dir or not os.path.isdir(target_dir):
        error("无法找到 rez-package-source 目录。")
        error("请通过 --target-dir 参数指定，或设置 WUWO_DIR 环境变量。")
        return 1

    info("rez-package-source 目录: {}".format(target_dir))

    # --- 2. 解析 Python 版本 ---
    py_parts = py_version.split(".")
    if len(py_parts) < 2:
        error("Python 版本格式不正确，应为 X.Y 格式，如 3.12")
        return 1
    py_major, py_minor = py_parts[0], py_parts[1]
    py_minor_next = str(int(py_minor) + 1)

    # --- 3. 构建目标路径 ---
    version_dir_name = "{}-py{}".format(rez_version, py_version)
    pkg_dir = os.path.join(target_dir, pip_name, version_dir_name)
    hidden_dir = ".{}".format(pip_name)
    install_dir = os.path.join(pkg_dir, hidden_dir)

    if os.path.isdir(pkg_dir) and not force:
        warn("目录已存在: {}".format(pkg_dir))
        warn("如需重新安装，请使用 --force 参数。")
        return 1

    info("目标包目录: {}".format(pkg_dir))
    info("安装目录:   {}".format(install_dir))

    # --- 4. 查找 Python 可执行文件 ---
    python_exe = find_python(py_version, target_dir)
    if not python_exe:
        error("无法找到 Python {} 可执行文件。".format(py_version))
        return 1
    info("使用 Python: {}".format(python_exe))

    # --- 5. 创建目录结构 ---
    os.makedirs(install_dir, exist_ok=True)
    info("已创建目录结构。")

    # --- 6. 生成 package.py ---
    upper_name = pip_name.upper().replace("-", "_").replace(".", "_")
    package_content = _PACKAGE_TEMPLATE.format(
        name=pip_name,
        version=rez_version,
        pip_name=pip_name,
        py_major=py_major,
        py_minor=py_minor,
        py_minor_next=py_minor_next,
        hidden_dir=hidden_dir,
        upper_name=upper_name,
    )
    package_py_path = os.path.join(pkg_dir, "package.py")
    with open(package_py_path, "w", encoding="utf-8") as f:
        f.write(package_content)
    info("已生成 package.py")

    # --- 7. 执行 pip install ---
    pip_cmd = [
        python_exe, "-m", "pip", "install",
        "--target", install_dir,
        "--upgrade",
    ]
    if no_deps:
        pip_cmd.append("--no-deps")
    pip_cmd.append(pip_name)

    info("正在安装 {} ...".format(pip_name))
    info("执行命令: {}".format(" ".join(pip_cmd)))

    try:
        result = subprocess.run(
            pip_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        error("无法执行 Python: {}".format(python_exe))
        _cleanup_on_fail(pkg_dir, target_dir, pip_name)
        return 1
    except subprocess.TimeoutExpired:
        error("pip install 超时（300秒），请检查网络连接。")
        _cleanup_on_fail(pkg_dir, target_dir, pip_name)
        return 1

    # 打印 pip 输出
    if result.stdout:
        for line in result.stdout.strip().splitlines():
            print("  " + line)

    if result.returncode != 0:
        error("pip install 失败（返回码: {}）".format(result.returncode))
        _cleanup_on_fail(pkg_dir, target_dir, pip_name)
        return 1

    success("pip install 完成。")

    # --- 8. 创建顶层 .gitignore（如果不存在）---
    pkg_top_dir = os.path.join(target_dir, pip_name)
    gitignore_path = os.path.join(pkg_top_dir, ".gitignore")
    if not os.path.isfile(gitignore_path):
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write("__pycache__/\n*.pyc\n")
        info("已创建 .gitignore")

    # --- 9. 验证安装 ---
    info("正在验证安装...")
    verify_ok = _verify_install(python_exe, install_dir, import_name)

    # --- 10. 输出结果摘要 ---
    print("")
    print("=" * 60)
    if verify_ok:
        success("安装完成！")
    else:
        warn("安装完成，但验证导入失败。")
        warn("如果 pip 包名与 import 名不同，请使用 --import-name 参数指定。")
    print("-" * 60)
    print("  包名:         {}".format(pip_name))
    print("  rez 版本:     {}".format(rez_version))
    print("  Python 版本:  {}".format(py_version))
    print("  安装位置:     {}".format(pkg_dir))
    if import_name != pip_name:
        print("  导入名:       {}".format(import_name))
    print("=" * 60)

    return 0 if verify_ok else 0  # 即使验证失败也返回0，因为安装本身成功了


def _verify_install(python_exe, install_dir, import_name):
    """尝试在安装目录中 import 包，打印版本"""
    verify_script = (
        "import sys; sys.path.insert(0, r'{install_dir}'); "
        "import {mod}; "
        "v = getattr({mod}, '__version__', getattr({mod}, 'VERSION', '未知')); "
        "print('版本: ' + str(v))"
    ).format(install_dir=install_dir, mod=import_name)

    try:
        result = subprocess.run(
            [python_exe, "-c", verify_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            success("验证通过 - {}".format(result.stdout.strip()))
            return True
        else:
            if result.stderr:
                warn("验证输出: {}".format(result.stderr.strip()[:200]))
            return False
    except Exception as e:
        warn("验证过程出错: {}".format(e))
        return False


def _cleanup_on_fail(pkg_dir, target_dir, pip_name):
    """安装失败时清理已创建的目录"""
    try:
        if os.path.isdir(pkg_dir):
            shutil.rmtree(pkg_dir)
            warn("已清理失败目录: {}".format(pkg_dir))
        # 如果顶层目录为空也删掉
        pkg_top = os.path.join(target_dir, pip_name)
        if os.path.isdir(pkg_top) and not os.listdir(pkg_top):
            os.rmdir(pkg_top)
    except Exception as e:
        warn("清理失败: {}".format(e))


# ---------------------------------------------------------------------------
# 参数解析 & 入口
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="rez_pip_installer",
        description="自动化添加第三方 pip 包到 rez-package-source",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例:
              python -m rez_pip_installer.install requests
              python -m rez_pip_installer.install pyfury --import-name pyfory
              python -m rez_pip_installer.install numpy -py 3.12 -rv 999.0 --no-deps
        """),
    )
    parser.add_argument(
        "pip_package_name",
        help="要安装的 pip 包名（必填）",
    )
    parser.add_argument(
        "--python-version", "-py",
        default="3.12",
        help="目标 Python 版本（默认: 3.12）",
    )
    parser.add_argument(
        "--rez-version", "-rv",
        default="999.0",
        help="rez 包版本号（默认: 999.0）",
    )
    parser.add_argument(
        "--target-dir", "-t",
        default=None,
        help="rez-package-source 路径（默认自动检测）",
    )
    parser.add_argument(
        "--import-name",
        default=None,
        help="Python import 名（当 import 名与 pip 包名不同时使用）",
    )
    parser.add_argument(
        "--no-deps",
        action="store_true",
        default=False,
        help="不安装依赖",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="强制重新安装（覆盖已有目录）",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(run_install(args))


if __name__ == "__main__":
    main()
