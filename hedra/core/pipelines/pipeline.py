
import asyncio
import enum
import networkx
from typing import Dict, List
from hedra.core.pipelines.transitions.exceptions.exceptions import IsolatedStageError
from hedra.core.pipelines.stages.stage import Stage
from hedra.core.pipelines.stages.types.stage_types import StageTypes
from .transitions import TransitionAssembler



class Pipeline:

    def __init__(self, stages: List[Stage]) -> None:
        
        self.graph = networkx.DiGraph()
        self.transitions_graph = []
        self._transitions = []

        self.stage_types = {
            subclass.stage_type: subclass for subclass in Stage.__subclasses__()
        }

        self.instances: Dict[StageTypes, List[Stage]] = {}
        for stage in self.stage_types.values():
            stage_instances = stage.__subclasses__()
            self.instances[stage.stage_type] = stage_instances

        self.stages: Dict[str, Stage] = {stage.__name__: stage for stage in stages}
        
        self.graph.add_nodes_from([
            (
                stage_name, 
                {"stage": stage}
            ) for stage_name, stage in self.stages.items()
        ])

        for stage in stages:
            for dependency in stage.dependencies:
                if self.graph.nodes.get(dependency.__name__):
                    self.graph.add_edge(dependency.__name__, stage.__name__)

        self.execution_order = [
            generation for generation in networkx.topological_generations(self.graph)
        ]

        self.runner = TransitionAssembler()

    def validate(self):

        self._prepend_stage(StageTypes.IDLE)

        if len(self.instances.get(StageTypes.ANALYZE)) < 1:
           self._append_stage(StageTypes.ANALYZE)

        if len(self.instances.get(StageTypes.CHECKPOINT)) < 1:
            self._append_stage(StageTypes.CHECKPOINT)

        self._append_stage(StageTypes.COMPLETE)

        self.transitions_graph = self.runner.build_transitions_graph(
            self.execution_order,
            self.stages
        )

        for isolate_stage_name in networkx.isolates(self.graph):
            raise IsolatedStageError(
                self.stages.get(isolate_stage_name)
            )

        for transition_group in self.transitions_graph:
            
            transtions = []
            
            for transition_sequence in list(transition_group.values()):
                transtions.extend(transition_sequence)

            self._transitions.append(transtions)

    async def run(self):

        for transition_group in self._transitions:
            
            if len(transition_group) == 1:
                await transition_group[0].transition(
                    transition_group[0].from_stage,
                    transition_group[0].to_stage
                )

            else:
                await asyncio.gather(*[
                    transition.transition(
                        transition.from_stage, 
                        transition.to_stage
                    ) for transition in transition_group
                ])

    def _append_stage(self, stage_type: StageTypes):

        appended_stage = self.stage_types.get(stage_type)
        last_cut = self.execution_order[-1]

        appended_stage.dependencies = list()

        for stage_name in last_cut:
            stage = self.stages.get(stage_name)

            appended_stage.dependencies.append(stage)

        self.graph.add_node(appended_stage.__name__, stage=appended_stage)

        for stage_name in last_cut:
            self.graph.add_edge(stage_name, appended_stage.__name__)

        self.execution_order = [
            generation for generation in networkx.topological_generations(self.graph)
        ]

        self.stages[appended_stage.__name__] = appended_stage
        self.instances[appended_stage.stage_type].append(appended_stage)

    def _prepend_stage(self, stage_type: StageTypes):
        prepended_stage = self.stage_types.get(stage_type)
        first_cut = self.execution_order[0]

        prepended_stage.dependencies = list()

        for stage_name in first_cut:
            stage = self.stages.get(stage_name)

            stage.dependencies.append(prepended_stage)

        self.graph.add_node(prepended_stage.__name__, stage=prepended_stage)

        for stage_name in first_cut:
            self.graph.add_edge(prepended_stage.__name__, stage_name)

        self.execution_order = [
            generation for generation in networkx.topological_generations(self.graph)
        ]

        self.stages[prepended_stage.__name__] = prepended_stage
        self.instances[prepended_stage.stage_type].append(stage_type)