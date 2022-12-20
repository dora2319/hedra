import os
import asyncio
import aiofiles
from typing import List, Union
from datetime import datetime
from hedra.core.graphs.events import Event
from hedra.core.graphs.hooks.registry.registry_types import (
    EventHook, 
    SaveHook,
    RestoreHook,
    ContextHook
)
from hedra.core.graphs.hooks.hook_types.internal import Internal
from hedra.core.graphs.hooks.hook_types.hook_type import HookType
from hedra.core.graphs.stages.types.stage_types import StageTypes
from .stage import Stage


class Checkpoint(Stage):
    stage_type=StageTypes.CHECKPOINT

    def __init__(self) -> None:
        super().__init__()
        self.previous_stage = None
        self.accepted_hook_types = [ 
            HookType.CONTEXT ,
            HookType.EVENT, 
            HookType.RESTORE,
            HookType.SAVE, 
        ]

        self.requires_shutdown = True

    @Internal()
    async def run(self):

        events: List[Union[EventHook, Event]] = [event for event in self.hooks[HookType.EVENT]]
        pre_events: List[EventHook] = [
            event for event in events if isinstance(event, EventHook) and event.pre
        ]
        
        if len(pre_events) > 0:
            pre_event_names = ", ".join([
                event.shortname for event in pre_events
            ])

            await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Executing PRE events - {pre_event_names}')
            await asyncio.wait([
                asyncio.create_task(event.call()) for event in pre_events
            ], timeout=self.stage_timeout)

        restore_hooks: List[RestoreHook] = self.hooks[HookType.RESTORE]
        if len(restore_hooks) > 0:
            await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Executing Save checkpoints for - {len(restore_hooks)} - items')

        for restore_hook in restore_hooks:
            async with aiofiles.open(restore_hook.restore_path, 'r') as restore_file:
                self.context[restore_hook.context_key] = await restore_hook.call(
                    await restore_file.read()
                )

        save_hooks: List[SaveHook] = self.hooks[HookType.SAVE]
        if len(save_hooks) > 0:
            await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Executing Save checkpoints for - {len(save_hooks)} - items')
        
        for save_hook in save_hooks:
            checkpoint_data = await save_hook.call(
                self.context.get(save_hook.context_key)
            )

            await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Executing checkpoint - {save_hook.name}')

            async with aiofiles.open(save_hook.save_path, 'w') as checkpoint_file:
                await checkpoint_file.write(checkpoint_data)

            await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Checkpoint - {save_hook.name} - complete')

            if self.context.get(save_hook.context_key):
                self.context[save_hook.context_key] = None
        
        post_events: List[EventHook] = [
            event for event in events if isinstance(event, EventHook) and event.pre is False
        ]

        if len(post_events) > 0:
            post_event_names = ", ".join([
                event.shortname for event in post_events
            ])

            await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Executing POST events - {post_event_names}')
            await asyncio.wait([
                asyncio.create_task(event.call()) for event in post_events
            ], timeout=self.stage_timeout)


        await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Completed checkpoints for - {len(save_hooks)} - items')

        context_hooks: List[ContextHook] = self.hooks[HookType.CONTEXT]
        for context_hook in context_hooks:
            self.context[context_hook.context_key] = await context_hook.call()
