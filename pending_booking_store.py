import logging
import uuid
from google.cloud import firestore
from memory_store import FIRESTORE_DATABASE

logger = logging.getLogger(__name__)

_db = firestore.Client(database=FIRESTORE_DATABASE)
_COLLECTION = "pending_bookings"


def save(chat_id: int, user_id: int, booking: dict, messages_to_delete: list[int]) -> str:
    """Stores a booking awaiting Confirm/Cancel and returns its id (embedded in the buttons' callback_data).

    Kept in Firestore rather than ConversationHandler state because the button click may land on a
    different Cloud Run instance, or after this one has scaled to zero.
    """
    booking_id = uuid.uuid4().hex[:16]
    _db.collection(_COLLECTION).document(booking_id).set({
        "chat_id": chat_id,
        "user_id": user_id,
        "booking": booking,
        "messages_to_delete": messages_to_delete,
        "created_at": firestore.SERVER_TIMESTAMP,
    })
    return booking_id


@firestore.transactional
def _pop_in_transaction(transaction, doc_ref):
    snapshot = doc_ref.get(transaction=transaction)
    if not snapshot.exists:
        return None
    transaction.delete(doc_ref)
    return snapshot.to_dict()


def pop(booking_id: str) -> dict | None:
    """Atomically fetches and deletes a pending booking, so a double-click can't create two events.

    Returns None if it was already confirmed/canceled (or never existed).
    """
    doc_ref = _db.collection(_COLLECTION).document(booking_id)
    return _pop_in_transaction(_db.transaction(), doc_ref)
