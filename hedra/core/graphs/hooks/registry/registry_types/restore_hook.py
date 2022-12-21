import aiofiles
from typing import Callable, Awaitable, Any
from hedra.core.graphs.simple_context import SimpleContext
from hedra.core.graphs.hooks.hook_types.hook_type import HookType
from .hook import Hook


class RestoreHook(Hook):

    def __init__(
        self, 
        name: str, 
        shortname: str, 
        call: Callable[..., Awaitable[Any]], 
        key: str=None,
        restore_filepath: str=None
    ) -> None:
        super().__init__(
            name, 
            shortname, 
            call, 
            hook_type=HookType.RESTORE
        )

        self.context_key = key
        self.restore_path = restore_filepath

    async def call(self, context: SimpleContext) -> None:
        async with aiofiles.open(self.restore_path, 'r') as restore_file:
            context[self.context_key] = await self._call(
                await restore_file.read()
            )
