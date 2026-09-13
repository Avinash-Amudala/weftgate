"""``python -m weftgate`` is the same as the ``weftgate`` console script."""

from .cli import main

raise SystemExit(main())
