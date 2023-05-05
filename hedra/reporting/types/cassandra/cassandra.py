import asyncio
import functools
import os
import psutil
import uuid
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor
from hedra.logging import HedraLogger
from hedra.reporting.experiment.experiments_collection import ExperimentMetricsCollectionSet
from hedra.reporting.processed_result.types.base_processed_result import BaseProcessedResult
from hedra.reporting.metric.stage_streams_set import StageStreamsSet
from hedra.reporting.metric import (
    MetricsSet,
    MetricType
)
from .cassandra_config import CassandraConfig


try:
    from cassandra.cqlengine import columns
    from cassandra.cqlengine import connection
    from datetime import datetime
    from cassandra.cqlengine.management import sync_table
    from cassandra.cqlengine.models import Model
    from cassandra.cluster import Cluster
    from cassandra.auth import PlainTextAuthProvider
    has_connector = True

except Exception:
    Cluster = None
    PlainTextAuthProvider = None
    has_connector = False


class Cassandra:

    def __init__(self, config: CassandraConfig) -> None:
        self.cluster = None
        self.session = None

        self.hosts = config.hosts
        self.port = config.port or 9042

        self.username = config.username
        self.password = config.password
        self.keyspace = config.keyspace
        
        self.events_table_name: str = config.events_table
        self.metrics_table_name: str = config.metrics_table
        self.streams_table_name: str = config.streams_table

        self.experiments_table_name: str= config.experiments_table
        self.variants_table_name: str= f'{config.experiments_table}_variants'
        self.mutations_table_name: str= f'{config.experiments_table}_mutations'

        self.shared_metrics_table_name = f'{config.metrics_table}_shared'
        self.custom_metrics_table_name = f'{config.metrics_table}_custom'
        self.errors_table_name = f'{config.metrics_table}_errors'
        
        self.replication_strategy = config.replication_strategy
        self.replication = config.replication       
        self.ssl = config.ssl

        self.session_uuid = str(uuid.uuid4())
        self.metadata_string: str = None
        self.logger = HedraLogger()
        self.logger.initialize()

        self._metrics_table = None
        self._errors_table = None
        self._events_table = None
        self._streams_table = None

        self._experiments_table = None
        self._variants_table = None
        self._mutations_table = None

        self._shared_metrics_table = None
        self._custom_metrics_table = None

        self._executor =ThreadPoolExecutor(max_workers=psutil.cpu_count(logical=False))
        self._loop = asyncio.get_event_loop()

    async def connect(self):

        host_port_combinations = ', '.join([
            f'{host}:{self.port}' for host in self.hosts
        ])

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Opening amd authorizing connection to Cassandra Cluster at - {host_port_combinations}')
        await self.logger.filesystem.aio['hedra.reporting'].debug(f'{self.metadata_string} - Opening session - {self.session_uuid}')

        auth = None
        if self.username and self.password:
            auth = PlainTextAuthProvider(self.username, self.password)
        

        self.cluster = Cluster(
            self.hosts,
            port=self.port,
            auth_provider=auth,
            ssl_context=self.ssl
        )

        self.session = await self._loop.run_in_executor(
            None,
            self.cluster.connect
        )


        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Connected to Cassandra Cluster at - {host_port_combinations}')

        if self.keyspace is None:
            self.keyspace = 'hedra'

        await self.logger.filesystem.aio['hedra.repoorting'].info(f'{self.metadata_string} - Creating Keyspace - {self.keyspace}')

        keyspace_options = f"'class' : '{self.replication_strategy}', 'replication_factor' : {self.replication}"
        keyspace_query = f"CREATE KEYSPACE IF NOT EXISTS {self.keyspace} WITH REPLICATION = " + "{" + keyspace_options  + "};"

        await self._loop.run_in_executor(
            None,
            self.session.execute,
            keyspace_query
        )

        await self._loop.run_in_executor(
            None,
            self.session.set_keyspace,
            self.keyspace
        )
        if os.getenv('CQLENG_ALLOW_SCHEMA_MANAGEMENT') is None:
            os.environ['CQLENG_ALLOW_SCHEMA_MANAGEMENT'] = '1'

        await self._loop.run_in_executor(
            self._executor,
            functools.partial(
                connection.setup,
                self.hosts, 
                self.keyspace, 
                protocol_version=3
            )
        )

        await self.logger.filesystem.aio['hedra.repoorting'].info(f'{self.metadata_string} - Created Keyspace - {self.keyspace}')
    
    async def submit_streams(self, stream_metrics: Dict[str, StageStreamsSet]):

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitting Streams to - Keyspace: {self.keyspace} - Table: {self.streams_table_name}')
        
        if self._streams_table is None:

            await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Creating Streams table - {self.streams_table_name} - under keyspace - {self.keyspace}')

            fields = {
                'id': columns.UUID(primary_key=True, default=uuid.uuid4),
                'name': columns.Text(min_length=1, index=True),
                'stage': columns.Text(min_length=1),
                'group': columns.Text(),
                'median': columns.Float(),
                'mean': columns.Float(),
                'variance': columns.Float(),
                'stdev': columns.Float(),
                'minimum': columns.Float(),
                'maximum': columns.Float(),
                'created_at': columns.DateTime(default=datetime.now)
            }

            self._streams_table = type(
                self.streams_table_name.capitalize(), 
                (Model, ), 
                fields
            )

            await self._loop.run_in_executor(
                self._executor,
                functools.partial(
                    sync_table,
                    self._streams_table,
                    keyspaces=[self.keyspace]
                )
            )

            await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Created Streams table - {self.streams_table_name} - under keyspace - {self.keyspace}')

        for stage_name, stream in stream_metrics.items():
            await self.logger.filesystem.aio['hedra.reporting'].debug(f'{self.metadata_string} - Submitting Stream - {stage_name}:{stream.stream_set_id}')

            for group_name, group in stream.grouped:
                await self._loop.run_in_executor(
                        self._executor,
                        functools.partial(
                            self._metrics_table.create,
                            **{
                                'name': f'{stage_name}_streams',
                                'stage': stage_name,
                                'group': group_name,
                                **group
                            }
                        )
                    )

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitted Shared Metrics to - Keyspace: {self.keyspace} - Table: {self.streams_table_name}')


    async def submit_experiments(self, experiment_metrics: ExperimentMetricsCollectionSet):
        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitting Experiments to - Keyspace: {self.keyspace} - Table: {self.experiments_table_name}')

        if self._experiments_table is None:

            await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Creating Experiments table - {self.experiments_table_name} - under keyspace - {self.keyspace}')

            self._experiments_table = type(
                self.experiments_table_name.capitalize(), 
                (Model, ), 
                {
                    'id': columns.UUID(primary_key=True, default=uuid.uuid4),
                    'experiment_name': columns.Text(min_length=1, index=True),
                    'experiment_randomized': columns.Boolean(),
                    'experiment_completed': columns.Integer(),
                    'experiment_succeeded': columns.Integer(),
                    'experiment_failed': columns.Integer(),
                    'experiment_median_aps': columns.Float(),
                    'created_at': columns.DateTime(default=datetime.now)
                }
            )

            await self._loop.run_in_executor(
                self._executor,
                functools.partial(
                    sync_table,
                    self._experiments_table,
                    keyspaces=[self.keyspace]
                )
            )

            await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Created Experiments table - {self.experiments_table_name} - under keyspace - {self.keyspace}')

        for experiment in experiment_metrics.experiments:
            
            await self._loop.run_in_executor(
                self._executor,
                functools.partial(
                    self._metrics_table.create,
                    **experiment
                )
            )

        
        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitted Experiments to - Keyspace: {self.keyspace} - Table: {self.experiments_table_name}')
    
    async def submit_variants(self, experiment_metrics: ExperimentMetricsCollectionSet):
        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitting Variants to - Keyspace: {self.keyspace} - Table: {self.variants_table_name}')

        if self._variants_table is None:

            await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Creating Variants table - {self.variants_table_name} - under keyspace - {self.keyspace}')

            self._variants_table = type(
                self.variants_table_name.capitalize(), 
                (Model, ), 
                {
                    'id': columns.UUID(primary_key=True, default=uuid.uuid4),
                    'variant_name': columns.Text(min_length=1, index=True),
                    'variant_experiment': columns.Text(min_length=1),
                    'variant_weight': columns.Float(),
                    'variant_distribution': columns.Text(min_length=1),
                    'variant_distribution_interval': columns.Float(),
                    'variant_ratio_completed': columns.Float(),
                    'variant_ratio_succeeded': columns.Float(),
                    'variant_ratio_failed': columns.Float(),
                    'variant_ratio_aps': columns.Float(),
                    'variant_completed': columns.Integer(),
                    'variant_succeeded': columns.Integer(),
                    'variant_failed': columns.Integer(),
                    'variant_actions_per_second': columns.Float(),
                    'created_at': columns.DateTime(default=datetime.now)
                }
            )

            await self._loop.run_in_executor(
                self._executor,
                functools.partial(
                    sync_table,
                    self._variants_table,
                    keyspaces=[self.keyspace]
                )
            )

            await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Created Variants table - {self.variants_table_name} - under keyspace - {self.keyspace}')

        for variant in experiment_metrics.variants:
            
            await self._loop.run_in_executor(
                self._executor,
                functools.partial(
                    self._metrics_table.create,
                    **variant
                )
            )

        
        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitted Variants to - Keyspace: {self.keyspace} - Table: {self.variants_table_name}')
    
    async def submit_mutations(self, experiment_metrics: ExperimentMetricsCollectionSet):
        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitting Mutations to - Keyspace: {self.keyspace} - Table: {self.mutations_table_name}')

        if self._mutations_table is None:

            await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Creating Mutations table - {self.mutations_table_name} - under keyspace - {self.keyspace}')

            self._mutations_table = type(
                self.mutations_table_name.capitalize(), 
                (Model, ), 
                {
                    'id': columns.UUID(primary_key=True, default=uuid.uuid4),
                    'mutation_name': columns.Text(min_length=1, index=True),
                    'mutation_experiment_name': columns.Text(min_length=1),
                    'mutation_variant_name': columns.Text(min_length=1),
                    'mutation_chance': columns.Float(),
                    'mutation_targets': columns.Text(min_length=1),
                    'mutation_type': columns.Text(min_length=1),
                    'created_at': columns.DateTime(default=datetime.now)
                }
            )

            await self._loop.run_in_executor(
                self._executor,
                functools.partial(
                    sync_table,
                    self._mutations_table,
                    keyspaces=[self.keyspace]
                )
            )

            await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Created Mutations table - {self.mutations_table_name} - under keyspace - {self.keyspace}')

        for mutation in experiment_metrics.mutations:
            
            await self._loop.run_in_executor(
                self._executor,
                functools.partial(
                    self._metrics_table.create,
                    **mutation
                )
            )

        
        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitted Mutations to - Keyspace: {self.keyspace} - Table: {self.mutations_table_name}')

    async def submit_events(self, events: List[BaseProcessedResult]):

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitting Events to - Keyspace: {self.keyspace} - Table: {self.events_table_name}')

        if self._events_table is None:

            await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Creating Events table - {self.events_table_name} - under keyspace - {self.keyspace}')

            self._events_table = type(
                self.events_table_name.capitalize(), 
                (Model, ), 
                {
                    'id': columns.UUID(primary_key=True, default=uuid.uuid4),
                    'name': columns.Text(min_length=1, index=True),
                    'stage': columns.Text(min_length=1),
                    'time': columns.Float(),
                    'succeeded': columns.Boolean(),
                    'created_at': columns.DateTime(default=datetime.now)
                }
            )

            await self._loop.run_in_executor(
                self._executor,
                functools.partial(
                    sync_table,
                    self._events_table,
                    keyspaces=[self.keyspace]
                )
            )

            await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Created Events table - {self.events_table_name} - under keyspace - {self.keyspace}')

        for event in events:
            
            await self._loop.run_in_executor(
                self._executor,
                functools.partial(
                    self._metrics_table.create,
                    **event.record
                )
            )

        
        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitted Events to - Keyspace: {self.keyspace} - Table: {self.events_table_name}')

    async def submit_common(self, metrics_sets: List[MetricsSet]):

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitting Shared Metrics to - Keyspace: {self.keyspace} - Table: {self.shared_metrics_table_name}')
        
        if self._shared_metrics_table is None:

            await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Creating Shared Metrics table - {self.shared_metrics_table_name} - under keyspace - {self.keyspace}')

            fields = {
                'id': columns.UUID(primary_key=True, default=uuid.uuid4),
                'name': columns.Text(min_length=1, index=True),
                'stage': columns.Text(min_length=1),
                'group': columns.Text(min_length=1),
                'total': columns.Integer(),
                'succeeded': columns.Integer(),
                'failed': columns.Integer(),
                'actions_per_second': columns.Float()
            }

            self._shared_metrics_table = type(
                self.shared_metrics_table_name.capitalize(), 
                (Model, ), 
                fields
            )

            await self._loop.run_in_executor(
                self._executor,
                functools.partial(
                    sync_table,
                    self._shared_metrics_table,
                    keyspaces=[self.keyspace]
                )
            )

            await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Created Shared Metrics table - {self.shared_metrics_table_name} - under keyspace - {self.keyspace}')

        for metrics_set in metrics_sets:
            await self.logger.filesystem.aio['hedra.reporting'].debug(f'{self.metadata_string} - Submitting Shared Metrics Set - {metrics_set.name}:{metrics_set.metrics_set_id}')
            await self._loop.run_in_executor(
                    self._executor,
                    functools.partial(
                        self._metrics_table.create,
                        **{
                            'name': metrics_set.name,
                            'stage': metrics_set.stage,
                            'group': 'common',
                            **metrics_set.common_stats
                        }
                    )
                )

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitted Shared Metrics to - Keyspace: {self.keyspace} - Table: {self.shared_metrics_table_name}')

    async def submit_metrics(self, metrics: List[MetricsSet]):

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitting Metrics to - Keyspace: {self.keyspace} - Table: {self.metrics_table_name}')

        for metrics_set in metrics:
            await self.logger.filesystem.aio['hedra.reporting'].debug(f'{self.metadata_string} - Submitting Metrics Set - {metrics_set.name}:{metrics_set.metrics_set_id}')
       
            if self._metrics_table is None:
                
                await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Creating Metrics table - {self.metrics_table_name} - under keyspace - {self.keyspace}')
                
                fields = {
                    'id': columns.UUID(primary_key=True, default=uuid.uuid4),
                    'name': columns.Text(min_length=1, index=True),
                    'stage': columns.Text(min_length=1),
                    'group': columns.Text(),
                    'median': columns.Float(),
                    'mean': columns.Float(),
                    'variance': columns.Float(),
                    'stdev': columns.Float(),
                    'minimum': columns.Float(),
                    'maximum': columns.Float(),
                    'created_at': columns.DateTime(default=datetime.now)
                }


                for quantile_name in metrics_set.quantiles:
                    fields[quantile_name] = columns.Float()
                
                for custom_field_name, custom_field_type in metrics_set.custom_schemas:
                    fields[custom_field_name] = custom_field_type


                self._metrics_table = type(
                    self.metrics_table_name.capitalize(), 
                    (Model, ), 
                    fields
                )

                await self._loop.run_in_executor(
                    self._executor,
                    functools.partial(
                        sync_table,
                        self._metrics_table,
                        keyspaces=[self.keyspace]
                    )
                )

                await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Created Metrics table - {self.metrics_table_name} - under keyspace - {self.keyspace}')

            for group_name, group in metrics_set.groups.items():
                await self.logger.filesystem.aio['hedra.reporting'].debug(f'{self.metadata_string} - Submitting Metrics Group - {group_name}:{group.metrics_group_id}')                
                await self._loop.run_in_executor(
                    self._executor,
                    functools.partial(
                        self._metrics_table.create,
                        **{
                            **group.record,
                            'group': group_name
                        }
                    )
                )

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitted Metrics Set to - Keyspace: {self.keyspace} - Table: {self.metrics_table_name}')

    async def submit_custom(self, metrics_sets: List[MetricsSet]):

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitting Custom Metrics Set to - Keyspace: {self.keyspace} - Table: {self.metrics_table_name}')
        await self.logger.filesystem.aio['hedra.reporting'].debug(f'{self.metadata_string} - Submitting Custom Metrics Group - Custom')

        if self._custom_metrics_table is None:

            await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Creating Custom Metrics table - {self.custom_metrics_table_name} - under keyspace - {self.keyspace}')
            
            custom_table = {
                'id': columns.UUID(primary_key=True, default=uuid.uuid4),
                'name': columns.Text(min_length=1, index=True),
                'stage': columns.Text(min_length=1),
                'group': columns.Text(min_length=1)
            }

            for metrics_set in metrics_sets:
                for custom_metric_name, custom_metric in metrics_set.custom_metrics.items():

                    cassandra_column = columns.Integer()

                    if custom_metric.metric_type == MetricType.COUNT:
                        cassandra_column = columns.Integer()
                    
                    else:
                        cassandra_column = columns.Float()

                    custom_table[custom_metric_name] = cassandra_column
                    custom_table[custom_metric_name] = cassandra_column

            self._custom_metrics_table: Model = type(
                self.custom_metrics_table_name.capitalize(), 
                (Model, ), 
                custom_table
            )

            await self._loop.run_in_executor(
                self._executor,
                functools.partial(
                    sync_table,
                    self._custom_metrics_table,
                    keyspaces=[self.keyspace]
                )
            )

            await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Created Custom Metrics table - {self.custom_metrics_table_name} - under keyspace - {self.keyspace}')


        for metrics_set in metrics_sets:
            await self.logger.filesystem.aio['hedra.reporting'].debug(f'{self.metadata_string} - Submitting Custom Metrics Set - {metrics_set.name}:{metrics_set.metrics_set_id}')
                

            await self._loop.run_in_executor(
                self._executor,
                functools.partial(
                    self._custom_metrics_table.create,
                    {
                        'name': metrics_set.name,
                        'stage': metrics_set.stage,
                        'group': 'Custom',
                        **{
                            custom_metric_name: custom_metric.metric_value for custom_metric_name, custom_metric in metrics_set.custom_metrics.items()
                        }
                    }
                )
            )
        
        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitted Custom Metrics Set to - Keyspace: {self.keyspace} - Table: {self.metrics_table_name}')

    async def submit_errors(self, metrics_sets: List[MetricsSet]):

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitting Errors Metrics to - Keyspace: {self.keyspace} - Table: {self.errors_table_name}')

        if self._errors_table is None:

            await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Creating Errors Metrics table - {self.errors_table_name} - under keyspace - {self.keyspace}')

            errors_table_fields = {
                'id': columns.UUID(primary_key=True, default=uuid.uuid4),
                'name': columns.Text(min_length=1, index=True),
                'stage': columns.Text(min_length=1),
                'error_message': columns.Text(min_length=1),
                'error_count': columns.Integer()
            }

            self._errors_table = type(
                self.errors_table_name.capitalize()
                (Model, ),
                errors_table_fields
            )

            await self._loop.run_in_executor(
                self._executor,
                functools.partial(
                    sync_table,
                    self._errors_table,
                    keyspaces=[self.keyspace]
                )
            )

            await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Created Errors Metrics table - {self.errors_table_name} - under keyspace - {self.keyspace}')

        for metrics_set in metrics_sets:
            await self.logger.filesystem.aio['hedra.reporting'].debug(f'{self.metadata_string} - Submitting Errors Metrics Set - {metrics_set.name}:{metrics_set.metrics_set_id}')

            for error in metrics_set.errors:
                await self._loop.run_in_executor(
                    self._executor,
                    functools.partial(
                        self._errors_table.create,
                        {
                            'name': metrics_set.name,
                            'stage': metrics_set.stage,
                            'error_message': error.get('message'),
                            'error_count': error.get('count')
                        }
                    )
                )
        
        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitted Errors Metrics to - Keyspace: {self.keyspace} - Table: {self.errors_table_name}')
 
    async def close(self):
        host_port_combinations = ', '.join([
            f'{host}:{self.port}' for host in self.hosts
        ])

        await self.logger.filesystem.aio['hedra.reporting'].debug(f'{self.metadata_string} - Closing session - {self.session_uuid}')
        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Closing connection to Cassandra Cluster at - {host_port_combinations}')

        await self._loop.run_in_executor(
            None,
            self.cluster.shutdown
        )

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Closed connection to Cassandra Cluster at - {host_port_combinations}')