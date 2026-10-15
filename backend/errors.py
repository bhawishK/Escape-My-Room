"""Requests the service refuses with a message meant for the user."""


class Refusal(Exception):
    """The request cannot be accepted; the message is shown to the user with this HTTP status."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status
