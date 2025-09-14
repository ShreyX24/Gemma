# -*- coding: utf-8 -*-
"""
UI element definitions and data structures.
"""

from dataclasses import dataclass

@dataclass
class BoundingBox:
    """Represents a UI element's bounding box."""
    x: int
    y: int
    width: int
    height: int
    confidence: float
    element_type: str
    element_text: str = ""