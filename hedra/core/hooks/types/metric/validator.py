from pydantic import BaseModel, Field, StrictStr, validator


class MetricHookValidator(BaseModel):
    metric_type: StrictStr
    group: StrictStr=Field(..., min_length=1)

    @validator('metric_type')
    def validate_names(cls, val):
        
        valid_metric_types = [
            "count",
            "rate",
            "distribution",
            "sample"
        ]

        assert val in valid_metric_types

