# -*- coding: utf-8 -*-
"""
Rez Configuration File

This file configures Rez behavior for the project.
"""

# Default shell for Windows
default_shell = "cmd"

# Available shells
shells = ["cmd", "powershell"]

# Package repository type
package_repository_type = "local"

# Package paths: set REZ_PACKAGES_PATH in wuwo.bat (recommended).
# Local Rez layout per root: <root>/<package_name>/<version>/package.py
# Dev source root: trayapp/rez-package-source (see SOURCE_PACKAGES in wuwo.bat).
# packages_path = [...]  # optional; env REZ_PACKAGES_PATH overrides when set

# Disable memcache warnings
warn_untimestamped = False
warn_old_commands = False

# Build settings
build_directory = "_build"

# Plugin settings
plugin_path = []
