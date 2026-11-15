"""Asynchronous entry point for Pygbag browser builds."""

import asyncio
import pygame
import pygame.surface

from engine.engine import Engine
from engine.project import ProjectConfig


project = ProjectConfig.load()
engine = Engine(project_config=project)
# Pygbag expects Pygame and the display to be ready before its async loop starts.
engine.initialize()


async def main():
    engine.running = True
    try:
        await engine.play_intro_async()
        while engine.running:
            engine.step()
            engine.clock.tick(engine.fps)
            await asyncio.sleep(0)
    finally:
        engine.shutdown()


asyncio.run(main())
