__all__ = ["MATCHERS"]

from typing import Tuple, List
from .core import UserAgentMatcher, OSMatcher, DeviceMatcher

MATCHERS: Tuple[
    List[UserAgentMatcher],
    List[OSMatcher],
    List[DeviceMatcher],
]