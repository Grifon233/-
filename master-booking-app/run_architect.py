#!/usr/bin/env python3
import sys
import asyncio
sys.path.insert(0, '/var/www/master-booking')

from architect.main import main

if __name__ == '__main__':
    asyncio.run(main())