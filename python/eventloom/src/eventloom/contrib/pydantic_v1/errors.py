"""Errors raised by `eventloom.contrib.pydantic_v1`."""


class PartialStreamValidationError(RuntimeError):
    """Raised by `ProviderStreamClient.stream()`/`.create()` when the fully
    accumulated stream still isn't parseable JSON, or doesn't satisfy
    `response_model`, once the underlying token stream has ended.

    Only raised by the final-validation step (`validate_final=True`, the
    default) — every intermediate partial yielded during streaming is always
    best-effort and never raises on its own account.
    """
