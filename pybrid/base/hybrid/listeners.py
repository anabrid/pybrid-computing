from abc import ABC, abstractmethod
from typing import Dict, List

from pybrid.redac.entities import Path

class SampleListener(ABC):
    """
    Base class for adapters to any Pybrid-based runner class which can be used
    to stream generated samples. The underlying streaming mechanism receives UDP
    packets from the device and forwards them as a dict of samples where the 
    keys are entity paths.
    """

    @abstractmethod
    async def receive(self, samples: Dict[Path, List[float]]):
        pass