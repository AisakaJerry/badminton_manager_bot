import logging
from google.cloud import firestore
from memory_store import FIRESTORE_DATABASE

logger = logging.getLogger(__name__)

_db = firestore.Client(database=FIRESTORE_DATABASE)
_COLLECTION = "media_groups"


def add_photo(chat_id: int, media_group_id: str, message_id: int, file_id: str) -> None:
    """Records one photo of an album, so a later reply to any photo in it can recover all of them."""
    doc_ref = _db.collection(_COLLECTION).document(f"{chat_id}_{media_group_id}")
    doc_ref.set(
        {"photos": firestore.ArrayUnion([{"message_id": message_id, "file_id": file_id}])},
        merge=True,
    )


def get_file_ids(chat_id: int, media_group_id: str) -> list[str]:
    """Returns the file_ids of every known photo in the album, in send order. Empty list if none cached."""
    doc = _db.collection(_COLLECTION).document(f"{chat_id}_{media_group_id}").get()
    if not doc.exists:
        return []
    photos = sorted(doc.to_dict().get("photos", []), key=lambda p: p["message_id"])
    return [photo["file_id"] for photo in photos]
