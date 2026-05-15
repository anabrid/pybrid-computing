from abc import ABC, abstractmethod
from typing import Dict, List

from pybrid.redac.entities import Path


class SampleListener(ABC):
    """Base class for adapters that stream samples from a running computation.

    :meth:`receive` is called incrementally during the run as data arrives.
    :meth:`on_run_complete` is invoked once after all data has been delivered.
    """

    @abstractmethod
    async def receive(self, samples: Dict[Path, List[float]]) -> None:
        """Called with a batch of decoded samples during a run.

        Args:
            samples: Mapping from channel :class:`~pybrid.redac.entities.Path`
                to a list of float64 sample values for that channel.
        """

    async def on_run_complete(self) -> None:
        """Invoked once after all data for a run has been delivered.

        Default is a no-op.  Override to flush buffers or finalise state.
        """
