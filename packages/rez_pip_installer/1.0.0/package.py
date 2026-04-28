# -*- coding: utf-8 -*-
name = "rez_pip_installer"
version = "1.0.0"
description = "Utility to add third-party pip packages as rez packages to rez-package-source"
authors = ["Lugwit Team"]

requires = []

build_command = False
cachable = False
relocatable = False


def commands():
    import os
    env.PYTHONPATH.prepend("{root}\\src")

    # 注册命令别名
    if os.name == "nt":
        alias("rez_pip_install", 'python -m rez_pip_installer.install')
    else:
        alias("rez_pip_install", 'python -m rez_pip_installer.install')
