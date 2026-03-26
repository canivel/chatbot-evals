"""SQLAlchemy models for the chatbot-evals platform.

Importing this package ensures all models are registered with the
declarative ``Base`` so that Alembic and ``create_all`` work correctly.
"""

from evalplatform.api.models.base import Base, get_db, init_db, close_db
from evalplatform.api.models.connector import Connector, ConnectorType
from evalplatform.api.models.conversation import Conversation, ConversationMessage
from evalplatform.api.models.eval_result import EvalResult
from evalplatform.api.models.eval_run import EvalRun, EvalRunStatus
from evalplatform.api.models.organization import Organization
from evalplatform.api.models.user import User

__all__ = [
    "Base",
    "close_db",
    "Connector",
    "ConnectorType",
    "Conversation",
    "ConversationMessage",
    "EvalResult",
    "EvalRun",
    "EvalRunStatus",
    "get_db",
    "init_db",
    "Organization",
    "User",
]
