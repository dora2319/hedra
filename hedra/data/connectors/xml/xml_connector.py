import asyncio
import functools
import collections
import collections.abc
import uuid
import psutil
import signal
import os
import pathlib
from typing import (
    List, 
    TextIO, 
    Dict, 
    Union,
    Any
)
from concurrent.futures import ThreadPoolExecutor
from hedra.logging import HedraLogger
from hedra.core.engines.client.config import Config
from hedra.core.hooks.types.action.hook import ActionHook
from hedra.data.connectors.common.connector_type import ConnectorType
from hedra.data.parsers.parser import Parser
from .xml_connector_config import XMLConnectorConfig

try:
    import xmltodict
except Exception:
    xmltodict = object

collections.Iterable = collections.abc.Iterable


def handle_loop_stop(
    signame, 
    executor: ThreadPoolExecutor, 
    loop: asyncio.AbstractEventLoop, 
    events_file: TextIO
): 
    try:
        events_file.close()
        executor.shutdown(wait=False, cancel_futures=True) 
        loop.stop()
    except Exception:
        pass


class XMLConnector:
    connector_type=ConnectorType.XML
    
    def __init__(
        self, 
        config: XMLConnectorConfig,
        stage: str,
        parser_config: Config,
    ) -> None:
        self._executor = ThreadPoolExecutor(max_workers=psutil.cpu_count(logical=False))
        self._loop: asyncio.AbstractEventLoop = None
        self.stage = stage
        self.parser_config = parser_config

        self.session_uuid = str(uuid.uuid4())
        self.metadata_string: str = None
        self.logger = HedraLogger()
        self.logger.initialize()

        self.filepath: str = config.filepath

        self.xml_file: Union[TextIO, None] = None

        self.file_mode = config.file_mode
        self.parser = Parser()

    async def connect(self):
        self._loop = asyncio._get_running_loop()
        await self.logger.filesystem.aio['hedra.reporting'].debug(f'{self.metadata_string} - Setting filepaths')
        
        if self.filepath[:2] == '~/':
            user_directory = pathlib.Path.home()
            self.filepath = os.path.join(
                user_directory,
                self.filepath[2:]
            )

        self.filepath = await self._loop.run_in_executor(
            self._executor,
            functools.partial(
                os.path.abspath,
                self.filepath
            )
        )
        
        if self.xml_file is None:
            self.xml_file = await self._loop.run_in_executor(
                self._executor,
                functools.partial(
                    open,
                    self.filepath,
                    self.file_mode
                )
            )

            for signame in ('SIGINT', 'SIGTERM', 'SIG_IGN'):
                self._loop.add_signal_handler(
                    getattr(signal, signame),
                    lambda signame=signame: handle_loop_stop(
                        signame,
                        self._executor,
                        self._loop,
                        self.xml_file
                    )
                )

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Opening from file - {self.filepath}')

    async def load_actions(
        self,
        options: Dict[str, Any]={}
    ) -> List[ActionHook]:
        
        actions: List[Dict[str, Any]] = await self.load_data()

        return await asyncio.gather(*[
            self.parser.parse(
                action_data,
                self.stage,
                self.parser_config,
                options
            ) for action_data in actions
        ])
    
    async def load_data(
        self, 
        options: Dict[str, Any]={}
    ) -> Any:
        
        file_data = await self._loop.run_in_executor(
            self._executor,
            self.xml_file.read
        )

        return await self._loop.run_in_executor(
            self._executor,
            functools.partial(
                xmltodict.parse,
                file_data
            )
        )
    
    async def close(self):

        await self._loop.run_in_executor(
            self._executor,
            self.xml_file.close
        )

        self._executor.shutdown(cancel_futures=True)     