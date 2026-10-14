"""Allow running PAGAN as `python -m pagan`."""

import sys

from pagan.cli import main

sys.exit(main())
