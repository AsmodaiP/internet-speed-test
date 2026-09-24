"""Allow ``python -m netmeter URL`` without installing the console script."""

from netmeter.cli import main

raise SystemExit(main())
