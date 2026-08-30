# Minimal external counter example

The bundled `plugin/counter` implementation is the executable example for one
distribution combining API, automation, core storage, and declarative UI. An
external repository uses the same files with its own `pyproject.toml`:

```text
open-cinema-counter/
├── pyproject.toml
├── src/open_cinema_counter/
│   ├── __init__.py
│   ├── plugin.py
│   └── open-cinema-plugin.toml
└── tests/test_contract.py
```

The manifest declares `counter.api`, `counter.automation`, and
`counter.admin`. The runtime exposes only `/api/plugins/counter/*`, stores one
bounded `counter.state` document with optimistic concurrency, and contributes
an overview page whose actions use typed endpoints. It has no Django model,
custom CSS, JavaScript bundle, audio backend, or host command.

Copy the bundled implementation, change distribution/publisher/version source
metadata, and keep every runtime ID in the `counter.*` namespace. Validate the
source checkout and built wheel with `assert_plugin_contract` as shown in the
author guide. The Open Cinema test suite exercises this exact public helper
against independent source and wheel fixtures.
