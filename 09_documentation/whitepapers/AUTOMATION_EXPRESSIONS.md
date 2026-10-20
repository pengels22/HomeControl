# Automation Expressions and Templates

HCM uses one bounded expression engine for native expressions, the supported
Home Assistant/Jinja subset, template conditions, variables, and service data.
Source is parsed into an explicit normalized AST and interpreted by an
allowlist evaluator. It never uses `eval`, `exec`, imports, Python object
traversal, filesystem access, network access, or provider code.

Native expressions use ordinary literals, names, calls, arithmetic, comparison,
boolean, membership, conditional, list/mapping, indexing, and controlled mapping
or trigger snapshot access. Jinja compatibility uses `{{ ... }}` and mixed text
templates. Supported filters/functions include `states`, `is_state`,
`state_attr`, `int`, `float`, `string`, `bool`, `default`, `lower`, `upper`,
`trim`, `replace`, `length`, `first`, `last`, `join`, `min`, `max`, `round`,
`abs`, `now`, `utcnow`, `today_at`, `duration`, `as_timestamp`,
`as_datetime`, and `as_local`. Undefined values are explicit, compare false,
render as an empty string, and can be handled with `default`.

Entity helpers resolve user-facing entity IDs through the current registry while
automations retain immutable entity references. Trigger, event, state snapshot,
run, and run-local variable mappings are read-only to expressions. Variables
are declaration-order and run-local; service results may be assigned with
`response_variable` for later actions. Service arguments are rendered before
normal Service Registry schema and ownership validation. Dry runs evaluate these
values without invoking services.

The evaluator enforces source, AST, nesting, collection, cache, and rendered
output limits. Errors are categorized as parse, unsupported, unknown function,
type, conversion, or resource-limit failures. The authenticated
`POST /api/v1/expressions/test` endpoint returns validity, bounded AST,
result type, dependencies, and sanitized errors without side effects.

| Compatibility | Status |
|---|---|
| `{{ ... }}` pure and mixed templates | Supported |
| state helpers and common scalar filters | Supported |
| trigger state/event access | Supported |
| bounded date/time and duration helpers | Supported |
| `{% if %}`, loops, macros, includes, arbitrary Jinja | Unsupported |
| Python methods, private attributes, imports, I/O | Unsupported |
| Dynamic entity targets and expression service calls | Unsupported |

The October 2026 real configuration audit covered 125 automations, 7 scripts,
and 4 scenes. It found 74 template-bearing values: 33 compile with the
bounded engine after this pass and 41 remain unsupported. The measured safe
expansions are top-level list/scalar filter chains (including filters followed
by comparisons) and the `is none`/`is not none` tests. These are normalized to
the existing AST and allowlist; they do not add Jinja execution. The remaining
failures are intentionally deferred: 21 control-block templates (`set`,
`for`, or multi-branch blocks), 8 parse forms outside the subset, 5 dynamic
`random` uses, 4 empty/unsupported call forms, and 3 collection/attribute
filter chains (`selectattr`, `map`, or equivalent). No control blocks, random
selection, arbitrary methods, or provider/service calls are enabled.
