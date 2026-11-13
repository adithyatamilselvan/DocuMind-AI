class LLMError(Exception):
    """Base class for LLM failures. `message` is safe to show to users."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable


class LLMNotConfiguredError(LLMError):
    def __init__(self) -> None:
        super().__init__("The AI assistant is not configured on the server (missing API key).")


class LLMRefusalError(LLMError):
    def __init__(self, category: str | None = None) -> None:
        super().__init__("The model declined to answer this request.")
        self.category = category
