import dill
import time
import statistics
import psutil
import asyncio
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Union, List, Dict, Union, Any, Tuple
from hedra.plugins.types.plugin_types import PluginType
from hedra.reporting.events import EventsGroup
from hedra.reporting.metric import MetricsSet
from hedra.core.graphs.hooks.hook_types.context import context
from hedra.core.graphs.hooks.hook_types.event import event  
from hedra.core.engines.types.common.results_set import ResultsSet
from hedra.core.graphs.hooks.hook_types.internal import Internal
from hedra.core.graphs.hooks.hook_types.hook_type import HookType
from hedra.core.graphs.stages.types.stage_types import StageTypes
from hedra.reporting.events import results_types
from hedra.reporting.events.types import (
    HTTPEvent, 
    HTTP2Event, 
    GraphQLEvent, 
    GRPCEvent, 
    WebsocketEvent, 
    PlaywrightEvent,
    UDPEvent
)
from hedra.core.graphs.stages.base.stage import Stage
from .parallel import process_results_batch


Events = Union[HTTPEvent, HTTP2Event, GraphQLEvent, GRPCEvent, WebsocketEvent, PlaywrightEvent, UDPEvent]

RawResultsSet = Dict[str,  List[Tuple[str, Any]]]

RawResultsPairs = List[Tuple[Dict[str,  List[Tuple[str, Any]]]]]

ProcessedResults = Dict[str, Union[Dict[str, Union[int, float, int]], int]]

ProcessedResultsSet = List[Dict[str, Union[Dict[str, Union[int, float, int]], int]]]

CustoMetricsSet = Dict[str, Dict[str, Dict[str, Union[int, float, Any]]]]

EventsSet = Dict[str, Dict[str, EventsGroup]]


