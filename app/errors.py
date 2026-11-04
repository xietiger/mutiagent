from __future__ import annotations


class ConsoleError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "bad_request"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


class ContractError(ConsoleError):
    def __init__(self, message: str):
        super().__init__(message, status=422, code="invalid_contract")
