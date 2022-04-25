from pathlib import Path

import yaml

from cmsaoi.rule import registered_rules


class AOITag:
    def __init__(self, base_directory, tag, rule_type, value):
        self.tag = tag
        self.rule_type = rule_type
        self.value = value
        self.base_directory = base_directory


def register_tag(tag, rule_type):
    def on_tag(loader, node):
        return AOITag(Path(loader.name).parent, tag, rule_type, node.value)

    yaml.SafeLoader.add_constructor(tag, on_tag)


for tag, rule_type in registered_rules.items():
    register_tag(tag, rule_type)


def load_yaml(fname):
    return _load_yaml_internal(fname)


def _load_yaml_internal(fname):
    content = Path(fname).read_text()
    loader = yaml.SafeLoader(content)
    loader.name = fname
    try:
        return loader.get_single_data() or {}
    finally:
        loader.dispose()
