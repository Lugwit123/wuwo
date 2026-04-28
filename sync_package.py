#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Rez Package Sync Utility

Automatically syncs packages from release directory to local packages directory.
"""

import sys
import shutil
from pathlib import Path
from typing import Optional, Tuple


class PackageSync:
    """Handle package synchronization between release and local directories."""
    
    def __init__(self, local_packages: str, release_packages: str, build_packages: Optional[str] = None):
        """Initialize package sync.
        
        Args:
            local_packages: Path to local packages directory
            release_packages: Path to release packages directory
            build_packages: Path to build packages directory (optional)
        """
        self.local_packages = Path(local_packages)
        self.release_packages = Path(release_packages)
        self.build_packages = Path(build_packages) if build_packages else None
        
        # Ensure local packages directory exists
        self.local_packages.mkdir(parents=True, exist_ok=True)
    
    def find_latest_version(self, package_name: str) -> Optional[Tuple[str, Path]]:
        """Find the latest version of a package in build or release directory.
        
        Search priority: build_packages -> release_packages
        
        Args:
            package_name: Name of the package
            
        Returns:
            Tuple of (version string, source directory path), or None if not found
        """
        # Try build packages first (if configured)
        if self.build_packages:
            build_dir = self.build_packages / package_name
            if build_dir.exists():
                versions = [d.name for d in build_dir.iterdir() if d.is_dir()]
                if versions:
                    versions.sort(reverse=True)
                    return versions[0], build_dir
        
        # Try release packages
        release_dir = self.release_packages / package_name
        if release_dir.exists():
            versions = [d.name for d in release_dir.iterdir() if d.is_dir()]
            if versions:
                versions.sort(reverse=True)
                return versions[0], release_dir
        
        return None
    
    def package_exists_locally(self, package_name: str) -> bool:
        """Check if package exists in local packages directory.
        
        Args:
            package_name: Name of the package
            
        Returns:
            True if package exists locally
        """
        package_dir = self.local_packages / package_name
        return package_dir.exists() and any(package_dir.iterdir())
    
    def sync_package(self, package_name: str, version: Optional[str] = None) -> Tuple[bool, str]:
        """Sync a package from build/release to local directory.
        
        Args:
            package_name: Name of the package to sync
            version: Specific version to sync (if None, uses latest)
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        # Check if package already exists locally
        if self.package_exists_locally(package_name):
            return True, f"Package '{package_name}' already exists in local packages"
        
        # Find version and source directory
        source_base_dir = None
        if version is None:
            result = self.find_latest_version(package_name)
            if result is None:
                return False, f"Package '{package_name}' not found in build or release packages"
            version, source_base_dir = result
        else:
            # If version is specified, search in build then release
            if self.build_packages:
                build_dir = self.build_packages / package_name
                if (build_dir / version).exists():
                    source_base_dir = build_dir
            
            if source_base_dir is None:
                release_dir = self.release_packages / package_name
                if (release_dir / version).exists():
                    source_base_dir = release_dir
        
        # Determine source path
        if source_base_dir is None:
            # Fallback to release packages for backward compatibility
            source_base_dir = self.release_packages / package_name
        
        source_path = source_base_dir / version
        dest_path = self.local_packages / package_name / version
        
        if not source_path.exists():
            return False, f"Package version '{package_name}/{version}' not found"
        
        # Sync package
        try:
            source_type = "build" if self.build_packages and source_base_dir == self.build_packages / package_name else "release"
            print(f"[INFO] Syncing package '{package_name}' version {version} from {source_type}...")
            print(f"  Source: {source_path}")
            print(f"  Target: {dest_path}")
            
            # Create parent directory
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy package
            shutil.copytree(source_path, dest_path, dirs_exist_ok=True)
            
            return True, f"Package '{package_name}' version {version} synced successfully from {source_type}"
            
        except Exception as e:
            return False, f"Failed to sync package: {e}"


def main():
    """Main entry point for command-line usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Rez Package Sync Utility")
    parser.add_argument("package_name", help="Name of the package to sync")
    parser.add_argument("--version", help="Specific version to sync (default: latest)")
    parser.add_argument("--local", default="packages", help="Local packages directory")
    parser.add_argument("--build", 
                       default=r"d:\TD_Depot\Software\Lugwit_syncPlug\lugwit_insapp\trayapp\rez-package-build",
                       help="Build packages directory (higher priority than release)")
    parser.add_argument("--release", 
                       default=r"d:\TD_Depot\Software\Lugwit_syncPlug\lugwit_insapp\trayapp\Lib\rez-packages-release",
                       help="Release packages directory")
    parser.add_argument("--force", action="store_true", help="Force sync even if package exists locally")
    
    args = parser.parse_args()
    
    # Get script directory
    script_dir = Path(__file__).parent
    local_packages = script_dir / args.local
    
    # Initialize sync
    sync = PackageSync(str(local_packages), args.release, args.build)
    
    # Sync package
    if args.force and sync.package_exists_locally(args.package_name):
        print(f"[INFO] Force sync enabled, removing existing local package...")
        local_dir = local_packages / args.package_name
        shutil.rmtree(local_dir)
    
    success, message = sync.sync_package(args.package_name, args.version)
    
    if success:
        print(f"[SUCCESS] {message}")
        return 0
    else:
        print(f"[ERROR] {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
