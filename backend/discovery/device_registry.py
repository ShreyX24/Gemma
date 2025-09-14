# -*- coding: utf-8 -*-
"""
Device registry for tracking SUT devices and their states
"""

import logging
import time
import json
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta
from enum import Enum

try:
    from ..core.events import event_bus, EventType
except ImportError:
    # Fallback for direct execution
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from core.events import event_bus, EventType

logger = logging.getLogger(__name__)


class SUTStatus(Enum):
    """SUT status enumeration"""
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class SUTDevice:
    """SUT device information with pairing support"""
    ip: str
    port: int
    unique_id: str
    hostname: str = ""
    status: SUTStatus = SUTStatus.UNKNOWN
    capabilities: List[str] = field(default_factory=list)
    last_seen: datetime = field(default_factory=datetime.now)
    first_discovered: datetime = field(default_factory=datetime.now)
    current_task: Optional[str] = None
    error_count: int = 0
    total_pings: int = 0
    successful_pings: int = 0

    # Pairing mode fields
    is_paired: bool = False
    paired_at: Optional[datetime] = None
    paired_by: str = "system"  # Who initiated the pairing
    pair_priority: int = 1     # Priority for paired device scanning (1=highest)
    
    @property
    def success_rate(self) -> float:
        """Calculate ping success rate"""
        if self.total_pings == 0:
            return 0.0
        return self.successful_pings / self.total_pings
        
    @property
    def is_online(self) -> bool:
        """Check if device is considered online"""
        return self.status == SUTStatus.ONLINE
        
    @property
    def age_seconds(self) -> int:
        """Get age of device discovery in seconds"""
        return int((datetime.now() - self.first_discovered).total_seconds())
        
    @property
    def last_seen_seconds(self) -> int:
        """Get seconds since last seen"""
        return int((datetime.now() - self.last_seen).total_seconds())

    # Pairing mode methods
    def pair_device(self, paired_by: str = "user") -> None:
        """Pair this device for priority scanning"""
        self.is_paired = True
        self.paired_at = datetime.now()
        self.paired_by = paired_by
        self.pair_priority = 1  # Set to highest priority

    def unpair_device(self) -> None:
        """Unpair this device"""
        self.is_paired = False
        self.paired_at = None
        self.paired_by = "system"
        self.pair_priority = 1

    @property
    def is_paired_device(self) -> bool:
        """Check if this device is paired"""
        return self.is_paired

    @property
    def pairing_age_seconds(self) -> int:
        """Get seconds since device was paired"""
        if not self.is_paired or not self.paired_at:
            return 0
        return int((datetime.now() - self.paired_at).total_seconds())


class DevicePersistence:
    """Handles persistence of paired SUT devices to JSON file"""

    def __init__(self, persistence_file: str = "paired_devices.json"):
        self.persistence_file = persistence_file
        logger.info(f"DevicePersistence initialized with file: {self.persistence_file}")

    def save_paired_devices(self, devices: Dict[str, SUTDevice]) -> bool:
        """Save paired devices to JSON file"""
        try:
            paired_devices = {
                device_id: device for device_id, device in devices.items()
                if device.is_paired
            }

            if not paired_devices:
                logger.info("No paired devices to save")
                return True

            # Convert devices to serializable format
            serializable_data = {
                "version": "1.0",
                "saved_at": datetime.now().isoformat(),
                "paired_devices": {}
            }

            for device_id, device in paired_devices.items():
                device_dict = asdict(device)
                # Convert datetime objects to ISO strings
                device_dict['last_seen'] = device.last_seen.isoformat() if device.last_seen else None
                device_dict['first_discovered'] = device.first_discovered.isoformat() if device.first_discovered else None
                device_dict['paired_at'] = device.paired_at.isoformat() if device.paired_at else None
                device_dict['status'] = device.status.value  # Convert enum to string

                serializable_data["paired_devices"][device_id] = device_dict

            with open(self.persistence_file, 'w') as f:
                json.dump(serializable_data, f, indent=2)

            logger.info(f"Saved {len(paired_devices)} paired devices to {self.persistence_file}")
            return True

        except Exception as e:
            logger.error(f"Error saving paired devices: {str(e)}")
            return False

    def load_paired_devices(self) -> Dict[str, SUTDevice]:
        """Load paired devices from JSON file"""
        if not os.path.exists(self.persistence_file):
            logger.info(f"Paired devices file not found: {self.persistence_file}")
            return {}

        try:
            with open(self.persistence_file, 'r') as f:
                data = json.load(f)

            paired_devices = {}
            devices_data = data.get("paired_devices", {})

            for device_id, device_dict in devices_data.items():
                # Convert ISO strings back to datetime objects
                if device_dict.get('last_seen'):
                    device_dict['last_seen'] = datetime.fromisoformat(device_dict['last_seen'])
                if device_dict.get('first_discovered'):
                    device_dict['first_discovered'] = datetime.fromisoformat(device_dict['first_discovered'])
                if device_dict.get('paired_at'):
                    device_dict['paired_at'] = datetime.fromisoformat(device_dict['paired_at'])

                # Convert status string back to enum
                if 'status' in device_dict:
                    device_dict['status'] = SUTStatus(device_dict['status'])

                # Create SUTDevice from dict
                device = SUTDevice(**device_dict)
                paired_devices[device_id] = device

            logger.info(f"Loaded {len(paired_devices)} paired devices from {self.persistence_file}")
            return paired_devices

        except Exception as e:
            logger.error(f"Error loading paired devices: {str(e)}")
            return {}


