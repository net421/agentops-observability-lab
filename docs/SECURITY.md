# Security and trust boundary

## Threat model

The most sensitive asset is the trace database: prompts, model identifiers, errors and tool activity may contain confidential context. This repository therefore defaults to local files and does not upload traces.

## Controls

- No credentials or network clients are required.
- Dataclass validation rejects negative counts, invalid scores and inconsistent token totals.
- SQLite foreign keys are enabled.
- Dynamic table access is allow-listed.
- Read surfaces use SQLite URI `mode=ro` and `PRAGMA query_only=ON`.
- The sidecar exposes no write tool and no arbitrary SQL interface.
- Paths must resolve to existing regular files.
- Generated databases and evidence are ignored by Git.
- CI scans the public tree for common secret formats and forbidden runtime state.

## Limitations

Read-only SQLite does not redact sensitive rows. Operators remain responsible for access control, filesystem permissions, retention and redaction. Quality scores are configured measurements, not proof that an agent is safe or correct.
