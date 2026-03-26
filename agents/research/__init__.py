"""Research team agents for the multi-agent chatbot eval platform.

This package contains agents specializing in evaluation research:
- EvalResearcher: Evaluation metrics research and implementation design.
- MLResearcher: LLM-as-Judge, embeddings, and pipeline design.
- LiteratureReviewer: Academic literature analysis and gap identification.
"""

from agents.research.eval_researcher import EvalResearcher, create_eval_researcher
from agents.research.literature_reviewer import LiteratureReviewer, create_literature_reviewer
from agents.research.ml_researcher import MLResearcher, create_ml_researcher

__all__ = [
    "EvalResearcher",
    "MLResearcher",
    "LiteratureReviewer",
    "create_eval_researcher",
    "create_ml_researcher",
    "create_literature_reviewer",
]
