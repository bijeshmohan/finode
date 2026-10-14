from pydantic import ValidationError


def validation_message(error: ValidationError) -> str:
    messages = []
    for item in error.errors():
        message = item["msg"].removeprefix("Value error, ")
        field = ".".join(str(part) for part in item["loc"] if not isinstance(part, int))
        messages.append(message if item["type"] == "value_error" or not field else f"{field}: {message}")
    return "; ".join(messages)
