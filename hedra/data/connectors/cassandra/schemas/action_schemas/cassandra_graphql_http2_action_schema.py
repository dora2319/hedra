import uuid
from datetime import datetime
from hedra.core.engines.types.common.types import RequestTypes


try:
    from cassandra.cqlengine import columns
    from cassandra.cqlengine.models import Model
    has_connector = True

except Exception:
    columns = object
    Model = None
    has_connector = False


class CassandraGraphQLHTTP2ActionSchema:

    def __init__(self, table_name: str) -> None:
        self.action_columns = {
            'id': columns.UUID(primary_key=True, default=uuid.uuid4),
            'name': columns.Text(min_length=1, index=True),
            'method': columns.Text(min_length=1),
            'url': columns.Text(min_length=1),
            'headers': columns.Text(),
            'query': columns.Text(min_length=1),
            'operation_name': columns.Text(min_length=1),
            'variables': columns.Text(min_length=1),
            'user': columns.Text(),
            'tags': columns.List(
                columns.Map(
                    columns.Text(),
                    columns.Text()
                )
            ),
            'created_at': columns.DateTime(default=datetime.now)
        }

        self.actions_table = type(
            f'{table_name}_graphql_http2',
            (Model, ), 
            self.action_columns
        )

        self.type = RequestTypes.GRAPHQL_HTTP2
