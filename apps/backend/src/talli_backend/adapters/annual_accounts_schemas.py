"""Offline constraints derived from exact public RR0002 JSON model annotations.

This is a strict local XML subset, not an upstream XSD or runtime acceptance.
No network resolver, dependency installation, or authority operation is used.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re

from lxml import etree

from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsError,AnnualAccountsDocumentsInspection,AnnualAccountsSchemaValidator,annual_accounts_schema_adapter,
)

_BUNDLE=Path(__file__).resolve().parents[1]/'modules/annual_accounts_filing/schemas/rr0002-202406-v1'
_PIN='04653f5ef226df749e5d9cd7a66dd5c061de85c2c1a7f44ce7c12cea3e1faa49'
_XSD='http://www.w3.org/2001/XMLSchema'
_APP='brg/aarsregnskap-vanlig-202406'
_MAIN_NS='http://schema.brreg.no/regnsys/aarsregnskap_vanlig'
_ACCOUNTS_NS=_MAIN_NS+'/underskjema'
# Explicit supported packet branches from the released renderer, not the
# broader upstream optional form. No customer facts or readiness are embedded.
_PROFILE_LEAVES={'companyAccountsXml': ('Rapport-RR0002U/aarsregnskap/regnskapstype',
                        'Rapport-RR0002U/aarsregnskap/valuta',
                        'Rapport-RR0002U/aarsregnskap/valoer',
                        'Skjemainnhold-RR0002U/resultatregnskapDriftsresultat/driftsresultat/aarets',
                        'Skjemainnhold-RR0002U/resultatregnskapDriftsresultat/kostnad/sumDriftskostnad/aarets',
                        'Skjemainnhold-RR0002U/resultatregnskapFinansinntekt/nettoFinans/aarets',
                        'Skjemainnhold-RR0002U/resultatregnskapFinansinntekt/finansinntekt/sumFinansinntekter/aarets',
                        'Skjemainnhold-RR0002U/resultatregnskapFinansinntekt/finanskostnad/sumFinanskostnader/aarets',
                        'Skjemainnhold-RR0002U/resultatregnskapResultat/resultat/resultatFoerSkattekostnad/aarets',
                        'Skjemainnhold-RR0002U/resultatregnskapResultat/resultat/skattekostnad/aarets',
                        'Skjemainnhold-RR0002U/resultatregnskapResultat/resultat/aarsresultat/aarets',
                        'Skjemainnhold-RR0002U/balanseAnleggsmidlerOmloepsmidler/sumEiendeler/aarets',
                        'Skjemainnhold-RR0002U/balanseAnleggsmidlerOmloepsmidler/balanseAnleggsmidler/sumAnleggsmidler/aarets',
                        'Skjemainnhold-RR0002U/balanseAnleggsmidlerOmloepsmidler/balanseAnleggsmidler/balanseFinansielleAnleggsmidler/investeringAksjerAndeler/aarets',
                        'Skjemainnhold-RR0002U/balanseAnleggsmidlerOmloepsmidler/balanseAnleggsmidler/balanseFinansielleAnleggsmidler/sumFinansielleAnleggsmidler/aarets',
                        'Skjemainnhold-RR0002U/balanseAnleggsmidlerOmloepsmidler/balanseOmloepsmidler/sumOmloepsmidler/aarets',
                        'Skjemainnhold-RR0002U/balanseAnleggsmidlerOmloepsmidler/balanseOmloepsmidler/balanseOmloepsmidlerInvesteringerBankinnskuddKontanter/bankinnskuddKontanter/sumBankinnskuddKontanter/aarets',
                        'Skjemainnhold-RR0002U/balanseEgenkapitalGjeld/sumEgenkapitalGjeld/aarets',
                        'Skjemainnhold-RR0002U/balanseEgenkapitalGjeld/balanseEgenkapitalInnskuttOpptjentEgenkapital/innskuttEgenkapital/sumInnskuttEgenkapital/aarets',
                        'Skjemainnhold-RR0002U/balanseEgenkapitalGjeld/balanseEgenkapitalInnskuttOpptjentEgenkapital/opptjentEgenkaiptal/annenEgenkapital/aarets',
                        'Skjemainnhold-RR0002U/balanseEgenkapitalGjeld/balanseEgenkapitalInnskuttOpptjentEgenkapital/opptjentEgenkaiptal/sumOpptjentEgenkapital/aarets',
                        'Skjemainnhold-RR0002U/balanseEgenkapitalGjeld/balanseEgenkapitalInnskuttOpptjentEgenkapital/opptjentEgenkaiptal/sumEgenkapital/aarets',
                        'Skjemainnhold-RR0002U/balanseEgenkapitalGjeld/balanseGjeldOversikt/sumGjeld/aarets',
                        'Skjemainnhold-RR0002U/balanseEgenkapitalGjeld/balanseGjeldOversikt/balanseKortsiktigGjeld/betalbarSkatt/aarets',
                        'Skjemainnhold-RR0002U/balanseEgenkapitalGjeld/balanseGjeldOversikt/balanseKortsiktigGjeld/sumKortsiktigGjeld/aarets',
                        'Skjemainnhold-RR0002U/noter/noteAarsverkTjenestePensjon/antallAarsverk'),
 'mainFormXml': ('Innsender/enhet/organisasjonsnummer',
                 'Innsender/enhet/organisasjonsform',
                 'Innsender/enhet/navn',
                 'Innsender/kontaktperson/e-post',
                 'Innsender/opplysningerInnsending/noteMaskinellBehandling',
                 'Innsender/opplysningerInnsending/systemNavn',
                 'Skjemainnhold/regnskapsperiode/regnskapsaar',
                 'Skjemainnhold/regnskapsperiode/regnskapsstart',
                 'Skjemainnhold/regnskapsperiode/regnskapsslutt',
                 'Skjemainnhold/konsern/morselskap',
                 'Skjemainnhold/regnskapsprinsipper/smaaForetak',
                 'Skjemainnhold/regnskapsprinsipper/regnskapsreglerSelskap',
                 'Skjemainnhold/fastsettelse/fastsettelsedato',
                 'Skjemainnhold/fastsettelse/bekreftendeSelskapsrepresentant',
                 'Skjemainnhold/revisjonRegnskapsfoerer/aarsregnskapIkkeRevideres',
                 'Skjemainnhold/revisjonRegnskapsfoerer/aarsregnskapUtarbeidetAutorisertRegnskapsfoerer',
                 'Skjemainnhold/revisjonRegnskapsfoerer/tjenestebistandEksternAutorisertRegnskapsfoerer')}



def _parse(raw):
    if type(raw) is not bytes or not 0<len(raw)<=8*1024*1024:raise ValueError('RR0002 XML exceeds its byte bound.')
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('RR0002 XML declarations are unsupported.')
    root=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False,huge_tree=False))
    if root.getroottree().docinfo.doctype or root.getroottree().docinfo.encoding.upper().replace('-','')!='UTF8':raise ValueError()
    count=0;pending=[(root,1)]
    while pending:
        node,depth=pending.pop();count+=1
        if count>100000 or depth>64 or not isinstance(node.tag,str):raise ValueError('RR0002 XML structure is unsupported.')
        pending.extend((child,depth+1) for child in node)
    if root.getprevious() is not None or root.getnext() is not None:raise ValueError()
    return root


def _constraints(model):
    """Compile only the pinned annotation vocabulary; unknown constructs fail."""
    root_keys={'$schema','$id','type','@xsdNamespaces','@xsdSchemaAttributes','info','@xsdRootElement','oneOf','$defs'}
    if set(model)!=root_keys or model['type']!='object' or model['$schema']!='https://json-schema.org/draft/2020-12/schema':raise ValueError()
    if len(model['oneOf'])!=1 or set(model['oneOf'][0])!={'$ref'}:raise ValueError()
    definitions=model['$defs'];namespace=model['@xsdNamespaces']['']
    if (model['$id']!='schema.json' or model['@xsdNamespaces']!={'':namespace,'xs':_XSD}
            or model['@xsdSchemaAttributes']!={'AttributeFormDefault':'None','ElementFormDefault':'Qualified',
                'BlockDefault':'None','FinalDefault':'None','TargetNamespace':namespace}):raise ValueError()
    def property_constraint(value):
        if type(value) is not dict:raise ValueError()
        if '$ref' in value:
            if set(value)-{'$ref','@xsdText','@xsdMinOccurs'}:raise ValueError('RR0002 unsupported reference siblings.')
            if '@xsdText' in value and value['@xsdText'] is not True:raise ValueError()
        elif value.get('type')=='array':
            if set(value)-{'type','items','maxItems','@xsdMinOccurs','@xsdMaxOccurs'} or set(value['items'])!={'$ref'}:raise ValueError()
            maximum=value.get('@xsdMaxOccurs','unbounded')
            if maximum!='unbounded' and (not str(maximum).isdigit() or int(maximum)<1):raise ValueError()
            if 'maxItems' in value and (type(value['maxItems']) is not int or maximum=='unbounded' or value['maxItems']!=int(maximum)):raise ValueError()
        else:
            if (set(value)!={'@xsdType','type','const','@xsdAttribute'} or value['@xsdAttribute'] is not True
                    or value['@xsdType']!='string' or value['type']!='string' or type(value['const']) is not str):raise ValueError()
        if '@xsdMinOccurs' in value and (type(value['@xsdMinOccurs']) is not int or value['@xsdMinOccurs'] not in (0,1)):raise ValueError()
    def supported(value):
        if type(value) is not dict:raise ValueError()
        if 'allOf' in value:
            if set(value)-{'allOf','@xsdAnyAttribute'}:raise ValueError('RR0002 unsupported composition siblings.')
            if '@xsdAnyAttribute' in value and value['@xsdAnyAttribute']!={'Namespace':'##any','ProcessContent':'None'}:raise ValueError()
            for part in value['allOf']:supported(part)
        elif 'properties' in value:
            if set(value)-{'properties','required'}:raise ValueError()
            for item in value['properties'].values():property_constraint(item)
        else:
            if set(value)-{'@xsdType','type','@xsdStructure','minLength','maxLength','minimum','maximum','enum','format'}:raise ValueError()
            kind=value.get('@xsdType')
            if kind not in ('string','integer','date') or value['type']!=('integer' if kind=='integer' else 'string'):raise ValueError()
            if value.get('format') not in (None,'date') or 'format' in value and kind!='date':raise ValueError()
            if kind=='date' and set(value)&{'minLength','maxLength','minimum','maximum','enum'}:raise ValueError()
    for definition in definitions.values():supported(definition)
    schema=etree.Element('{'+_XSD+'}schema',nsmap={'xs':_XSD,'m':namespace},targetNamespace=namespace,
        elementFormDefault='qualified',attributeFormDefault='unqualified')
    def child(parent,tag,**attributes):return etree.SubElement(parent,'{'+_XSD+'}'+tag,**{key:str(value) for key,value in attributes.items()})
    def reference(value):
        name=value['$ref']
        if not name.startswith('#/$defs/') or name[8:] not in definitions:raise ValueError('RR0002 external or unknown schema reference.')
        return 'm:'+name[8:]
    def scalar_type(value):
        if '$ref' in value:return reference(value)
        kind=value['@xsdType']
        if kind not in ('string','integer','date'):raise ValueError('RR0002 scalar type is unsupported.')
        return 'xs:'+kind
    def merged(value):
        if 'allOf' not in value:return value
        properties={};required=[]
        for part in value['allOf']:
            if set(part)-{'properties','required'}:raise ValueError('RR0002 composition is unsupported.')
            if set(properties)&set(part.get('properties',{})):raise ValueError('RR0002 repeated schema property.')
            properties.update(part.get('properties',{}));required.extend(part.get('required',()))
        return {'properties':properties,'required':required}
    for name,definition in definitions.items():
        if re.fullmatch('[A-Za-z_][A-Za-z0-9_.-]*',name) is None:raise ValueError()
        value=merged(definition)
        if 'properties' not in value:
            if value.get('@xsdStructure')!='XmlSchemaSimpleTypeRestriction':raise ValueError()
            target=child(schema,'simpleType',name=name);restriction=child(target,'restriction',base=scalar_type(value))
            for key,facet in (('minLength','minLength'),('maxLength','maxLength'),('minimum','minInclusive'),('maximum','maxInclusive')):
                if key in value:child(restriction,facet,value=value[key])
            for item in value.get('enum',()):child(restriction,'enumeration',value=item)
            continue
        properties=value['properties'];required=set(value.get('required',()))
        if not required<=set(properties):raise ValueError()
        target=child(schema,'complexType',name=name)
        texts=[(key,item) for key,item in properties.items() if item.get('@xsdText') is True]
        elements=[(key,item) for key,item in properties.items() if not item.get('@xsdAttribute') and not item.get('@xsdText')]
        if texts:
            if len(texts)!=1 or elements:raise ValueError('RR0002 mixed content is unsupported.')
            target=child(child(target,'simpleContent'),'extension',base=scalar_type(texts[0][1]))
        elif elements:
            sequence=child(target,'sequence')
            for key,item in elements:
                array=item.get('type')=='array';element_type=scalar_type(item['items'] if array else item)
                minimum=item.get('@xsdMinOccurs',1 if key in required else 0)
                maximum=item.get('@xsdMaxOccurs',item.get('maxItems','unbounded')) if array else 1
                child(sequence,'element',name=key,type=element_type,minOccurs=minimum,maxOccurs=maximum)
        for key,item in properties.items():
            if not item.get('@xsdAttribute'):continue
            attributes={'name':key,'type':scalar_type(item),'use':'required' if key in required else 'optional'}
            if 'const' in item:attributes['fixed']=item['const']
            child(target,'attribute',**attributes)
        # The upstream root permits wildcard attributes. This narrow local
        # profile deliberately rejects extras rather than silently ignoring them.
    root=model['oneOf']
    if len(root)!=1:raise ValueError('RR0002 root choice is unsupported.')
    child(schema,'element',name=model['@xsdRootElement'],type=reference(root[0]))
    return etree.XMLSchema(schema)


@annual_accounts_schema_adapter(AnnualAccountsSchemaValidator)
class PinnedAnnualAccountsSchemas:
    def __init__(self):
        try:
            if _BUNDLE.is_symlink() or (_BUNDLE/'manifest.json').is_symlink():raise ValueError()
            raw=(_BUNDLE/'manifest.json').read_bytes()
            if sha256(raw).hexdigest()!=_PIN:raise ValueError()
            manifest=json.loads(raw)
            expected={'Hovedskjema.json','Underskjema.json','applicationmetadata.json','process.bpmn'}
            if manifest['version']!='annual-accounts-rr0002-schemas-v1' or manifest['applicationId']!=_APP or set(manifest['files'])!=expected:raise ValueError()
            resources={}
            for name,record in manifest['files'].items():
                path=_BUNDLE/name
                if path.is_symlink():raise ValueError()
                raw=path.read_bytes()
                if len(raw)!=record['bytes'] or sha256(raw).hexdigest()!=record['sha256']:raise ValueError()
                resources[name]=raw
            metadata=json.loads(resources['applicationmetadata.json'])
            if metadata['id']!=_APP:raise ValueError()
            process=_parse(resources['process.bpmn'])
            ns={'b':'http://www.omg.org/spec/BPMN/20100524/MODEL'}
            if {node.get('id') for node in process.xpath('//b:task',namespaces=ns)}!={'Utfylling','Signering'}:raise ValueError()
            self._schemas=tuple(_constraints(json.loads(resources[name])) for name in ('Hovedskjema.json','Underskjema.json'))
        except (OSError,ValueError,TypeError,KeyError,AttributeError,etree.LxmlError):raise AnnualAccountsError.unavailable() from None

    @property
    def schema_sha256(self):return _PIN

    def validate_pair(self,main_form: bytes,company_accounts: bytes,*,organization_number: str,income_year: int):
        try:
            inspection=AnnualAccountsDocumentsInspection(_PIN,organization_number,income_year,sha256(main_form).hexdigest(),sha256(company_accounts).hexdigest())
            roots=tuple(_parse(raw) for raw in (main_form,company_accounts))
            for schema,root in zip(self._schemas,roots):schema.assertValid(root)
            for root,key in zip(roots,('mainFormXml','companyAccountsXml')):
                allowed={''}
                for leaf in _PROFILE_LEAVES[key]:
                    parts=leaf.split('/')
                    allowed.update('/'.join(parts[:length]) for length in range(1,len(parts)+1))
                def check(node,path):
                    if path not in allowed or any('{' in attribute for attribute in node.attrib):raise ValueError('RR0002 unsupported profile branch or namespace attribute.')
                    for child in node:check(child,path+'/'+etree.QName(child).localname if path else etree.QName(child).localname)
                check(root,'')
            main,accounts=roots
            if main.tag!='{'+_MAIN_NS+'}melding' or accounts.tag!='{'+_ACCOUNTS_NS+'}melding':raise ValueError()
            ns={'m':_MAIN_NS}
            if (main.findtext('m:Innsender/m:enhet/m:organisasjonsnummer',namespaces=ns)!=organization_number
                    or main.findtext('m:Skjemainnhold/m:regnskapsperiode/m:regnskapsaar',namespaces=ns)!=str(income_year)
                    or main.findtext('m:Skjemainnhold/m:regnskapsperiode/m:regnskapsstart',namespaces=ns)!=str(income_year)+'-01-01'
                    or main.findtext('m:Skjemainnhold/m:regnskapsperiode/m:regnskapsslutt',namespaces=ns)!=str(income_year)+'-12-31'):raise ValueError()
            # Explicit Talli launch subset; the public schema supports more.
            for root,namespace,fields in (
                (main,_MAIN_NS,{'Innsender/enhet/organisasjonsform':'AS','Skjemainnhold/konsern/morselskap':'nei',
                    'Skjemainnhold/regnskapsprinsipper/smaaForetak':'ja',
                    'Skjemainnhold/regnskapsprinsipper/regnskapsreglerSelskap':'nei',
                    'Skjemainnhold/revisjonRegnskapsfoerer/aarsregnskapIkkeRevideres':'ja'}),
                (accounts,_ACCOUNTS_NS,{'Rapport-RR0002U/aarsregnskap/regnskapstype':'S',
                    'Rapport-RR0002U/aarsregnskap/valuta':'NOK','Rapport-RR0002U/aarsregnskap/valoer':'H'})):
                for path,expected in fields.items():
                    if root.findtext('/'.join('{'+namespace+'}'+part for part in path.split('/')))!=expected:raise ValueError()
            return inspection
        except (ValueError,TypeError,KeyError,AttributeError,etree.LxmlError,RecursionError,OverflowError):
            raise AnnualAccountsError.unavailable() from None
