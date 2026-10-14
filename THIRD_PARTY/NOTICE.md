# Upstream attribution

Architecture inspiration: Setasoma, mycodo-hermes-skill.
Repository: https://github.com/setasoma/mycodo-hermes-skill
Inspected commit: 7069cb0cec6f84116f77ca567fe6d24065db34c8
License: MIT; original copyright and license retained in upstream-LICENSE.

This is a clean, standard-library-only rewrite for Jeff Wu's SCD41/Pi 5 A box, not an upstream installation. No upstream executable shell entrypoints, GPIO helpers, credential files, species thresholds, camera modules or schedules are copied into the runtime.

Concepts retained: sensor acquisition → species configuration → safety gates → decision planning → reporting. Replaced YAML/PyYAML with JSON, direct Flux querying with database-independent Mycodo measurement GET, phase inference with explicitly unconfigured species settings, and execution/follow-up with an immutable dry-run boundary. There is no legacy threshold fallback.

Mycodo interface reference: locally supplied official v8.17.0 source, mycodo/mycodo_flask/app.py (X-API-KEY base64 decoding), api/measurement.py (last measurement route), api/sql_schema_fields.py (output_id), plus operator's saved GET report. No claim is made about the running InfluxDB version or deployment of Pi-side safety Functions.
