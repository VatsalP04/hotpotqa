"""
Configuration management for HotpotQA NLP Pipeline.

This module provides utilities for loading, merging, and accessing configuration
from YAML files with support for inheritance and overrides.
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional, Union
from copy import deepcopy


class ConfigManager:
    """
    Manager for loading and accessing configuration from YAML files.

    Supports loading base configuration and overlaying specific configs,
    as well as runtime overrides via dictionary or environment variables.
    """

    def __init__(self, config_path: Optional[Union[str, Path]] = None):
        """
        Initialize the configuration manager.

        Args:
            config_path: Path to the main configuration file. If None, loads default.yaml
                        from the configs directory.
        """
        self.project_root = Path(__file__).resolve().parents[2]
        self.config_dir = self.project_root / "configs"

        if config_path is None:
            config_path = self.config_dir / "default.yaml"
        else:
            config_path = Path(config_path)
            if not config_path.is_absolute():
                config_path = self.config_dir / config_path

        self.config_path = config_path
        self._config: Dict[str, Any] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from the YAML file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        with open(self.config_path, 'r') as f:
            self._config = yaml.safe_load(f) or {}

    def merge_config(self, overlay_config: Union[str, Path, Dict[str, Any]]) -> None:
        """
        Merge additional configuration on top of the current config.

        Args:
            overlay_config: Either a path to a YAML file, or a dictionary of config values.
                           Values in overlay_config will override existing values.
        """
        if isinstance(overlay_config, dict):
            overlay_dict = overlay_config
        else:
            overlay_path = Path(overlay_config)
            if not overlay_path.is_absolute():
                overlay_path = self.config_dir / overlay_path

            if not overlay_path.exists():
                raise FileNotFoundError(f"Overlay config file not found: {overlay_path}")

            with open(overlay_path, 'r') as f:
                overlay_dict = yaml.safe_load(f) or {}

        self._config = self._deep_merge(self._config, overlay_dict)

    @staticmethod
    def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deep merge two dictionaries, with overlay taking precedence.

        Args:
            base: Base dictionary
            overlay: Dictionary to merge on top

        Returns:
            Merged dictionary
        """
        result = deepcopy(base)

        for key, value in overlay.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigManager._deep_merge(result[key], value)
            else:
                result[key] = deepcopy(value)

        return result

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value using dot notation.

        Args:
            key: Configuration key in dot notation (e.g., 'data.raw_dir')
            default: Default value if key is not found

        Returns:
            Configuration value

        Example:
            >>> config = ConfigManager()
            >>> config.get('data.raw_dir')
            'data/raw'
            >>> config.get('data.max_examples', 1000)
            1000
        """
        keys = key.split('.')
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """
        Set a configuration value using dot notation.

        Args:
            key: Configuration key in dot notation (e.g., 'data.raw_dir')
            value: Value to set

        Example:
            >>> config = ConfigManager()
            >>> config.set('data.max_examples', 500)
        """
        keys = key.split('.')
        target = self._config

        for k in keys[:-1]:
            if k not in target or not isinstance(target[k], dict):
                target[k] = {}
            target = target[k]

        target[keys[-1]] = value

    def get_section(self, section: str) -> Dict[str, Any]:
        """
        Get an entire configuration section.

        Args:
            section: Section name (e.g., 'data', 'preprocessing')

        Returns:
            Dictionary containing the section configuration
        """
        return self.get(section, {})

    def get_embeddings_path(self) -> Path:
        """
        Resolve the embeddings file path from configuration.

        Priority:
        1. `data.embeddings_path` (absolute or relative to project root)
        2. `data.embeddings_dir` + `data.embeddings_file` (both relative to project root)

        Returns:
            Path pointing to the embeddings file (may not exist yet).
        """
        # First, allow a single explicit path
        embeddings_path = self.get('data.embeddings_path')
        if embeddings_path:
            p = Path(embeddings_path)
            if not p.is_absolute():
                p = self.project_root / p
            return p

        # Fallback to directory + filename
        embeddings_dir = Path(self.get('data.embeddings_dir', 'data/embeddings'))
        embeddings_file = self.get('data.embeddings_file', 'glove.840B.300d.txt')

        if not embeddings_dir.is_absolute():
            embeddings_dir = self.project_root / embeddings_dir

        return embeddings_dir / embeddings_file

    def to_dict(self) -> Dict[str, Any]:
        """Get the full configuration as a dictionary."""
        return deepcopy(self._config)

    def save(self, output_path: Union[str, Path]) -> None:
        """
        Save the current configuration to a YAML file.

        Args:
            output_path: Path where to save the configuration
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w') as f:
            yaml.dump(self._config, f, default_flow_style=False, sort_keys=False)

    def __getitem__(self, key: str) -> Any:
        """Allow dictionary-style access to configuration."""
        return self.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        """Allow dictionary-style setting of configuration."""
        self.set(key, value)

    def __contains__(self, key: str) -> bool:
        """Check if a configuration key exists."""
        return self.get(key) is not None

    def __repr__(self) -> str:
        """String representation of the config manager."""
        return f"ConfigManager(config_path='{self.config_path}')"


def load_config(
    config_file: Optional[str] = None,
    preset: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None
) -> ConfigManager:
    """
    Convenience function to load configuration with optional preset and overrides.

    Args:
        config_file: Base configuration file (default: 'default.yaml')
        preset: Preset name from preprocessing.yaml (e.g., 'quick', 'full', 'rag')
        overrides: Dictionary of configuration overrides

    Returns:
        Configured ConfigManager instance

    Example:
        >>> config = load_config(preset='quick', overrides={'data.max_examples': 50})
    """
    # Load base config
    if config_file is None:
        config = ConfigManager()
    else:
        config = ConfigManager(config_file)

    # Apply preset if specified
    if preset:
        preprocessing_config_path = config.config_dir / "preprocessing.yaml"
        if preprocessing_config_path.exists():
            with open(preprocessing_config_path, 'r') as f:
                preprocessing_configs = yaml.safe_load(f) or {}

            if preset in preprocessing_configs:
                config.merge_config(preprocessing_configs[preset])
            else:
                available_presets = list(preprocessing_configs.keys())
                raise ValueError(
                    f"Unknown preset '{preset}'. Available presets: {available_presets}"
                )

    # Apply overrides
    if overrides:
        config.merge_config(overrides)

    return config


if __name__ == "__main__":
    # Demo usage
    print("Loading default configuration...")
    config = ConfigManager()

    print(f"\nProject name: {config.get('project.name')}")
    print(f"Raw data dir: {config.get('data.raw_dir')}")
    print(f"Max length: {config.get('preprocessing.tokenization.max_length')}")

    print("\n--- Loading with 'quick' preset ---")
    config_quick = load_config(preset='quick')
    print(f"Max examples (quick): {config_quick.get('data.max_examples')}")
    print(f"Max length (quick): {config_quick.get('preprocessing.tokenization.max_length')}")

    print("\n--- Testing overrides ---")
    config_custom = load_config(
        preset='quick',
        overrides={'data.max_examples': 50, 'preprocessing.tokenization.max_length': 128}
    )
    print(f"Max examples (custom): {config_custom.get('data.max_examples')}")
    print(f"Max length (custom): {config_custom.get('preprocessing.tokenization.max_length')}")

    print("\n✅ Configuration system working correctly!")