class DeviceRegistry:
    """Registry for managing SUT devices"""
    
    def __init__(self, offline_timeout: int = 30, persistence_file: str = "paired_devices.json"):
        self.devices: Dict[str, SUTDevice] = {}  # Key: unique_id
        self.ip_to_id_mapping: Dict[str, str] = {}  # Key: ip, Value: unique_id
        self.offline_timeout = offline_timeout  # Seconds to consider device offline
        self._lock = None  # Will be set by controller

        # Initialize persistence
        self.persistence = DevicePersistence(persistence_file)
        self.load_paired_devices_on_startup()
        
    def register_device(self, ip: str, port: int, unique_id: str, capabilities: List[str] = None, hostname: str = "") -> SUTDevice:
        """Register or update a SUT device"""
        capabilities = capabilities or []
        
        # Check if device already exists
        if unique_id in self.devices:
            device = self.devices[unique_id]
            old_status = device.status
            
            # Update existing device
            device.ip = ip  # IP might have changed
            device.port = port
            device.hostname = hostname
            device.capabilities = capabilities
            device.last_seen = datetime.now()
            device.successful_pings += 1
            device.total_pings += 1
            
            # Update status if it was offline
            if device.status == SUTStatus.OFFLINE:
                device.status = SUTStatus.ONLINE
                device.error_count = 0
                logger.info(f"SUT {unique_id} came back online at {ip}:{port}")
                event_bus.emit(EventType.SUT_ONLINE, {
                    "device_id": unique_id,
                    "ip": ip,
                    "port": port,
                    "hostname": hostname
                })
            elif old_status != device.status:
                event_bus.emit(EventType.SUT_STATUS_CHANGED, {
                    "device_id": unique_id,
                    "old_status": old_status.value,
                    "new_status": device.status.value,
                    "ip": ip,
                    "port": port
                })
        else:
            # Create new device
            device = SUTDevice(
                ip=ip,
                port=port,
                unique_id=unique_id,
                hostname=hostname,
                status=SUTStatus.ONLINE,
                capabilities=capabilities,
                successful_pings=1,
                total_pings=1
            )
            
            self.devices[unique_id] = device
            logger.info(f"New SUT discovered: {unique_id} at {ip}:{port} with hostname '{hostname}'")
            event_bus.emit(EventType.SUT_DISCOVERED, {
                "device_id": unique_id,
                "ip": ip,
                "port": port,
                "hostname": hostname,
                "capabilities": capabilities
            })
            
        # Update IP mapping
        self.ip_to_id_mapping[ip] = unique_id
        
        return device
        
    def update_device_ping_fail(self, unique_id: str):
        """Update device when ping fails"""
        if unique_id in self.devices:
            device = self.devices[unique_id]
            device.error_count += 1
            device.total_pings += 1
            
            # Mark as offline if too many failures or timeout
            if (device.error_count >= 3 or 
                (datetime.now() - device.last_seen).total_seconds() > self.offline_timeout):
                
                if device.status != SUTStatus.OFFLINE:
                    old_status = device.status
                    device.status = SUTStatus.OFFLINE
                    logger.warning(f"SUT {unique_id} marked as offline (errors: {device.error_count})")
                    event_bus.emit(EventType.SUT_OFFLINE, {
                        "device_id": unique_id,
                        "ip": device.ip,
                        "port": device.port,
                        "error_count": device.error_count
                    })
                    
    def get_device_by_id(self, unique_id: str) -> Optional[SUTDevice]:
        """Get device by unique ID"""
        return self.devices.get(unique_id)
        
    def get_device_by_ip(self, ip: str) -> Optional[SUTDevice]:
        """Get device by IP address"""
        unique_id = self.ip_to_id_mapping.get(ip)
        return self.devices.get(unique_id) if unique_id else None
        
    def get_online_devices(self) -> List[SUTDevice]:
        """Get all online devices"""
        return [device for device in self.devices.values() if device.status == SUTStatus.ONLINE]
        
    def get_all_devices(self) -> List[SUTDevice]:
        """Get all devices"""
        return list(self.devices.values())
        
    def set_device_busy(self, unique_id: str, task: str = None):
        """Mark device as busy"""
        if unique_id in self.devices:
            device = self.devices[unique_id]
            old_status = device.status
            device.status = SUTStatus.BUSY
            device.current_task = task
            
            if old_status != SUTStatus.BUSY:
                event_bus.emit(EventType.SUT_STATUS_CHANGED, {
                    "device_id": unique_id,
                    "old_status": old_status.value,
                    "new_status": SUTStatus.BUSY.value,
                    "task": task
                })
                
    def set_device_online(self, unique_id: str):
        """Mark device as online and available"""
        if unique_id in self.devices:
            device = self.devices[unique_id]
            old_status = device.status
            device.status = SUTStatus.ONLINE
            device.current_task = None
            
            if old_status != SUTStatus.ONLINE:
                event_bus.emit(EventType.SUT_STATUS_CHANGED, {
                    "device_id": unique_id,
                    "old_status": old_status.value,
                    "new_status": SUTStatus.ONLINE.value
                })
                
    def cleanup_stale_devices(self):
        """Remove devices that haven't been seen for a long time"""
        stale_threshold = timedelta(minutes=10)  # 10 minutes
        current_time = datetime.now()
        stale_devices = []
        
        for unique_id, device in self.devices.items():
            if current_time - device.last_seen > stale_threshold:
                stale_devices.append(unique_id)
                
        for unique_id in stale_devices:
            device = self.devices[unique_id]
            logger.info(f"Removing stale device: {unique_id} (last seen: {device.last_seen})")
            
            # Remove from IP mapping
            if device.ip in self.ip_to_id_mapping:
                del self.ip_to_id_mapping[device.ip]
                
            del self.devices[unique_id]
            
    def get_device_stats(self) -> Dict[str, any]:
        """Get registry statistics"""
        online_count = len(self.get_online_devices())
        total_count = len(self.devices)
        paired_count = len(self.get_paired_devices())

        return {
            "total_devices": total_count,
            "online_devices": online_count,
            "offline_devices": total_count - online_count,
            "paired_devices": paired_count,
            "discovery_rate": f"{online_count}/{total_count}" if total_count > 0 else "0/0"
        }

    # Pairing mode methods
    def pair_device(self, unique_id: str, paired_by: str = "user") -> bool:
        """Pair a device for priority scanning"""
        device = self.get_device_by_id(unique_id)
        if not device:
            logger.warning(f"Cannot pair device {unique_id}: device not found")
            return False

        device.pair_device(paired_by)
        logger.info(f"Device {unique_id} ({device.ip}) paired by {paired_by}")

        # Emit pairing event
        event_bus.emit(EventType.SUT_PAIRED, {
            "device_id": unique_id,
            "ip": device.ip,
            "port": device.port,
            "hostname": device.hostname,
            "paired_by": paired_by,
            "paired_at": device.paired_at.isoformat() if device.paired_at else None
        })

        # Save paired devices to persistence
        self.save_paired_devices()
        return True

    def unpair_device(self, unique_id: str) -> bool:
        """Unpair a device"""
        device = self.get_device_by_id(unique_id)
        if not device:
            logger.warning(f"Cannot unpair device {unique_id}: device not found")
            return False

        device.unpair_device()
        logger.info(f"Device {unique_id} ({device.ip}) unpaired")

        # Emit unpairing event
        event_bus.emit(EventType.SUT_UNPAIRED, {
            "device_id": unique_id,
            "ip": device.ip,
            "port": device.port,
            "hostname": device.hostname
        })

        # Save paired devices to persistence
        self.save_paired_devices()
        return True

    def get_paired_devices(self) -> List[SUTDevice]:
        """Get all paired devices"""
        return [device for device in self.devices.values() if device.is_paired]

    def get_paired_device_ips(self) -> Set[str]:
        """Get IPs of all paired devices for priority scanning"""
        return {device.ip for device in self.devices.values() if device.is_paired}

    # Persistence methods
    def load_paired_devices_on_startup(self) -> None:
        """Load paired devices from persistence file on startup"""
        logger.info("Loading paired devices from persistence...")
        paired_devices = self.persistence.load_paired_devices()

        for device_id, device in paired_devices.items():
            # Add to registry but mark as offline initially
            device.status = SUTStatus.OFFLINE
            self.devices[device_id] = device
            self.ip_to_id_mapping[device.ip] = device_id
            logger.info(f"Loaded paired device: {device.ip} ({device_id})")

        logger.info(f"Loaded {len(paired_devices)} paired devices from persistence")

    def save_paired_devices(self) -> bool:
        """Save current paired devices to persistence"""
        return self.persistence.save_paired_devices(self.devices)