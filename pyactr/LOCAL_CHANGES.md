# Local DM edition of pyactr 0.3.2

Upstream: https://github.com/jakdot/pyactr
Author: Jakub Dotlačil and upstream contributors.
License: GNU GPL version 3, see `LICENSE` (preserved verbatim).
Source baseline: the pyactr 0.3.2 wheel from PyPI.
Local modification date: 2026-10-12.

This repository includes the Python sources, upstream tests and license. Imports
resolve this local `pyactr/` directory when the application is launched from the
repository, so no separate pyactr installation is required.

The public declarative-memory API consistently uses `DM`, `DMBuffer`, `model.dm`,
`model.dms` and `model.set_dm(data)`. Internal references, private buffer field
names, documentation and tests use the same vocabulary. The existing
`Buffer.dm` property is reused by the retrieval buffer; the per-buffer memory
mapping in `ACTRModel.simulation` has a distinct local name to avoid shadowing.

Modified upstream files: `declarative.py`, `model.py`, `productions.py`,
`tests/modeltests.py`, `tests/tests.py`. Cognitive equations and default parameter
values are unchanged. The application's optional performance overrides validate
the imported module's version, including this bundled edition.

External model files must use this DM API. The unmodified PyPI edition uses a
different public API. Do not replace this directory with a pip package without
also migrating callers and the optional performance overrides.

Verification: `python -m unittest pyactr.tests.tests`.
