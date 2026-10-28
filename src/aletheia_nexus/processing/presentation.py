"""Optional, reversible presentation of model material; never source correction."""

from copy import deepcopy

VERSION = "compact-material/1"
DEFAULTS = {"kind": "paragraph", "uncertain": False, "content_region": "body"}


def presentation_identity(task: dict) -> dict:
    if task.get("material_presentation") != "compact":
        return {}
    return {
        "material_presentation": "compact",
        "material_presentation_version": VERSION,
        "material_block_defaults": deepcopy(DEFAULTS),
    }


def _same_scalar(value, default) -> bool:
    # JSON false must not absorb numeric 0, text "false", or null.
    return type(value) is type(default) and value == default


def compact_material(request: dict) -> dict:
    """Omit exact defaults only; all source values and array order stay intact."""
    result = deepcopy(request)
    material = result["material"]
    if "compact_version" in material or "block_defaults" in material:
        raise ValueError("material already has compact presentation metadata")
    for document in material["documents"]:
        for block in document["blocks"]:
            # model_material always emits these keys, including explicit nulls.
            if any(key not in block for key in DEFAULTS):
                raise ValueError("model block lacks an explicit presentation key")
            for key, default in DEFAULTS.items():
                if _same_scalar(block[key], default):
                    del block[key]
    material.update(compact_version=VERSION, block_defaults=deepcopy(DEFAULTS))
    return result


def decompress_material(request: dict) -> dict:
    """Restore omitted defaults; the full package remains the source of record."""
    result = deepcopy(request)
    material = result["material"]
    defaults = material.get("block_defaults")
    if (
        material.get("compact_version") != VERSION
        or not isinstance(defaults, dict)
        or set(defaults) != set(DEFAULTS)
        or any(not _same_scalar(defaults[k], v) for k, v in DEFAULTS.items())
    ):
        raise ValueError("unsupported compact material presentation")
    for document in material["documents"]:
        for block in document["blocks"]:
            for key, default in defaults.items():
                if key not in block:
                    block[key] = default
    del material["compact_version"]
    del material["block_defaults"]
    return result
