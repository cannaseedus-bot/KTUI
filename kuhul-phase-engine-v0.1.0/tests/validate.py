from pathlib import Path
import json
from jsonschema import Draft202012Validator
from lxml import etree
ROOT=Path(__file__).resolve().parents[1]
schema=json.loads((ROOT/'schema/micronaut.schema.json').read_text())
example=json.loads((ROOT/'examples/dog.micronaut.json').read_text())
Draft202012Validator.check_schema(schema)
Draft202012Validator(schema).validate(example)
invalid=dict(example); invalid['format']='unknown'
assert not Draft202012Validator(schema).is_valid(invalid)
invalid=dict(example); invalid['phases']=[{'name':'invalid','steps':[]}]
assert not Draft202012Validator(schema).is_valid(invalid)
xsd=etree.XMLSchema(etree.parse(str(ROOT/'schema/micronaut.xsd')))
assert xsd.validate(etree.parse(str(ROOT/'examples/dog.micronaut.xml'))), str(xsd.error_log)
key_schema=json.loads((ROOT/'schema/semantic-key.schema.json').read_text())
Draft202012Validator.check_schema(key_schema)
print('PASS: JSON schema, negative cases, XML XSD, semantic key schema')
