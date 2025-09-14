# -*- coding: utf-8 -*-
"""
Configuration management for the backend system
"""

import os
from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class BackendConfig:
    """Backend configuration settings"""
    # Server settings
    host: str = "0.0.0.0"
    port: int = 5000
    debug: bool = False
    secret_key: str = "gemma-backend-secret-key"
    
    # Discovery settings
    discovery_interval: float = 2.0  # Fast discovery rate in seconds
    discovery_timeout: float = 3.0   # Timeout for SUT ping
    sut_port: int = 8080

    # Enhanced pairing mode settings
    paired_devices_scan_interval: float = 0.5  # Fast scan for paired devices
    unpaired_discovery_interval: float = 5.0   # Slower scan for network discovery
    enable_priority_scanning: bool = True      # Prioritize paired devices
    instant_paired_discovery: bool = True      # Connect to paired SUTs immediately on startup
    paired_devices_file: str = "paired_devices.json"  # Storage for paired devices
    
    # SUT identification
    sut_identifier_key: str = "gemma_sut_signature"
    sut_identifier_value: str = "gemma_sut_v2"
    
    # Network settings - Leave None for auto-discovery
    network_ranges: List[str] = None  # Auto-detected from local interfaces if None
    
    # Omniparser settings
    omniparser_url: str = "http://localhost:8000"
    
    # Logging
    log_level: str = "INFO"
    log_file: str = "backend.log"
    
    def __post_init__(self):
        """Post-initialization setup"""
        # Network ranges are now dynamically discovered in the discovery service
        # This allows the system to work on any network without configuration
        pass


class ConfigManager:
    """Manages configuration loading and environment overrides"""
    
    @staticmethod
    def load_config() -> BackendConfig:
        """Load configuration with environment variable overrides"""
        config = BackendConfig()
        
        # Override with environment variables
        config.host = os.getenv("BACKEND_HOST", config.host)
        config.port = int(os.getenv("BACKEND_PORT", config.port))
        config.debug = os.getenv("BACKEND_DEBUG", "false").lower() == "true"
        config.secret_key = os.getenv("BACKEND_SECRET_KEY", config.secret_key)
        
        config.discovery_interval = float(os.getenv("DISCOVERY_INTERVAL", config.discovery_interval))
        config.discovery_timeout = float(os.getenv("DISCOVERY_TIMEOUT", config.discovery_timeout))
        config.sut_port = int(os.getenv("SUT_PORT", config.sut_port))

        # Pairing mode settings
        config.paired_devices_scan_interval = float(os.getenv("PAIRED_DEVICES_SCAN_INTERVAL", config.paired_devices_scan_interval))
        config.unpaired_discovery_interval = float(os.getenv("UNPAIRED_DISCOVERY_INTERVAL", config.unpaired_discovery_interval))
        config.enable_priority_scanning = os.getenv("ENABLE_PRIORITY_SCANNING", "true").lower() == "true"
        config.instant_paired_discovery = os.getenv("INSTANT_PAIRED_DISCOVERY", "true").lower() == "true"
        config.paired_devices_file = os.getenv("PAIRED_DEVICES_FILE", config.paired_devices_file)
        
        config.omniparser_url = os.getenv("OMNIPARSER_URL", config.omniparser_url)
        
        config.log_level = os.getenv("LOG_LEVEL", config.log_level)
        config.log_file = os.getenv("LOG_FILE", config.log_file)
        
        return config