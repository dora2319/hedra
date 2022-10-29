import functools
from hedra.plugins.types.common.plugin_hook import PluginHook
from hedra.plugins.types.common.types import PluginHooks
from hedra.plugins.types.common.registrar import plugin_registrar


@plugin_registrar(PluginHooks.ON_PROCESS_SHARED_STATS)
def process_shared():

    def wrapper(func) -> PluginHook:

        @functools.wraps(func)
        def decorator(*args, **kwargs):

            return func(*args, **kwargs)
                
        return decorator

    return wrapper