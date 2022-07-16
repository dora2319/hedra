import inspect
import psutil
import functools
from typing import Dict, List, Union
from hedra.test.hooks.hook import Hook
from hedra.test.hooks.types import HookType
from hedra.core.engines.types.common.hooks import Hooks
from hedra.test.config import Config
from hedra.test.client import Client
from hedra.core.engines.types.common.request import Request
from hedra.core.engines.types.playwright.command import Command
from hedra.test.registry.registrar import registar
from hedra.core.pipelines.stages.types.stage_types import StageTypes
from .stage import Stage


class Setup(Stage):
    stage_type=StageTypes.SETUP
    log_level='info'
    persona_type='simple'
    total_time='00:01:00'
    batch_size=1000
    batch_interval=1
    batch_interval_range=None
    optimize=0
    optimize_iter_duration=10
    optimizer_type='shg'
    gradient=0.1
    pool_size=psutil.cpu_count(logical=False)
    no_run_visuals=False
    connect_timeout=5
    request_timeout=60
    options={
        
    }
    config: Config = None
    client: Client = None
    
    def __init__(self) -> None:
        super().__init__()
        self.actions = []
        self.hooks: Dict[str, List[Hook]] = {}

        for hook_type in HookType:
            self.hooks[hook_type] = []

    async def register_actions(self):
        methods = inspect.getmembers(self, predicate=inspect.ismethod) 

        for _, method in methods:

            method_name = method.__name__

            hook: Hook = registar.all.get(method_name)

            if hook and self.hooks.get(hook.hook_type) is None:
                self.hooks[hook.hook_type] = [hook]
            
            elif hook:
                self.hooks[hook.hook_type].append(hook)

        for hook in self.hooks.get(HookType.ACTION):
            
            selected_client = self.client[self.config.engine_type]
            selected_client.next_name = hook.name
            self.client[self.config.engine_type] = selected_client
            await hook.call(self)

            self.client.session.context.history.add_row(
                hook.name,
                batch_size=self.config.batch_size
            )

            parsed_action = self.client.session.registered.get(hook.name)

            parsed_action.hooks = Hooks(
                before=self.get_hook(parsed_action, HookType.BEFORE),
                after=self.get_hook(parsed_action, HookType.AFTER)
            )

            hook.session = self.client.session
            hook.action = parsed_action
            

            self.actions.append(hook)

    def get_hook(self, action: Union[Request,Command], hook_type: str):
        for hook in self.hooks[hook_type]:
            if action.name in hook.names:
                return functools.partial(hook.call, self)


    async def setup(self):
        for setup_hook in self.hooks.get(HookType.SETUP):
            await setup_hook()