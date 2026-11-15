"""Asynchronous entry point for Pygbag browser builds."""

import asyncio

from engine.engine import Engine
from engine.project import ProjectConfig


async def main():
    project = ProjectConfig.load()
    await Engine(project_config=project).run_async()


asyncio.run(main())
