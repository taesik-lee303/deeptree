import json
import os
import logging
from jsonschema import Draft202012Validator
from functools import lru_cache

logger = logging.getLogger(__name__)

@lru_cache(maxsize=16)
def load_schema(schema_name: str):
    base = os.path.join(os.path.dirname(__file__), "..", "..", "pipelines", "kafka", "config", "schemas")
    path = os.path.abspath(os.path.join(base, schema_name))
    with open(path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    Draft202012Validator.check_schema(schema)
    return schema

def validate(instance: dict, schema_name: str):
    schema = load_schema(schema_name)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: e.path)
    if errors:
        msg = "; ".join([f"{'/'.join([str(p) for p in err.path])}: {err.message}" for err in errors])
        raise ValueError(f"Schema validation failed: {msg}")
