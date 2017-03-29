import asyncio
import reprlib
import signal
from typing import Any, IO, Sequence, Set, Tuple, Union
from .utils.compat import DummyContext
from .utils.logging import setup_logging
from .utils.services import Service
from .types import AppT, ServiceT, SensorT

try:  # pragma: no cover
    from setproctitle import setproctitle
except ImportError:  # pragma: no cover
    def setproctitle(title: str) -> None: ...  # noqa

__all__ = ['Worker']

PSIDENT = '[Faust:Worker]'


class _TupleAsListRepr(reprlib.Repr):

    def repr_tuple(self, x: Tuple, level: int) -> str:
        return self.repr_list(x, level)
_repr = _TupleAsListRepr().repr  # noqa: E305


class Worker(Service):
    debug: bool
    sensors: Set[SensorT]
    services: Sequence[ServiceT]
    loglevel: Union[str, int]
    logfile: Union[str, IO]

    def __init__(self, *services: ServiceT,
                 sensors: Sequence[SensorT] = None,
                 debug: bool = False,
                 loglevel: Union[str, int] = None,
                 logfile: Union[str, IO] = None,
                 logformat: str = None,
                 loop: asyncio.AbstractEventLoop = None) -> None:
        self.services = services
        self.sensors = set(sensors or [])
        self.debug = debug
        self.loglevel = loglevel
        self.logfile = logfile
        self.logformat = logformat
        super().__init__(loop=loop)

    def install_signal_handlers(self):
        self.loop.add_signal_handler(signal.SIGINT, self._on_sigint)

    def _on_sigint(self):
        print('-INT- -INT- -INT- -INT- -INT- -INT-')
        try:
            self.loop.run_until_complete(
                asyncio.ensure_future(self._stop_on_signal(), loop=self.loop))
        except RuntimeError:
            # Says loop is already running, but somehow this removes
            # the "Task exception was never retrieved" warning.
            pass

    async def _stop_on_signal(self):
        await self.stop()
        self.loop.close()
        raise SystemExit()

    def execute_from_commandline(self, *coroutines):
        self.loop.run_until_complete(
            self._execute_from_commandline(*coroutines))

    async def _execute_from_commandline(self, *coroutines) -> None:
        setproctitle('[Faust:Worker] init')
        with self._monitor():
            self.install_signal_handlers()
            await asyncio.gather(
                *[asyncio.ensure_future(coro, loop=self.loop)
                  for coro in coroutines],
                loop=self.loop)
            await self.start()
            await asyncio.ensure_future(self._stats(), loop=self.loop)
            await self.wait_until_stopped()

    async def _stats(self) -> None:
        while not self.should_stop:
            await asyncio.sleep(5)
            if len(self.services) == 1:
                print(self.services[0])
            else:
                print(_repr(self.services))

    def _monitor(self) -> Any:
        if self.debug:
            try:
                import aiomonitor
            except ImportError:
                pass
            else:
                return aiomonitor.start_monitor(loop=self.loop)
        return DummyContext()

    async def start(self) -> None:
        if not self.restart_count:
            await self.on_first_start()
        await super().start()

    async def on_first_start(self) -> None:
        if self.loglevel:
            setup_logging(
                loglevel=self.loglevel,
                logfile=self.logfile,
                logformat=self.logformat,
            )
        for sensor in self.sensors:
            await sensor.maybe_start()

    async def on_start(self) -> None:
        self._setproctitle('starting')
        for service in self.services:
            for sensor in self.sensors:
                if isinstance(service, AppT):
                    service.add_sensor(sensor)
            self._setproctitle('running')
            await service.maybe_start()

    async def on_stop(self) -> None:
        self._setproctitle('stopping')
        for service in reversed(self.services):
            await service.stop()
        for sensor in self.sensors:
            await sensor.stop()

    def _repr_info(self) -> str:
        return _repr(self.services)

    def _setproctitle(self, info: str) -> None:
        setproctitle('{} {}'.format(PSIDENT, info))
