from enum import Enum
from typing import Dict, Union
from .async_filesystem_logger import AsyncFilesystemLogger
from .sync_filesystem_logger import SyncFilesystemLogger    
from .async_logger import AsyncLogger
from .sync_logger import SyncLogger


class LoggerTypes(Enum):
    CONSOLE='console'
    DISTRIBUTED='distributed'
    FILESYSTEM='filesystem'
    DISTRIBUTED_FILESYSTEM='distributed_filesysem'
    HEDRA='hedra'


class LoggerTypesMap:
    
    def __init__(self) -> None:
        self.logger_types={
            'console': LoggerTypes.CONSOLE,
            'distributed': LoggerTypes.DISTRIBUTED,
            'filesystem': LoggerTypes.FILESYSTEM,
            'hedra': LoggerTypes.HEDRA,
            'distributed_filesystem': LoggerTypes.DISTRIBUTED_FILESYSTEM
        }

        self.async_loggers: Dict[LoggerTypes, Union[AsyncLogger, AsyncFilesystemLogger]] = {
            LoggerTypes.CONSOLE: AsyncLogger,
            LoggerTypes.DISTRIBUTED: AsyncLogger,
            LoggerTypes.HEDRA: AsyncLogger,
            LoggerTypes.FILESYSTEM: AsyncFilesystemLogger,
            LoggerTypes.DISTRIBUTED_FILESYSTEM: AsyncFilesystemLogger
        }

        self.sync_loggers: Dict[LoggerTypes, Union[SyncLogger, SyncFilesystemLogger]] = {
            LoggerTypes.CONSOLE: SyncLogger,
            LoggerTypes.DISTRIBUTED: SyncLogger,
            LoggerTypes.HEDRA: SyncLogger,
            LoggerTypes.FILESYSTEM: SyncFilesystemLogger,
            LoggerTypes.DISTRIBUTED_FILESYSTEM: SyncFilesystemLogger
        }

        self.logger_names = {
            logger_type: logger_name for logger_name, logger_type in self.logger_types.items()
        }

    @property
    def names(self):
        return list(self.logger_types.keys())

    @property
    def types(self):
        return list(self.logger_types.values())

    def get_name(self, logger_type: LoggerTypes):
        return self.logger_names.get(logger_type)

    def get_type(self, logger_name: str):
        return self.logger_types.get(logger_name)