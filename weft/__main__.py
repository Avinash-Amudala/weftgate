"""``python -m weft`` is the same as the ``weft`` console script."""

from .cli import main

raise SystemExit(main())
