# -*- coding: utf-8 -*-
name = "lugwit_env"
version = "1.0.0"
description = "Lugwit site environment - injects deployment paths and config dir"
authors = ["Lugwit Team"]

requires = []

build_command = False
cachable = False
relocatable = False


def commands():
    # --- deployment paths (replaces EnvVar_orgi.json) ---
    env.TD_DepotDir = "D:\\TD_Depot"
    env.Lugwit_publicPath = "A:\\TD"
    env.LugwitAppDir = "D:\\TD_Depot\\Software\\Lugwit_syncPlug\\lugwit_insapp"
    env.LugwitLibDir = "D:\\TD_Depot\\Software\\Lugwit_syncPlug\\lugwit_insapp\\trayapp\\Lib"
    env.LugwitPath = "D:\\TD_Depot\\plug_in\\Lugwit_plug"
    env.Lugwit_mayaPluginPath = "D:\\TD_Depot\\plug_in\\Lugwit_plug\\mayaPlug"
    env.Yplug = "D:\\TD_Depot\\plug_in\\Yplug"
    env.P4CHARSET = "utf8"
    env.DEADLINE_PATH = "D:\\TD_Depot\\Software\\dccData\\ThinkBox\\Deadline_Client\\bin"
    env.NUKE_PATH = "D:\\TD_Depot\\Software\\dccData\\NukePlug;C:\\ProgramData\\Thinkbox\\Deadline10\\submitters\\Nuke"

    # --- 与 l_tray 包内 config 统一（EnvVar_orgi / ToolEnv_orgi / smallProgramList 等）---
    env.WUWO_CONFIG_DIR = (
        "{root}\\..\\..\\..\\..\\rez-package-source\\l_tray\\999.0\\src\\l_tray\\config"
    )
    env.WUWO_DIR = "{root}\\..\\..\\.."
    env.WUWO_ICONS_DIR = "{root}\\..\\..\\..\\icons"

    # --- tool_env.py is importable from this package ---
    env.PYTHONPATH.prepend("{root}\\src")
