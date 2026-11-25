"""Fail-closed Micronaut Jinja -> AIML 2.0 routing compiler.
Usage: python compile_micronaut.py input.json output.aiml
Requires: pip install jinja2
"""
import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def compile_file(source, output, template_path=None):
    source, output = Path(source), Path(output)
    template_path = Path(template_path or Path(__file__).with_name('micronaut.jinja'))
    data = json.loads(source.read_text(encoding='utf-8'))
    env = Environment(loader=FileSystemLoader(str(template_path.parent)),
                      extensions=['jinja2.ext.do'], undefined=StrictUndefined,
                      autoescape=False)
    module = env.get_template(template_path.name).make_module()
    xml = module.render_brain(data)
    errors = [x for x in module.compiler_diagnostics().split("|||") if x]
    if errors:
        raise ValueError('Micronaut compilation rejected:\n- ' + '\n- '.join(errors))
    root = ET.fromstring(xml)
    if root.tag != 'aiml' or root.attrib.get('version') != '2.0':
        raise ValueError('Expected AIML 2.0 root')
    for category in root.findall('category'):
        if len(category.findall('pattern')) != 1 or len(category.findall('template')) != 1:
            raise ValueError('Invalid AIML category structure')
    output.write_text(xml, encoding='utf-8')
    return output

if __name__ == '__main__':
    if len(sys.argv) not in (3, 4):
        sys.exit('Usage: python compile_micronaut.py input.json output.aiml [micronaut.jinja]')
    try:
        print(compile_file(*sys.argv[1:]))
    except (ValueError, KeyError, TypeError) as exc:
        sys.exit(str(exc))
