"""Small reviewed retrieval seed set, never a held-out evaluation split.

These are invariant examples over signed commands. They intentionally do not
claim to constrain actual measured motion from a commanded velocity alone.
"""

EXAMPLE_SET_VERSION = "invariants-seed-v1"


def _compare(variable, comparator, value, unit):
    return {"op": "compare", "variable": variable, "comparator": comparator,
            "value": value, "unit": unit}


def _example(identifier, text, expression):
    return {"schema_version": "1.0", "id": identifier, "text": text,
            "expression": expression}


EXAMPLES = (
    _example("command-speed-magnitude", "Keep commanded linear speed at most 0.2 m/s in either direction.",
             {"op": "and", "args": [
                 _compare("command.linear_speed", "le", 0.2, "m/s"),
                 _compare("command.linear_speed", "ge", -0.2, "m/s")]}),
    _example("command-forward-limit", "The signed commanded linear velocity must be below 0.2 m/s.",
             _compare("command.linear_speed", "lt", 0.2, "m/s")),
    _example("school-zone-command-limit", "In school_zone, keep commanded linear speed at most 0.1 m/s in either direction.",
             {"op": "or", "args": [
                 {"op": "not", "arg": {"op": "inside", "region": "school_zone"}},
                 {"op": "and", "args": [
                     _compare("command.linear_speed", "le", 0.1, "m/s"),
                     _compare("command.linear_speed", "ge", -0.1, "m/s")]}]}),
    _example("school-zone-no-reverse-command", "Never command reverse motion in school_zone.",
             {"op": "or", "args": [
                 {"op": "not", "arg": {"op": "inside", "region": "school_zone"}},
                 _compare("command.linear_speed", "ge", 0.0, "m/s")]}),
    _example("loading-area-keepout", "Never let the robot footprint enter or touch loading_area.",
             {"op": "not", "arg": {"op": "inside", "region": "loading_area"}}),
    _example("command-duration", "Each proposed action duration must be at most 0.5 seconds.",
             _compare("command.duration", "le", 0.5, "s")),
)
