import asyncio
import os
import sys

from master_bot.main import main

if len(sys.argv) == 1 and os.getenv("MASTER_BOT_TOKEN"):
    sys.argv.append(os.environ["MASTER_BOT_TOKEN"])

asyncio.run(main())
