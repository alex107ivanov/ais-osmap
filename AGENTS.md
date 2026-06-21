# AGENTS.md

## Scope
These instructions apply to the whole repository.

## Project overview
- This is a small Python project that receives AIS NMEA messages over UDP, decodes them, stores recent vessel state, and renders a simple web map.
- Favor small, readable modules over framework-heavy structure.

## Conventions
- Keep dependencies minimal.
- Prefer the Python standard library where practical.
- Use SQLite for local persistence.
- Keep runtime behavior configurable through module-level constants or environment variables.
- Write focused tests for parsing, persistence, TTL cleanup, and track handling.

## Editing guidance
- Preserve the simple local-developer workflow.
- Avoid introducing background schedulers or external services unless explicitly requested.
- If frontend changes are needed, keep them lightweight and easy to inspect.
