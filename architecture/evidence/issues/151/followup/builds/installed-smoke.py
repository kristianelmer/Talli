from pathlib import Path
from dataclasses import fields,is_dataclass
from collections.abc import Mapping
import hashlib,json,sys,socket

def deny_network(*args,**kwargs):
    raise AssertionError('installed_smoke_forbids_network')
socket.create_connection=deny_network
import talli_backend
from talli_backend.main import app
from talli_backend.modules.shareholder_register_filing.public import parse_rf1086_case,render_rf1086_preview,rf1086_xml_schema
from fastapi.testclient import TestClient

repo=Path(sys.argv[1]).resolve()
installed=Path(talli_backend.__file__).resolve()
assert 'installed-venv' in installed.parts and 'site-packages' in installed.parts
assert not any(str(repo) in value for value in sys.path)
assert not any(name=='holding_core' or name.startswith('holding_core.') or name=='holding_cli' or name.startswith('holding_cli.') for name in sys.modules)
manifest=json.loads((repo/'apps/backend/tests/fixtures/rf1086_oracle/manifest.json').read_text())
schemas={}
for document,name in [('hovedskjema','aksjonaerregisteroppgaveHovedskjema.xsd'),('underskjema','aksjonaerregisteroppgaveUnderskjema.xsd')]:
    digest=hashlib.sha256(rf1086_xml_schema(document)).hexdigest()
    assert digest==manifest['files']['docs/filing/'+name]
    schemas[document]=digest

def values(value):
    if is_dataclass(value):return {item.name:values(getattr(value,item.name)) for item in fields(value)}
    if isinstance(value,Mapping):return {key:values(item) for key,item in value.items()}
    if isinstance(value,tuple):return [values(item) for item in value]
    return value
cases=json.loads((repo/'apps/backend/tests/fixtures/rf1086_oracle/python-oracle.json').read_text())
case=next(case for case in cases if 'error' not in case and case.get('output',{}).get('hovedskjemaXml'))
result=values(render_rf1086_preview(parse_rf1086_case(case['input'])))
result['hovedskjemaXml']=result.pop('hovedskjema_xml');result['underskjemaXml']=result.pop('underskjema_xml')
assert result==case['output']
with TestClient(app) as client:
    assert client.get('/health/live').status_code==200
    tracer=client.get('/api/v1/system-boundary/tracer')
    assert tracer.status_code==200 and tracer.json()=={'apiVersion':'v1','service':'talli-backend','status':'AVAILABLE'}
    schema=app.openapi()
    assert '/api/v1/shareholder-register-filings/archive-source' in schema['paths']
print(json.dumps({'verdict':'pass','installed_from_wheel':True,'outside_source_path':True,'legacy_root_imports':False,'bundled_rf_schemas':schemas,'fixed_input_original_output_exact':True,'health_and_tracer':True,'archive_source_contract_present':True,'provider_and_database_operations':False},sort_keys=True))
