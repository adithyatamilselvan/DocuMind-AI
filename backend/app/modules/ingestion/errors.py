class PermanentError(Exception):
    """Unrecoverable (corrupt/encrypted file...). The message is shown to the user."""


class RetryableError(Exception):
    """Transient failure (provider timeout, network)."""


class RetryLater(Exception):  # noqa: N818
    def __init__(self, countdown: int) -> None:
        super().__init__(f"retry in {countdown}s")
        self.countdown = countdown


class DocumentGone(Exception):  # noqa: N818
    """Document was deleted while processing."""
