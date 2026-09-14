"""Opaque JSON transport keeps ordinary Pydantic formatting and refuses cycles."""
from datetime import datetime,timezone
from uuid import UUID

import pytest
from pydantic import BaseModel,Field

from talli_backend.json_transport import model_json_response


class Wire(BaseModel):
    identity: UUID=Field(serialization_alias='recordId')
    recorded_at: datetime=Field(serialization_alias='recordedAt')
    values: dict


def test_iterative_json_matches_normal_validated_wire_serialization():
    model=Wire(identity=UUID('15300000-0000-4000-8000-000000000020'),recorded_at=datetime(2026,9,14,9,0,1,123000,tzinfo=timezone.utc),
        values={'unicode':'årsregnskap','nested':[None,True,False,0,-0.0,1.5,{'quote':'"\n'}]})
    assert model_json_response(model).body.decode()==model.model_dump_json(by_alias=True)


def test_iterative_json_refuses_cyclic_values():
    model=Wire(identity=UUID('15300000-0000-4000-8000-000000000020'),recorded_at=datetime.now(timezone.utc),values={})
    model.values['cycle']=model.values
    with pytest.raises(ValueError,match='Cyclic'):model_json_response(model)
