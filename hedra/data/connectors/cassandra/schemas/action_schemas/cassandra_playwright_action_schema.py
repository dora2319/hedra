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


class CassandraPlaywrightActionSchema:

    def __init__(self, table_name: str) -> None:
        self.action_columns = {
            'id': columns.UUID(primary_key=True, default=uuid.uuid4),
            'name': columns.Text(min_length=1, index=True),
            'command': columns.Text(min_length=1),
            'selector': columns.Text(min_length=1),
            'attribute': columns.Text(min_length=1),
            'x_coordinate': columns.Text(min_length=1),
            'y_coordinate': columns.Text(min_length=1),
            'frame': columns.Integer(default=0),
            'location': columns.Text(),
            'headers': columns.Text(),
            'key': columns.Text(),
            'text': columns.Text(),
            'expression': columns.Text(),
            'args': columns.List(
                columns.Map(
                    columns.Text(),
                    columns.Text()
                )
            ),
            'filepath': columns.Text(),
            'file': columns.Text(),
            'path': columns.Text(),
            'option': columns.Map(
                columns.Text(),
                columns.Text()
            ),
            'by_label': columns.Boolean(default=False),
            'by_value': columns.Boolean(default=False),
            'event': columns.Text(),
            'is_checked': columns.Boolean(default=False),
            'timeout': columns.Float(),
            'extra': columns.Text(),
            'switch_by': columns.Text(),
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
            f'{table_name}_playwright',
            (Model, ), 
            self.action_columns
        )

        self.type = RequestTypes.PLAYWRIGHT
