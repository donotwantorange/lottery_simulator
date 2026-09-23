from collections.abc import Callable


CancelCheck = Callable[[], bool]
PhaseCallback = Callable[[str, int | None, int | None], None]
ProgressCallback = Callable[[int, int], None]


class SimulationCancelled(RuntimeError):
    pass


def check_cancelled(cancel_check: CancelCheck | None) -> None:
    if cancel_check is not None and cancel_check():
        raise SimulationCancelled("simulation cancelled")
