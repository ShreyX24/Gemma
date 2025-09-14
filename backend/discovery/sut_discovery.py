# -*- coding: utf-8 -*-
"""
Network SUT discovery service with unique identification
"""

import asyncio
import logging
import socket
import threading
import time
from typing import List, Set, Optional, Dict, Any
import ipaddress
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from .device_registry import DeviceRegistry, SUTDevice, SUTStatus
    from .network_utils import NetworkDiscovery
    from ..core.config import BackendConfig
    from ..core.events import event_bus, EventType
except ImportError:
    # Fallback for direct execution
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from discovery.device_registry import DeviceRegistry, SUTDevice, SUTStatus
    from discovery.network_utils import NetworkDiscovery
    from core.config import BackendConfig
    from core.events import event_bus, EventType

logger = logging.getLogger(__name__)


class SUTDiscoveryService:
    """Service for discovering SUT devices on the network"""
    
    def __init__(self, config: BackendConfig, device_registry: DeviceRegistry):
        self.config = config
        self.registry = device_registry
        self.running = False
        self.discovery_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._discovery_lock = threading.Lock()
        
        # Network scanning
        self.target_ips: Set[str] = set()
        self._initialize_target_ips()

        # Priority discovery tracking
        self.priority_scan_count = 0
        self.general_scan_count = 0
        self.last_priority_scan = 0
        self.last_general_scan = 0

        logger.info(f"SUTDiscoveryService initialized with {len(self.target_ips)} target IPs")
        logger.info(f"Discovery interval: {config.discovery_interval}s")
        logger.info(f"Priority scanning: {config.enable_priority_scanning}")
        if config.enable_priority_scanning:
            logger.info(f"Paired devices scan interval: {config.paired_devices_scan_interval}s")
            logger.info(f"Unpaired discovery interval: {config.unpaired_discovery_interval}s")
        
    def _initialize_target_ips(self):
        """Initialize the list of target IPs to scan using dynamic network discovery"""
        self.target_ips.clear()
        
        # Get network ranges dynamically based on host interfaces
        if hasattr(self.config, 'network_ranges') and self.config.network_ranges:
            # Use configured ranges if explicitly set
            network_ranges = self.config.network_ranges
            logger.info("Using configured network ranges")
        else:
            # Auto-discover network ranges
            network_ranges = NetworkDiscovery.get_local_network_ranges()
            logger.info("Auto-discovered network ranges from local interfaces")
        
        host_ip = NetworkDiscovery.get_host_ip()
        logger.info(f"Host IP detected: {host_ip}")
        
        for network_range in network_ranges:
            try:
                network = ipaddress.ip_network(network_range, strict=False)
                if network.num_addresses <= 256:  # Only scan small networks
                    for ip in network.hosts():
                        self.target_ips.add(str(ip))
                    logger.info(f"Added network range: {network_range} ({network.num_addresses-2} hosts)")
                else:
                    logger.warning(f"Skipping large network: {network_range} ({network.num_addresses} addresses)")
            except ValueError as e:
                logger.error(f"Invalid network range {network_range}: {e}")
                
        logger.info(f"Initialized {len(self.target_ips)} target IPs for scanning across {len(network_ranges)} networks")
        
    def start(self):
        """Start the discovery service"""
        if self.running:
            logger.warning("Discovery service is already running")
            return
            
        self.running = True
        self._stop_event.clear()
        
        self.discovery_thread = threading.Thread(
            target=self._discovery_loop,
            name="SUTDiscovery",
            daemon=True
        )
        self.discovery_thread.start()
        
        logger.info("SUT Discovery service started")
        
    def stop(self):
        """Stop the discovery service"""
        if not self.running:
            return
            
        logger.info("Stopping SUT Discovery service")
        self.running = False
        self._stop_event.set()
        
        if self.discovery_thread and self.discovery_thread.is_alive():
            self.discovery_thread.join(timeout=10)
            
        logger.info("SUT Discovery service stopped")
        
    def _discovery_loop(self):
        """Enhanced discovery loop with priority scanning for paired devices"""
        logger.info("Discovery loop started with priority scanning support")

        # Perform immediate priority scan for paired devices if enabled
        if self.config.enable_priority_scanning and self.config.instant_paired_discovery:
            logger.info("Performing initial priority scan for paired devices...")
            self._perform_priority_scan()

        while self.running and not self._stop_event.is_set():
            try:
                current_time = time.time()
                performed_scan = False

                # Priority scanning for paired devices
                if (self.config.enable_priority_scanning and
                    current_time - self.last_priority_scan >= self.config.paired_devices_scan_interval):

                    self._perform_priority_scan()
                    self.last_priority_scan = current_time
                    performed_scan = True

                # General network discovery
                if current_time - self.last_general_scan >= self.config.unpaired_discovery_interval:
                    self._perform_general_discovery_scan()
                    self.last_general_scan = current_time
                    performed_scan = True

                # Cleanup stale devices
                if performed_scan:
                    self.registry.cleanup_stale_devices()

                # Wait with intelligent interval based on next required scan
                next_priority = self.last_priority_scan + self.config.paired_devices_scan_interval
                next_general = self.last_general_scan + self.config.unpaired_discovery_interval
                next_scan_time = min(next_priority, next_general)
                wait_time = max(0.1, next_scan_time - current_time)  # At least 0.1s wait

                self._stop_event.wait(min(wait_time, 1.0))  # Max 1s wait

            except Exception as e:
                logger.error(f"Error in discovery loop: {e}")
                time.sleep(5)  # Error backoff

        logger.info("Discovery loop ended")
        
    def _perform_discovery_scan(self):
        """Perform a discovery scan across all target IPs"""
        with self._discovery_lock:
            online_count = 0
            
            # Use ThreadPoolExecutor for concurrent scanning
            with ThreadPoolExecutor(max_workers=5) as executor:
                # Submit all scan tasks
                future_to_ip = {
                    executor.submit(self._scan_ip, ip): ip 
                    for ip in self.target_ips
                }
                
                # Process results as they complete
                for future in as_completed(future_to_ip):
                    ip = future_to_ip[future]
                    try:
                        result = future.result()
                        if result:
                            online_count += 1
                    except Exception as e:
                        logger.debug(f"Error scanning {ip}: {e}")
                        
            logger.debug(f"Discovery scan complete: {online_count} SUTs found")
            
    def _scan_ip(self, ip: str) -> Optional[SUTDevice]:
        """Scan a single IP for SUT service"""
        try:
            # Quick port check first
            if not self._is_port_open(ip, self.config.sut_port):
                return None
                
            # Try to contact the SUT service
            response = requests.get(
                f"http://{ip}:{self.config.sut_port}/status",
                timeout=self.config.discovery_timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Verify this is a Gemma SUT
                if self._is_gemma_sut(data):
                    return self._process_sut_response(ip, data)
                else:
                    logger.debug(f"Non-Gemma service found at {ip}:{self.config.sut_port}")
                    
        except (requests.RequestException, ValueError, KeyError):
            # Handle failed SUTs
            existing_device = self.registry.get_device_by_ip(ip)
            if existing_device:
                self.registry.update_device_ping_fail(existing_device.unique_id)
            
        return None
        
    def _is_port_open(self, ip: str, port: int) -> bool:
        """Quick port connectivity check"""
        try:
            with socket.create_connection((ip, port), timeout=1):
                return True
        except (socket.error, OSError):
            return False
            
    def _is_gemma_sut(self, response_data: Dict[str, Any]) -> bool:
        """Check if response indicates a Gemma SUT"""
        # Check for unique identifier
        identifier = response_data.get(self.config.sut_identifier_key)
        if identifier == self.config.sut_identifier_value:
            return True
            
        # Fallback: check for Gemma-specific capabilities
        capabilities = response_data.get("capabilities", [])
        gemma_capabilities = [
            "basic_clicks", "advanced_clicks", "drag_drop", 
            "scroll", "hotkeys", "text_input", "sequences",
            "performance_monitoring", "gaming_optimizations"
        ]
        
        # If it has most Gemma capabilities, it's probably a Gemma SUT
        matching_caps = sum(1 for cap in gemma_capabilities if cap in capabilities)
        return matching_caps >= 5
        
    def _process_sut_response(self, ip: str, response_data: Dict[str, Any]) -> SUTDevice:
        """Process a valid SUT response and register the device"""
        # Generate unique ID (fallback if not provided)
        unique_id = response_data.get("device_id")
        if not unique_id:
            # Fallback: use IP + some unique data from response
            hostname = response_data.get("hostname", "unknown")
            unique_id = f"sut_{ip.replace('.', '_')}_{hostname}"
            
        capabilities = response_data.get("capabilities", [])
        hostname = response_data.get("hostname", "")
        version = response_data.get("version", "unknown")
        
        # Register or update the device
        device = self.registry.register_device(
            ip=ip,
            port=self.config.sut_port,
            unique_id=unique_id,
            capabilities=capabilities,
            hostname=hostname
        )
        
        logger.debug(f"SUT found: {unique_id} at {ip} (v{version}, {len(capabilities)} caps)")
        
        return device
        
    def _perform_priority_scan(self):
        """Perform priority scan for paired devices only"""
        if not self.config.enable_priority_scanning:
            return

        paired_ips = self.registry.get_paired_device_ips()
        if not paired_ips:
            logger.debug("No paired devices to scan")
            return

        logger.debug(f"Starting priority scan for {len(paired_ips)} paired devices")
        with self._discovery_lock:
            online_count = 0

            # Use ThreadPoolExecutor for concurrent scanning
            with ThreadPoolExecutor(max_workers=10) as executor:  # More workers for faster paired scanning
                future_to_ip = {
                    executor.submit(self._scan_ip, ip): ip
                    for ip in paired_ips
                }

                # Process results as they complete
                for future in as_completed(future_to_ip):
                    ip = future_to_ip[future]
                    try:
                        result = future.result()
                        if result:
                            online_count += 1
                    except Exception as e:
                        logger.debug(f"Error scanning paired device {ip}: {e}")

            self.priority_scan_count += 1
            logger.debug(f"Priority scan complete: {online_count}/{len(paired_ips)} paired SUTs online")

    def _perform_general_discovery_scan(self):
        """Perform general network discovery scan for all IPs"""
        logger.debug(f"Starting general discovery scan for {len(self.target_ips)} IPs")
        with self._discovery_lock:
            online_count = 0

            # Use ThreadPoolExecutor for concurrent scanning
            with ThreadPoolExecutor(max_workers=5) as executor:
                # Submit all scan tasks
                future_to_ip = {
                    executor.submit(self._scan_ip, ip): ip
                    for ip in self.target_ips
                }

                # Process results as they complete
                for future in as_completed(future_to_ip):
                    ip = future_to_ip[future]
                    try:
                        result = future.result()
                        if result:
                            online_count += 1
                    except Exception as e:
                        logger.debug(f"Error scanning {ip}: {e}")

            self.general_scan_count += 1
            logger.debug(f"General discovery scan complete: {online_count} SUTs found")

    def force_discovery_scan(self) -> Dict[str, Any]:
        """Force an immediate discovery scan"""
        logger.info("Forcing discovery scan")
        
        start_time = time.time()
        self._perform_discovery_scan()
        scan_time = time.time() - start_time
        
        stats = self.registry.get_device_stats()
        stats["scan_time"] = scan_time
        
        logger.info(f"Forced discovery completed in {scan_time:.2f}s: {stats}")
        
        return stats
        
    def add_target_ip(self, ip: str):
        """Add a specific IP to the target list"""
        try:
            ipaddress.ip_address(ip)  # Validate IP
            self.target_ips.add(ip)
            logger.info(f"Added target IP: {ip}")
        except ValueError:
            logger.error(f"Invalid IP address: {ip}")
            
    def remove_target_ip(self, ip: str):
        """Remove an IP from the target list"""
        if ip in self.target_ips:
            self.target_ips.remove(ip)
            logger.info(f"Removed target IP: {ip}")
            
    def get_discovery_status(self) -> Dict[str, Any]:
        """Get discovery service status with priority scanning info"""
        paired_devices_count = len(self.registry.get_paired_devices()) if hasattr(self.registry, 'get_paired_devices') else 0

        status = {
            "running": self.running,
            "target_ips": len(self.target_ips),
            "priority_scanning_enabled": self.config.enable_priority_scanning,
            "paired_devices_count": paired_devices_count,
            "priority_scan_count": self.priority_scan_count,
            "general_scan_count": self.general_scan_count,
            "discovery_intervals": {
                "paired_devices": self.config.paired_devices_scan_interval,
                "unpaired_discovery": self.config.unpaired_discovery_interval
            },
            "discovery_interval": self.config.discovery_interval,
            "discovery_timeout": self.config.discovery_timeout,
            **self.registry.get_device_stats()
        }