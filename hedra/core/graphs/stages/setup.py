import asyncio
import psutil
from typing_extensions import TypeVarTuple, Unpack
from typing import Dict, Generic
from hedra.core.graphs.hooks.types.hook import Hook
from hedra.core.graphs.hooks.types.hook_types import HookType
from hedra.core.graphs.hooks.types.internal import Internal
from hedra.core.engines.client.client import Client
from hedra.core.engines.client.config import Config
from hedra.core.graphs.stages.types.stage_types import StageTypes
from hedra.core.personas.types import PersonaTypesMap
from hedra.plugins.types.engine.engine_plugin import EnginePlugin
from hedra.plugins.types.plugin_types import PluginType
from .execute import Execute
from .stage import Stage
from .exceptions import (
    HookSetupError
)

T = TypeVarTuple('T')


class SetupCall:

    def __init__(self, hook: Hook) -> None:
        self.hook = hook
        self.exception = None
        self.action_store = None

    async def setup(self):
        try:
            await self.hook.call()

        except Exception as setup_exception:
            self.exception = setup_exception
            self.action_store.waiter.set_result(None)



class Setup(Stage, Generic[Unpack[T]]):
    stage_type=StageTypes.SETUP
    log_level='info'
    persona_type='default'
    total_time='1m'
    batch_size=1000
    batch_interval=0
    action_interval=0
    batch_gradient=0.1
    cpus=int(psutil.cpu_count(logical=False))
    no_run_visuals=False
    graceful_stop=1
    connect_timeout=10
    request_timeout=60
    reset_connections=False
    apply_to_stages=[]
    
    def __init__(self) -> None:
        super().__init__()
        self.generation_setup_candidates = 0
        self.stages: Dict[str, Execute] = {}
        self.accepted_hook_types = [ HookType.SETUP ]
        self.persona_types = PersonaTypesMap()

    @Internal
    async def run(self):
        
        await asyncio.gather(*[hook.call() for hook in self.hooks.get(HookType.SETUP)])
        execute_stage_id = 1

        stages = dict(self.stages)

        execute_stage_names = ', '.join(list(stages.keys()))

        await self.logger.console.aio.append_progress_message(f'Setting up - {execute_stage_names}')
        
        for execute_stage_name, execute_stage in stages.items():

            execute_stage.execution_stage_id = execute_stage_id
            execute_stage.execute_setup_stage = self.name

            execute_stage_id += 1

            persona_plugins = self.plugins_by_type.get(PluginType.PERSONA)
            for plugin_name in persona_plugins.keys():
                self.persona_types.types[plugin_name] = plugin_name

            config = Config(
                log_level=self.log_level,
                persona_type=self.persona_types[self.persona_type],
                total_time=self.total_time,
                batch_size=self.batch_size,
                batch_interval=self.batch_interval,
                action_interval=self.action_interval,
                batch_gradient=self.batch_gradient,
                cpus=self.cpus,
                no_run_visuals=self.no_run_visuals,
                connect_timeout=self.connect_timeout,
                request_timeout=self.request_timeout,
                graceful_stop=self.graceful_stop,
                reset_connections=self.reset_connections

            )
   
            client = Client()
            engine_plugins: Dict[str, EnginePlugin] = self.plugins_by_type.get(PluginType.ENGINE)

            for plugin_name, plugin in engine_plugins.items():
                client.plugin[plugin_name] = plugin(config)
                plugin.name = plugin_name
                self.plugins_by_type[plugin_name] = plugin

            execute_stage.client = client
            execute_stage.client._config = config

            for hook in execute_stage.hooks.get(HookType.ACTION, []):

                execute_stage.client.next_name = hook.name
                execute_stage.client.intercept = True
                
                execute_stage.client.actions.set_waiter(execute_stage.name)

                setup_call = SetupCall(hook)
                setup_call.action_store = execute_stage.client.actions

                task = asyncio.create_task(setup_call.setup())

                await execute_stage.client.actions.wait_for_ready(setup_call)   

                try:
                    if setup_call.exception:
                        raise HookSetupError(hook, HookType.ACTION, str(setup_call.exception))

                    task.cancel()
                    if task.cancelled() is False:
                        await asyncio.wait_for(task, timeout=0.1)

                except HookSetupError as hook_setup_exception:
                    raise hook_setup_exception

                except asyncio.InvalidStateError:
                    pass

                except asyncio.CancelledError:
                    pass

                except asyncio.TimeoutError:
                    pass
                     
                action, session = execute_stage.client.actions.get(
                    execute_stage.name,
                    hook.name
                )

                action.hooks.before = self.get_hook(execute_stage, hook.shortname, HookType.BEFORE)
                action.hooks.after = self.get_hook(execute_stage, hook.shortname, HookType.AFTER)
                action.hooks.checks = self.get_checks(execute_stage, hook.shortname)

                hook.session = session
                hook.action = action    

            for hook in execute_stage.hooks.get(HookType.TASK, []):
                execute_stage.client.next_name = hook.name
                task, session = execute_stage.client.task.call(
                    hook.call,
                    env=hook.config.env,
                    user=hook.config.user,
                    tags=hook.config.tags
                )

                task.hooks.checks = self.get_checks(execute_stage, hook.shortname) 

                hook.session = session
                hook.action = task  

            execute_stage.client.intercept = False
            for setup_hook in execute_stage.hooks.get(HookType.SETUP):
                await setup_hook.call()

            self.stages[execute_stage_name] = execute_stage

        await self.logger.console.aio.set_default_message(f'Setup for - {execute_stage_names} - complete')

        return self.stages

    def get_hook(self, execute_stage: Execute, shortname: str, hook_type: str):
        for hook in execute_stage.hooks[hook_type]:
            if shortname in hook.names:
                return hook.call

    def get_checks(self, execute_stage: Execute, shortname: str):

        checks = []

        for hook in execute_stage.hooks[HookType.CHECK]:
            if shortname in hook.names:
                checks.append(hook.call)

        return checks

    async def setup(self):
        for setup_hook in self.hooks.get(HookType.SETUP):
            await setup_hook()