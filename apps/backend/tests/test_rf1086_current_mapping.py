"""Official #193 field meanings and actual current XSD acceptance, not service conformance."""
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import pytest

from talli_backend.modules.shareholder_register_filing.public import (
    generate_rf1086_documents, parse_rf1086_case, rf1086_xml_schema,
)

ROOT = Path(__file__).resolve().parents[3]


def documents(name):
    source = json.loads((ROOT / 'tests/fixtures/rf1086' / (name + '.json')).read_text())
    return generate_rf1086_documents(parse_rf1086_case(source))


def field(xml, name):
    return ET.fromstring(xml).find('.//' + name).text


def test_formation_is_t_in_both_company_and_shareholder_reports():
    result = documents('stiftelse_two_founders')
    assert field(result.hovedskjema_xml, 'AksjerNyutstedteStiftelseMvType-datadef-17670') == 'T'
    assert all(field(xml, 'AksjeErvervType-datadef-17745') == 'T' for xml in result.underskjema_xml.values())


def test_ordinary_sale_and_purchase_are_r_and_k():
    result = documents('share_sale')
    assert field(result.underskjema_xml['seller'], 'AksjerArvMvOmsattType-datadef-17753') == 'R'
    assert field(result.underskjema_xml['buyer'], 'AksjeErvervType-datadef-17745') == 'K'


def test_dividend_total_reconciles_main_and_shareholders_and_uses_y():
    result = documents('dividend')
    total = field(result.hovedskjema_xml, 'AksjeUtbytteISINAksjetype-datadef-17665')
    assert total == '100000'
    assert int(total) == sum(int(field(xml, 'Aksjeutbytte-datadef-29169')) for xml in result.underskjema_xml.values())
    assert field(result.hovedskjema_xml, 'AksjeUtbytteHendelsestype-datadef-36564') == 'Y'


@pytest.mark.parametrize('name', ['no_activity','stiftelse','stiftelse_two_founders','share_sale','dividend'])
def test_all_original_cases_validate_against_current_official_xsds(name, tmp_path):
    result = documents(name)
    for kind, xmls in [('hovedskjema', [result.hovedskjema_xml]), ('underskjema', result.underskjema_xml.values())]:
        schema = tmp_path / (kind + '.xsd')
        schema.write_bytes(rf1086_xml_schema(kind))
        for index, xml in enumerate(xmls):
            document = tmp_path / f'{kind}-{index}.xml'
            document.write_text(xml)
            run = subprocess.run(['xmllint','--nonet','--noout','--schema',str(schema),str(document)], capture_output=True, text=True)
            assert run.returncode == 0, run.stderr


@pytest.mark.parametrize('name,kind,holder,field_name,old_code', [
    ('share_sale','underskjema','seller','AksjerArvMvOmsattType-datadef-17753','S'),
    ('dividend','hovedskjema',None,'AksjeUtbytteHendelsestype-datadef-36564','U'),
])
def test_current_schema_rejects_previously_guessed_sale_and_dividend_codes(name, kind, holder, field_name, old_code, tmp_path):
    result = documents(name)
    xml = result.hovedskjema_xml if holder is None else result.underskjema_xml[holder]
    root = ET.fromstring(xml)
    root.find('.//' + field_name).text = old_code
    document, schema = tmp_path/'document.xml', tmp_path/'schema.xsd'
    document.write_bytes(ET.tostring(root))
    schema.write_bytes(rf1086_xml_schema(kind))
    run = subprocess.run(['xmllint','--nonet','--noout','--schema',str(schema),str(document)], capture_output=True, text=True)
    assert run.returncode != 0
    assert 'enumeration' in run.stderr
