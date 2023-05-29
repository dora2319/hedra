import os
from pydantic import BaseModel, StrictStr
from hedra.data.connectors.common.connector_type import ConnectorType


class JSONConnectorConfig(BaseModel):
    filepath: StrictStr
    file_mode: StrictStr='r'
    reporter_type: ConnectorType=ConnectorType.JSON