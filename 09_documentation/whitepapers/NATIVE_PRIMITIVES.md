# Native Helpers, Scripts, and Scenes

HCM native primitives use the internal `hcm_native` provider only as an
ownership boundary. Definitions are durable in migration 019; state and
availability remain ordinary integration entities and durable entity events.
No primitive writes GPIO or calls a third-party provider directly.

Helpers include `input_boolean`, `input_button`, `input_number`, `input_text`,
`input_select`, `input_datetime`, `counter`, `timer`, and weekly `schedule`.
Their mutation services are registered through the normal Service Registry and
are virtual (`physical_mutation=false`). Timer state and expected finish are
persisted in entity attributes. Active timers are reconstructed after restart,
finish once if their deadline passed while HCM was offline, and paused timers
remain paused. Schedule helpers compute their next weekly transition in the HCM
timezone and own one cancellable task.

Scripts reuse the Automation action runner, modes, expression context, traces,
and run limits. Typed primitive inputs support required/default/type/options
validation. Script runs use the shared run table with `run_kind=script`, expose
`script.run`, and cap nested calls at five levels. Interrupted runs do not
resume after restart. Script calls use the normal service path.

Scenes store deterministic target entity references and desired state/attributes.
Snapshot scenes capture current normalized state and can be activated through
`scene.turn_on`; each target reports success or failure so partial results are
visible. Scene activation resolves ownership and invokes semantic services; it
does not mutate provider state directly. Static scene expression templating,
full domain-specific attribute translation, and importer/UI work remain future
phases.

Authenticated APIs expose `/api/v1/helpers`, `/api/v1/scripts`, and
`/api/v1/scenes`. READONLY users inspect; ADMIN users mutate, run scripts, and
activate scenes. Deletion rejects helper references from automations and native
entity deletion is restricted by the database.
