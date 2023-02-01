import asyncio
import traceback
from typing import Dict
from hedra.core.graphs.simple_context import SimpleContext
from hedra.core.graphs.stages.base.stage import Stage
from hedra.core.graphs.stages.types.stage_states import StageStates
from hedra.core.graphs.stages.types.stage_types import StageTypes
from hedra.core.graphs.transitions.exceptions import (
    StageExecutionError,
    StageTimeoutError
)
from hedra.logging import HedraLogger


async def analyze_transition(current_stage: Stage, next_stage: Stage):

    logger = HedraLogger()
    logger.initialize()

    if current_stage.state == StageStates.INITIALIZED:

        await logger.spinner.system.debug(f'{current_stage.metadata_string} - Executing transition from {current_stage.name} to {next_stage.name}')
        await logger.filesystem.aio['hedra.core'].debug(f'{current_stage.metadata_string} - Executing transition from {current_stage.name} to {next_stage.name}')
        
        current_stage.state = StageStates.ANALYZING

        raw_results = dict(current_stage.context.results)
        execute_stages = current_stage.context.stages.get(StageTypes.EXECUTE)
        submit_stages: Dict[str, Stage] = current_stage.context.stages.get(StageTypes.SUBMIT)
        paths = current_stage.context.paths

        valid_states = [
            StageStates.EXECUTED, 
            StageStates.CHECKPOINTED, 
            StageStates.TEARDOWN_COMPLETE
        ]

        results_to_calculate = {}
        stages = {}
        for stage_name in raw_results.keys():
            stage = execute_stages.get(stage_name)

            in_path = current_stage.name in paths.get(stage.name)
            if stage.state in valid_states and in_path:
                stage.state = StageStates.ANALYZING
                results_to_calculate[stage_name] = raw_results.get(stage_name)
                stages[stage_name] = stage
        

        if len(results_to_calculate) > 0:

            current_stage.context['raw_results'] = results_to_calculate
            current_stage.context['target_stages'] = stages

            if current_stage.timeout:
                await asyncio.wait_for(current_stage.run(), timeout=current_stage.timeout)

            else:
                await current_stage.run()

        current_stage.state = StageStates.ANALYZED

        next_stage.context = SimpleContext()
        for known_key in current_stage.context.known_keys:
            next_stage.context[known_key] = current_stage.context[known_key]

        if len(results_to_calculate) > 0:
            next_stage.context.summaries.update(current_stage.context['summary_metrics'])
 
            for stage in submit_stages.values():
                if stage.name in paths.get(current_stage.name) and stage.state == StageStates.INITIALIZED:

                    if stage.context is None:
                        stage.context = SimpleContext()

                    if stage.context['summaries'] is None:
                        stage.context['summaries'] = {}

                    stage.context['summaries'].update(
                        current_stage.context['summary_metrics']
                    )

        next_stage.context['results_stages'].append(current_stage)
        next_stage.context['visited'].append(current_stage.name)

        await logger.spinner.system.debug(f'{current_stage.metadata_string} - Completed transition from {current_stage.name} to {next_stage.name}')
        await logger.filesystem.aio['hedra.core'].debug(f'{current_stage.metadata_string} - Completed transition from {current_stage.name} to {next_stage.name}')

    else:
        await logger.spinner.system.debug(f'{current_stage.metadata_string} - Skipping transition from {current_stage.name} to {next_stage.name}')
        await logger.filesystem.aio['hedra.core'].debug(f'{current_stage.metadata_string} - Skipping transition from {current_stage.name} to {next_stage.name}')
        

async def analyze_to_checkpoint_transition(current_stage: Stage, next_stage: Stage):

    try:

        await analyze_transition(current_stage, next_stage)

    except asyncio.TimeoutError:
        return StageTimeoutError(current_stage), StageTypes.ERROR
    
    except Exception as stage_runtime_error:
        return StageExecutionError(current_stage, next_stage, str(stage_runtime_error)), StageTypes.ERROR

    next_stage.data = dict(current_stage.context.summaries)
    next_stage.previous_stage = current_stage.name

    current_stage = None
    
    return None, StageTypes.CHECKPOINT


async def analyze_to_submit_transition(current_stage: Stage, next_stage: Stage):

    try:

        await analyze_transition(current_stage, next_stage)

    except asyncio.TimeoutError:
        return StageTimeoutError(current_stage), StageTypes.ERROR
    
    except Exception as stage_runtime_error:
        print(traceback.format_exc())
        return StageExecutionError(current_stage, next_stage, str(stage_runtime_error)), StageTypes.ERROR

    current_stage = None

    return None, StageTypes.SUBMIT


async def analyze_to_wait_transition(current_stage: Stage, next_stage: Stage):

    try:

        await analyze_transition(current_stage, next_stage)

    except asyncio.TimeoutError:
        return StageTimeoutError(current_stage), StageTypes.ERROR
    
    except Exception as stage_runtime_error:
        return StageExecutionError(current_stage, next_stage, str(stage_runtime_error)), StageTypes.ERROR

    current_stage = None

    return None, StageTypes.WAIT
