import uuid
from typing import Coroutine, List, Optional, Any, Dict
from hedra.core.graphs.hooks.types.hook_types import HookType


class Metadata:

    def __init__(
        self, 
        weight: int = 1, 
        order: int = 1, 
        env: str = None, 
        user: str = None, 
        path: str = None,
        tags: List[str] = [],
        pre: bool=False
    ) -> None:
        self.weight = weight
        self.order = order
        self.env = env
        self.user = user
        self.path = path
        self.tags = tags
        self.pre = pre

class Hook:

    def __init__(
        self, 
        name: str, 
        shortname: str,
        call: Coroutine, 
        stage: str = None,
        hook_type=HookType.ACTION,
        names: List[str] = [], 
        metadata: Metadata = Metadata(), 
        checks: List[Coroutine]=[],
        group: Optional[str]=None,
        notify: List[str] = [],
        listen: List[str] = []
    ) -> None:
        self.hook_id = str(uuid.uuid4())
        self.name = name
        self.shortname = shortname
        self.call = call
        self.stage = stage
        self.hook_type = hook_type
        self.names = list(set(names))
        self.config = metadata
        self.checks = checks
        self.session: Any = None
        self.action: Any = None
        self.group = group
        self.notify = notify
        self.listen = listen
        self.events: Dict[str, Coroutine] = {}
        self.stage_instance: Any = None
        
        self.notifiers: List[str] = []
        self.listeners: List[str] = []

