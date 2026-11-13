from enum import StrEnum


class DocumentStatus(StrEnum):
    UPLOADING = "UPLOADING"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    EXTRACTING = "EXTRACTING"
    OCR_PROCESSING = "OCR_PROCESSING"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


S = DocumentStatus

# Allowed transitions. OCR is optional (EXTRACTING may skip straight to CHUNKING).
# FAILED -> QUEUED is the retry path; COMPLETED -> QUEUED is re-processing (e.g. re-embedding).
TRANSITIONS: dict[DocumentStatus, set[DocumentStatus]] = {
    S.UPLOADING: {S.QUEUED, S.FAILED},
    S.QUEUED: {S.PROCESSING, S.FAILED},
    S.PROCESSING: {S.EXTRACTING, S.FAILED},
    S.EXTRACTING: {S.OCR_PROCESSING, S.CHUNKING, S.FAILED},
    S.OCR_PROCESSING: {S.CHUNKING, S.FAILED},
    S.CHUNKING: {S.EMBEDDING, S.FAILED},
    S.EMBEDDING: {S.INDEXING, S.FAILED},
    S.INDEXING: {S.COMPLETED, S.FAILED},
    S.COMPLETED: {S.QUEUED},
    S.FAILED: {S.QUEUED},
}

IN_PROGRESS = {
    S.UPLOADING, S.QUEUED, S.PROCESSING, S.EXTRACTING, S.OCR_PROCESSING,
    S.CHUNKING, S.EMBEDDING, S.INDEXING,
}  # fmt: skip


def can_transition(current: DocumentStatus, new: DocumentStatus) -> bool:
    return new in TRANSITIONS[current]
