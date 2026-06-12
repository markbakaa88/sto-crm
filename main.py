#!/usr/bin/env python3
"""Compatibility launcher for the packaged STO CRM application.

The implementation lives in the `sto_crm` package; this file is kept so
existing commands, build scripts and PyInstaller continue to use
`python sto_crm.py` as the executable entrypoint.
"""

from sto_crm.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
