"""Clean fixture. No check is expected to fire on this file."""


def add(left: int, right: int) -> int:
    return left + right


def greet(name: str) -> str:
    return f"hello {name}"
