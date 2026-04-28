#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Rez Command Reconfiguration

Custom build command implementation for Rez package management.
This module provides enhanced build functionality with additional features.
"""

import sys
import shutil
from pathlib import Path
from typing import Optional


class RezBuildCommand:
    """Custom Rez build command with enhanced functionality."""
    
    def __init__(self, source_path: str, install_path: Optional[str] = None):
        """Initialize build command.
        
        Args:
            source_path: Path to package source directory
            install_path: Path to install directory (optional)
        """
        self.source_path = Path(source_path)
        self.install_path = Path(install_path) if install_path else None
        
        # Load package.py to get package info
        self.package_info = self._load_package_info()
    
    def _load_package_info(self) -> dict:
        """Load package information from package.py.
        
        Returns:
            Dictionary with package name, version, and build_command
        """
        package_py = self.source_path / "package.py"
        if not package_py.exists():
            raise FileNotFoundError(f"package.py not found in {self.source_path}")
        
        # Simple parsing of package.py
        info = {"name": None, "version": None, "build_command": None}
        
        with open(package_py, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('name ='):
                    info["name"] = line.split('=')[1].strip().strip('"').strip("'")
                elif line.startswith('version ='):
                    info["version"] = line.split('=')[1].strip().strip('"').strip("'")
                elif line.startswith('build_command ='):
                    # Extract build_command value
                    value = line.split('=', 1)[1].strip()
                    if value.lower() not in ['false', 'none', '']:
                        info["build_command"] = value.strip('"').strip("'")
        
        return info
    
    def build(self, install: bool = False, clean: bool = False, verbose: bool = False) -> int:
        """Execute custom build process.
        
        Args:
            install: Whether to install after building
            clean: Whether to clean before building
            verbose: Whether to show verbose output
            
        Returns:
            Exit code (0 for success)
        """
        print("=" * 60)
        print(f"Building package: {self.package_info['name']}")
        print("=" * 60)
        print(f"Source:  {self.source_path}")
        
        if install and self.install_path:
            print(f"Install: {self.install_path}")
        
        print()
        
        # Step 1: Validate
        if not self._validate():
            return 1
        
        # Step 2: Clean if requested
        if clean:
            if not self._clean():
                return 1
        
        # Step 3: Build
        if not self._execute_build(verbose):
            return 1
        
        # Step 4: Install if requested
        if install:
            if not self._install(verbose):
                return 1
        
        print()
        print("=" * 60)
        print("✅ Build completed successfully!")
        print("=" * 60)
        
        return 0
    
    def _validate(self) -> bool:
        """Validate package structure.
        
        Returns:
            True if valid
        """
        print("[1/4] Validating package structure...")
        
        # Check for required files
        required_files = ["package.py"]
        for filename in required_files:
            filepath = self.source_path / filename
            if not filepath.exists():
                print(f"  ❌ Missing required file: {filename}")
                return False
            print(f"  ✅ Found: {filename}")
        
        # Check for build.py
        build_py = self.source_path / "build.py"
        if build_py.exists():
            print(f"  ✅ Found: build.py")
        else:
            print(f"  ⚠️  No build.py (will use default copy)")
        
        print()
        return True
    
    def _clean(self) -> bool:
        """Clean build artifacts.
        
        Returns:
            True if successful
        """
        print("[2/4] Cleaning build artifacts...")
        
        build_dir = self.source_path / "build"
        if build_dir.exists():
            shutil.rmtree(build_dir)
            print(f"  ✅ Removed: {build_dir}")
        else:
            print(f"  ℹ️  No build directory to clean")
        
        print()
        return True
    
    def _execute_build(self, verbose: bool) -> bool:
        """Execute the build process.
        
        Args:
            verbose: Show verbose output
            
        Returns:
            True if successful
        """
        print("[3/4] Executing build...")
        
        # Check if build_command is defined in package.py
        build_command = self.package_info.get("build_command")
        
        if build_command:
            # Replace {root} with actual source path
            build_command = build_command.replace("{root}", str(self.source_path))
            print(f"  Executing build command: {build_command}")
            
            import subprocess
            try:
                result = subprocess.run(
                    build_command,
                    shell=True,
                    check=True,
                    cwd=str(self.source_path)
                )
                print(f"  ✅ Build command completed successfully")
                return True
            except subprocess.CalledProcessError as e:
                print(f"  ❌ Build command failed with exit code {e.returncode}")
                return False
        
        # Check if custom build.py exists
        build_py = self.source_path / "build.py"
        
        if build_py.exists():
            print(f"  Using custom build script: {build_py}")
            # Custom build.py will be called by Rez
            return True
        else:
            print(f"  Using default build process (copy files)")
            return True
        
        print()
    
    def _install(self, verbose: bool) -> bool:
        """Install the package.
        
        Args:
            verbose: Show verbose output
            
        Returns:
            True if successful
        """
        print("[4/4] Installing package...")
        
        if not self.install_path:
            # Default to build directory
            # Determine script directory (where this script is located)
            script_dir = Path(__file__).parent
            build_dir = script_dir.parent / "rez-package-build"
            
            # Set install path to build directory
            self.install_path = build_dir / self.package_info['name'] / self.package_info['version']
            
            if verbose:
                print(f"  Using default build directory: {build_dir}")
        
        print(f"  Target: {self.install_path}")
        
        # Create install directory
        self.install_path.mkdir(parents=True, exist_ok=True)
        
        # Call build.py if it exists
        build_py = self.source_path / "build.py"
        if build_py.exists():
            # Execute build.py with install path
            import subprocess
            result = subprocess.run(
                [sys.executable, str(build_py), str(self.source_path), str(self.install_path)],
                cwd=str(self.source_path)
            )
            if result.returncode != 0:
                print(f"  ❌ Build script failed")
                return False
        else:
            # Default: copy necessary files
            self._copy_files()
        
        print(f"  ✅ Package installed to: {self.install_path}")
        print()
        return True
    
    def _copy_files(self):
        """Copy files to install directory (default behavior)."""
        exclude_patterns = {
            'build', 'build.bat', 'build.py', '.git', '.gitignore',
            '__pycache__', '*.pyc', '*.pyo', '.DS_Store', 'Thumbs.db'
        }
        
        for item in self.source_path.iterdir():
            if item.name in exclude_patterns:
                continue
            
            dest = self.install_path / item.name
            
            if item.is_file():
                shutil.copy2(item, dest)
                print(f"    Copied: {item.name}")
            elif item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
                print(f"    Copied: {item.name}/")


def main():
    """Main entry point for command-line usage."""
    import argparse
    
    # Check if first argument is 'rez' and remove it
    import sys
    if len(sys.argv) > 1 and sys.argv[1].lower() == 'rez':
        sys.argv.pop(1)
    
    # Check if first argument is 'build' subcommand and remove it
    if len(sys.argv) > 1 and sys.argv[1].lower() == 'build':
        sys.argv.pop(1)
    
    parser = argparse.ArgumentParser(description="Enhanced Rez Build Command")
    parser.add_argument("source", nargs='?', default='.', help="Package source directory (default: current directory)")
    parser.add_argument("-i", "--install", action="store_true", help="Install after building")
    parser.add_argument("--install-path", help="Custom install path")
    parser.add_argument("--clean", action="store_true", help="Clean before building")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    # Create build command
    builder = RezBuildCommand(args.source, args.install_path)
    
    # Execute build
    exit_code = builder.build(
        install=args.install,
        clean=args.clean,
        verbose=args.verbose
    )
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