class Analyze(Stage):
    stage_type=StageTypes.ANALYZE
    is_parallel = False
    handler = None

    def __init__(self) -> None:
        super().__init__()

        self.accepted_hook_types = [ 
            HookType.CONDITION,
            HookType.CONTEXT,
            HookType.CONDITION,
            HookType.EVENT, 
            HookType.METRIC,
            HookType.TRANSFORM, 
        ]

        self.requires_shutdown = True
        self.allow_parallel = True
        self.analysis_execution_time = 0
        self.analysis_execution_time_start = 0
        self._executor = ThreadPoolExecutor(max_workers=psutil.cpu_count())

    @Internal()
    async def run(self):  
        await self.setup_events()
        await self.dispatcher.dispatch_events()

    @context()
    async def initialize_raw_results(
        self,
        raw_results: RawResultsSet={}
    ):
        await self.logger.filesystem.aio.create_logfile('hedra.reporting.log')
        self.logger.filesystem.create_filelogger('hedra.reporting.log')
        
        await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Starting results analysis')

        self.analysis_execution_time_start = time.monotonic()

        engine_plugins = self.plugins_by_type.get(PluginType.ENGINE)
        for plugin_name, plugin in engine_plugins.items():
            results_types[plugin_name] = plugin.event

            await self.logger.filesystem.aio['hedra.core'].debug(f'{self.metadata_string} - Generated custom Event - {plugin.event.type} - for Reporter plugin - {plugin_name}')

        all_results = list(raw_results.items())

        self.context.ignore_serialization_filters = [
            'all_results',
            'raw_results',
            'target_stages'
        ]
        
        return {
            'raw_results': raw_results,
            'all_results': all_results
        }

    @event('initialize_raw_results')
    async def partition_results_batches(
        self,
        raw_results: RawResultsSet={},
        all_results: List[RawResultsPairs]=[]
    ):
        batches = self.executor.partion_stage_batches(all_results)
        total_group_results = 0

        elapsed_times = []
        for stage_name, _, _ in batches:
            stage_results: ResultsSet = raw_results.get(stage_name)
            total_group_results += stage_results.total_results
            elapsed_times.append(
                stage_results.total_elapsed
            )

        await self.logger.filesystem.aio['hedra.core'].debug(f'{self.metadata_string} - Paritioned {len(batches)} batches of results')

        return {
            'batches': batches,
            'total_group_results': total_group_results,
            'elapsed_times': elapsed_times
        }
    
    @event('partition_results_batches')
    async def get_custom_metric_hooks(self):

        metric_hook_names: List[str] = [hook.name for hook in self.hooks[HookType.METRIC]]
        
        for metric_hook_name in metric_hook_names:
            await self.logger.filesystem.aio['hedra.core'].debug(f'{self.metadata_string} - Loaded custom Metric hook - {metric_hook_name}')

        return {
            'metric_hook_names': metric_hook_names,
            'custom_metric_hooks':  self.hooks[HookType.METRIC]
        }

    @event('get_custom_metric_hooks')
    async def create_stage_batches(
        self,
        raw_results: RawResultsSet=[],
        batches: List[Tuple[str, Any, int]]=[],
    ):

        stage_total_times = {}
        stage_batch_sizes = {}

        for stage_name, _, assigned_workers_count in batches:
            
            stage_batches: List[List[Any]] = []

            stage_results = raw_results.get(stage_name)
            results = stage_results.results
            stage_total_time = stage_results.total_elapsed
            
            stage_total_times[stage_name] = stage_total_time

            results_count = len(results)
            
            batch_size = int(results_count/assigned_workers_count)
            
            for worker_idx in range(assigned_workers_count):

                batch_marker = worker_idx * batch_size

                stage_batches.append(
                    results[batch_marker:batch_marker + batch_size]
                )

            if results_count%assigned_workers_count > 0:
                stage_batches[assigned_workers_count-1].extend(
                    results[assigned_workers_count * batch_size:]
                )

            stage_batch_sizes[stage_name] = stage_batches

        return {
            'target_stages': {},
            'stage_total_times': stage_total_times,
            'stage_batch_sizes': stage_batch_sizes
        }

    @context('create_stage_batches')
    async def assign_stage_batches(
        self,
        batches: List[Tuple[str, Any, int]]=[],
        stage_batch_sizes: Dict[str, List[List[Any]]]=[],
        metric_hook_names: List[str]=[]
    ):
        loop = asyncio.get_event_loop()

        stage_configs = []
        serializable_context = self.context.as_serializable()

        for stage_name, _, assigned_workers_count in batches:

            stage_config_batch = await asyncio.gather(*[
                loop.run_in_executor(
                    self._executor,
                    dill.dumps,
                    {
                        'graph_name': self.graph_name,
                        'graph_path': self.graph_path,
                        'graph_id': self.graph_id,
                        'source_stage_name': self.name,
                        'source_stage_context': {
                            context_key: context_value for context_key, context_value in serializable_context
                        },
                        'source_stage_id': self.stage_id,
                        'analyze_stage_name': stage_name,
                        'analyze_stage_metric_hooks': list(metric_hook_names),
                        'analyze_stage_batched_results': batch
                    }
                ) for batch in stage_batch_sizes[stage_name]
            ])
            

            stage_configs.append((
                stage_name,
                assigned_workers_count,
                stage_config_batch
            ))
            

            await self.logger.filesystem.aio['hedra.core'].debug(f'{self.metadata_string} - Assigned {assigned_workers_count} to process results from stage - {stage_name}')

        stages_count = len(stage_configs)

        return {
            'stage_configs': stage_configs,
            'stages_count': stages_count
        }

    @event('assign_stage_batches')
    async def analyze_stage_batches(
        self,
        stages_count: int=0,
        elapsed_times: List[float]=[],
        total_group_results: int=0,
        stage_configs: List[Tuple[str, Any, int]]=[],
    ):

        await self.logger.spinner.append_message(
            f'Calculating results for - {stages_count} - stages'
        )

        await self.logger.filesystem.aio['hedra.core'].debug(f'{self.metadata_string} - Processing results or - {stages_count} - stages')
        
        median_execution_time = round(statistics.median(elapsed_times))
        await self.logger.spinner.append_message(f'Calculating stats for - {total_group_results} - actions executed over a median stage execution time of {median_execution_time} seconds')

        await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Calculating stats for - {total_group_results} - actions over a median stage execution time of {median_execution_time} seconds')

        stage_batches = await self.executor.execute_batches(
            stage_configs,
            process_results_batch
        )

        await self.logger.filesystem.aio['hedra.core'].debug(f'{self.metadata_string} - Completed parital results aggregation for - {stages_count} - stages')

        return {
            'stage_batches': stage_batches
        }

    @event('analyze_stage_batches')
    async def reduce_stage_contexts(
        self,
        stages_count: int=0,
        stage_batches: List[Tuple[str, List[Any]]]=[]
    ):

        self.logger.spinner.set_message_at(2, f'Converting aggregate results to metrics for - {stages_count} - stages.')

        await self.logger.filesystem.aio['hedra.core'].debug(f'{self.metadata_string} - Starting stage results aggregation for {stages_count} stages')
        
        stage_contexts = defaultdict(list)

        for _, stage_results in stage_batches:

            for group in stage_results:
                pipeline_context = group.get('context', {})
                for context_key, context_value in pipeline_context.items():
                    stage_contexts[context_key].append(context_value)

        return {
            'stage_contexts': stage_contexts
        }
        
    @event('reduce_stage_contexts')
    async def merge_events_groups(
        self,
        stage_batches: List[Tuple[str, List[Any]]]=[]
    ):

        stage_events_set = {}

        for stage_name, stage_results in stage_batches:


            batch_results: List[Dict[str, Union[dict, EventsGroup]]] = [
                dill.loads(group.get('events')) for group in stage_results
            ]

            stage_events =  defaultdict(EventsGroup)

            for events_groups in batch_results:
                for event_group_name, events_group in events_groups.items():
                    stage_events[event_group_name].merge(events_group)

            stage_events_set[stage_name] = stage_events

        return {
            'stage_events_set': stage_events_set
        }

    @event('merge_events_groups')
    async def calculate_custom_metrics(
        self,
        raw_results: RawResultsSet=[],
        stage_events_set: EventsSet={},
        custom_metric_hooks: List[str]=[]
    ):


        custom_metrics_set = {}

        for stage_name, stage_events in stage_events_set.items():    

            stage_custom_metrics = {}

            for event_group_name in stage_events.keys():  

                custom_metrics = defaultdict(dict)
                for custom_metric in custom_metric_hooks:
                    custom_metrics[custom_metric.group][custom_metric.shortname] = await custom_metric.call(
                        raw_results.get(
                            stage_name
                        ).get('results')
                    )

                stage_custom_metrics[event_group_name] = custom_metrics


            custom_metrics_set[stage_name] = stage_custom_metrics

        return {
            'custom_metrics_set': custom_metrics_set
        }

    @event('calculate_custom_metrics')
    async def generate_metrics_sets(
        self,
        custom_metrics_set: CustoMetricsSet={},
        stage_events_set: EventsSet={},
        stage_total_times: Dict[str, float]={},
    ):

        processed_results = []
        
        for stage_name, stage_events in stage_events_set.items():    

            grouped_stats = {}

            stage_total = 0
            stage_total_time = stage_total_times.get(stage_name)
            stage_custom_metrics = custom_metrics_set.get(stage_name)

            for event_group_name, events_group in stage_events.items():  

                custom_metrics = stage_custom_metrics.get(event_group_name)

                events_group.calculate_quantiles()

                metric_data = {
                    'total': events_group.total,
                    'succeeded': events_group.succeeded,
                    'failed': events_group.failed,
                    'actions_per_second': events_group.total/stage_total_time,
                    'errors': list([
                        {
                            'message': error_message,
                            'count': error_count
                        } for error_message, error_count in events_group.errors.items()
                    ]),
                    'groups': events_group.groups,
                    'custom': custom_metrics
                }

                metric = MetricsSet(
                    event_group_name,
                    events_group.source,
                    stage_name,
                    metric_data,
                    events_group.tags
                )

                grouped_stats[event_group_name] = metric

                stage_total += events_group.total

                await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Convererted stats for stage - {stage_name} to metrics set')
        
            await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Calculated results for - {stage_total} - actions from stage - {stage_name}')

            processed_results.append( {
                'stage_metrics': {
                    stage_name: {
                        'total': stage_total,
                        'actions_per_second': stage_total/stage_total_time,
                        'actions': grouped_stats
                    }
                },
                'stage_total': stage_total
            })

        return {
            'processed_results': processed_results
        }

    @context('generate_metrics_sets')
    async def generate_summary(
        self,
        stages_count: int=0,
        total_group_results: int=0,
        processed_results: ProcessedResultsSet={},
        stage_contexts: Dict[str, Any]={}
    ):

        self.context[self.name] = stage_contexts
        
        summaries = {
            'session_total': 0,
            'stages': {}
        }

        for result in processed_results:
            summaries['stages'].update(result.get('stage_metrics'))
            summaries['session_total'] += result.get('stage_total')

        self.analysis_execution_time = round(
            time.monotonic() - self.analysis_execution_time_start
        )

        await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Completed results analysis for - {stages_count} - stages in - {self.analysis_execution_time} seconds')
        await self.logger.spinner.set_default_message(f'Completed results analysis for {total_group_results} actions and {stages_count} stages over {self.analysis_execution_time} seconds')

        return {
            'summary_metrics': summaries
        }
