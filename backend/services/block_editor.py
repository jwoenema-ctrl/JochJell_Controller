"""Block identifiers and reference-aware layout editing."""
import re


def block_id(value):
    value = str(value).strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_-]{0,31}", value):
        raise ValueError("Block ID must start with a letter and contain at most 32 letters, digits, hyphens or underscores")
    return value


def next_block_id(blocks):
    numbers = [int(match.group(1)) for block in blocks
               if (match := re.fullmatch(r"B(\d+)", str(block["id"]).upper()))]
    return f"B{max(numbers, default=0) + 1:02d}"


def rename_references(value, old, new, key=""):
    """Rewrite structural references, never labels or unrelated entity IDs."""
    singles = {"block_id", "blockId", "current_block_id", "destination_block_id",
               "protects_block_id", "entry_block_id", "straight_block_id",
               "diverging_block_id", "aligned_block_id", "from", "to", "alternate",
               "source", "target", "from_block_id", "to_block_id", "source_id", "target_id",
               "protects", "position"}
    multiples = {"neighbor_ids", "neighborIds", "block_ids", "blockIds",
                 "connected_block_ids", "connected_node_ids", "connected", "route"}
    if isinstance(value, dict):
        return {k: rename_references(v, old, new, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [new if key in multiples and isinstance(v, str) and v.upper() == old
                else rename_references(v, old, new) for v in value]
    return new if key in singles and isinstance(value, str) and value.upper() == old else value
