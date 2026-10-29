"""Wire conventions only; no business models belong in the shared package."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PlainSerializer
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
    )


MoneyAmount = Annotated[
    int,
    Field(ge=0, strict=True),
    PlainSerializer(str, return_type=str, when_used="json"),
]


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone")
    return value.astimezone(UTC)


UtcDatetime = Annotated[
    datetime,
    AfterValidator(normalize_utc),
    PlainSerializer(
        lambda value: value.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        return_type=str,
        when_used="json",
    ),
]
