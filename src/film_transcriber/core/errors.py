"""Safe domain errors exposed by the API and CLI."""


class AppError(Exception):
    """An actionable error without internal paths or media content."""

    def __init__(self, category: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.status_code = status_code
