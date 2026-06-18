import os
import logging
from google.cloud import firestore

logger = logging.getLogger(__name__)

FIRESTORE_DATABASE = os.environ.get("FIRESTORE_DATABASE", "badminton-bot-memory")

_db = firestore.Client(database=FIRESTORE_DATABASE)
_COLLECTION = "chat_memories"


def remember(chat_id: int, fact: str) -> None:
    """Appends a fact to the persistent memory for a chat."""
    doc_ref = _db.collection(_COLLECTION).document(str(chat_id))
    doc_ref.set({"facts": firestore.ArrayUnion([fact])}, merge=True)


def get_memories(chat_id: int) -> list[str]:
    """Returns all remembered facts for a chat, oldest first. Empty list if none."""
    doc = _db.collection(_COLLECTION).document(str(chat_id)).get()
    if not doc.exists:
        return []
    return doc.to_dict().get("facts", [])
