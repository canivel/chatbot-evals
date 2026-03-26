"""Product Manager agent package.

Exports the main agent class and supporting components.
"""

from .agent import PMAgent
from .backlog import BacklogManager, SprintPlan
from .story_generator import StoryGenerator

__all__ = [
    "PMAgent",
    "BacklogManager",
    "SprintPlan",
    "StoryGenerator",
]
