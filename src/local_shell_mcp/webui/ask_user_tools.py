"""Agent-only Ask User tool, separate from LSM's native MCP tool registry."""

ASK_USER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Pause the Agent and ask the user a question before continuing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "description": {"type": "string"},
                    "options": {"type": "array", "items": {
                        "type": "object", "properties": {
                            "label": {"type": "string"}, "value": {"type": "string"},
                        }, "required": ["label", "value"], "additionalProperties": False,
                    }},
                    "multiSelect": {"type": "boolean"},
                },
                "required": ["question"],
                "additionalProperties": False,
            },
        },
    },
]
