# Python environment constraints

`v10-python-3.10.txt` selects the model and test dependency closure active in
the verified V10 Python 3.10.12 environment. The versions were reconciled
against
`deliverables/current/2026-09-02_v10/environment/python_packages.txt` and the
active distributions reported by `importlib.metadata` on the packaging host.

This is a pip constraints file, not a universal or cryptographically locked
environment:

- it constrains packages requested by the editable project installation;
- it intentionally excludes unrelated packages from the captured host;
- it carries no wheel or source-distribution hashes;
- operating-system, CPU architecture, Python patch version, LaTeX, fonts,
  LibreOffice, and Node are outside its scope;
- V10's own archives and environment records remain immutable and authoritative.

Use the file with Python 3.10 as documented in `docs/HANDOFF.md`. Review and
re-test before adopting it on another Python minor version or platform.
