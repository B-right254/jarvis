"""
Smoke-test: verify TOOL_SCHEMAS is importable with expected structure.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from tools import TOOL_REGISTRY, TOOL_SCHEMAS

assert len(TOOL_SCHEMAS) > 0, "No tool schemas loaded"
assert len(TOOL_REGISTRY) > 0, "No tool implementations registered"

schema_names = {s["function"]["name"] for s in TOOL_SCHEMAS}
registry_names = set(TOOL_REGISTRY.keys())

# Every schema should have a matching registry entry
assert schema_names == registry_names, (
    f"Mismatch: schemas without impl: {schema_names - registry_names}, "
    f"impl without schema: {registry_names - schema_names}"
)

print(f"[OK] TOOL_SCHEMAS: {len(TOOL_SCHEMAS)} tools — {sorted(schema_names)}")
print("[OK] TOOL_REGISTRY matches TOOL_SCHEMAS")
