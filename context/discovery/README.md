# Discovery Rules

Date-stamped, point-in-time audits of the repo. Not canonical — treat as
historical context.

## Rotation Rule

Files older than 30 days, or whose findings are all RESOLVED or have been
promoted to a living artifact (e.g. `context/tasks.md`) move to
`context/.archive/` (named per `context/.archive/README.md`). Open findings
migrate to `context/tasks.md` before archiving.

This rotation is best-effort — nothing enforces it automatically. Any session
that opens this directory should check whether the contents are still current
and either re-date the file (with a fresh "Status" header), promote findings to
`tasks.md`, or archive.
