# A simple calculator module
import math
from typing import List

def add(a, b):
    # Deprecated: use sum() for lists
    # New implementation supports summing a list
    if isinstance(a, List):
        return sum(a)
    return a + b
