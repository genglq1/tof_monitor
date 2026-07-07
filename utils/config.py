import yaml
import os

def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    def replace_env(value):
        if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
            return os.environ.get(value[2:-1], '')
        elif isinstance(value, dict):
            return {k: replace_env(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [replace_env(v) for v in value]
        return value
    return replace_env(config)