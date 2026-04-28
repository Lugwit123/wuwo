#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Configuration Loader

Load and parse config.yaml for package management settings.
"""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional


class Config:
    """Configuration manager for Rez package management."""
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize configuration.
        
        Args:
            config_path: Path to config.yaml file (default: config.yaml in script directory)
        """
        if config_path is None:
            config_path = Path(__file__).parent / "config.yaml"
        
        self.config_path = Path(config_path)
        self._config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file.
        
        Returns:
            Configuration dictionary
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    @property
    def packages(self) -> Dict[str, str]:
        """Get package directories configuration."""
        return self._config.get('packages', {})
    
    @property
    def local_packages(self) -> str:
        """Get local packages directory."""
        return self.packages.get('local', 'packages')
    
    @property
    def build_packages(self) -> str:
        """Get build packages directory."""
        return self.packages.get('build', '')
    
    @property
    def release_packages(self) -> str:
        """Get release packages directory."""
        return self.packages.get('release', '')
    
    @property
    def python(self) -> Dict[str, str]:
        """Get Python environment configuration."""
        return self._config.get('python', {})
    
    @property
    def sync_settings(self) -> Dict[str, Any]:
        """Get package sync settings."""
        return self._config.get('sync', {})
    
    @property
    def auto_sync(self) -> bool:
        """Check if auto sync is enabled."""
        return self.sync_settings.get('auto_sync', True)
    
    @property
    def test_packages(self) -> list:
        """Get test packages list."""
        return self._config.get('test_packages', [])
    
    @property
    def build_settings(self) -> Dict[str, Any]:
        """Get build settings."""
        return self._config.get('build', {})
    
    @property
    def exclude_patterns(self) -> list:
        """Get build exclude patterns."""
        return self.build_settings.get('exclude_patterns', [])
    
    def get_test(self, test_name: str) -> Optional[Dict[str, Any]]:
        """Get test configuration by name.
        
        Args:
            test_name: Name of the test (e.g., 'test4')
            
        Returns:
            Test configuration dictionary or None if not found
        """
        testing = self._config.get('testing', {})
        return testing.get(test_name)


def main():
    """Example usage of Config class."""
    config = Config()
    
    print("=" * 60)
    print("Configuration Loaded")
    print("=" * 60)
    print(f"\nLocal packages: {config.local_packages}")
    print(f"Build packages: {config.build_packages}")
    print(f"Release packages: {config.release_packages}")
    print(f"\nAuto sync: {config.auto_sync}")
    print(f"\nTest packages: {len(config.test_packages)}")
    
    # Show test4 configuration
    test4 = config.get_test('test4')
    if test4:
        print(f"\nTest 4: {test4['name']}")
        print(f"Description: {test4['description']}")
        print(f"Steps: {len(test4['steps'])}")


if __name__ == "__main__":
    main()
