"""Typed errors: ModelError base + ModelTimeout, ModelUnavailable, InvalidOutput."""
from dataclasses import dataclass

class ModelError(Exception):
    """Something went wrong when talking to a model."""


class ModelTimeout(ModelError):
    """The model took too long."""


class ModelUnavailable(ModelError):
    """Couldn't reach the model (network down, Ollaa down, bad API key)."""


class InvalidOutput(ModelError):
    """Model reply was incorrectly typed."""