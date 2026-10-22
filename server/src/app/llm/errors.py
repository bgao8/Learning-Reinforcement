"""Typed errors: ModelError base + ModelTimeout, ModelUnavailable, InvalidOutput."""
from dataclasses import dataclass

class ModelError(Exception):
    """Something went wrong when talking to a model."""


class ModelTimeout(ModelError):
    """The model took too long."""


class ModelUnavailable(ModelError):
    """Couldn't reach the model (network down, Ollama down, bad API key)."""


class InvalidOutput(ModelError):
    """Model ran, but returned invalid JSON or didn't match the schema."""

    def __init__(self, reason: str, raw_text: str):
        super().__init__(reason)
        self.raw_text = raw_text