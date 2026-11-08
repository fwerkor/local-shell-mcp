"""Source port of LibreChat's Ask User tool schema and resume validation.

Reference: LibreChat e8f3be08, agents/hitl/askUserQuestionTool.ts and
agents/hitl/resume.ts; SDK @librechat/agents 4.0.1 askUserQuestions.ts.
Schema equality and resume behavior are compared against exported original
functions in tests/fixtures/librechat. No React contract is redefined here.
"""
from __future__ import annotations

import re
from typing import Any

ASK_USER_QUESTION_TOOL_NAME = "ask_user_question"
ASK_USER_QUESTION_DEFINITION = {'name': 'ask_user_question',
 'description': 'Ask the user one to four related clarifying questions and pause the run until '
                "they answer; their answers are returned as this tool's result, keyed by each "
                'question id. Use it only when you are genuinely blocked on decisions you cannot '
                'resolve from the conversation or your other tools. Put every related question in '
                'this ONE tool call, and NEVER call this tool in parallel with any other tool '
                'call. Use stable, concise ids matching [A-Za-z][A-Za-z0-9_-]{0,63}. When the '
                'realistic answers are enumerable, provide 2-6 concise options; set multiSelect to '
                'true only when several options may sensibly apply at once (the selected option '
                'values are returned joined by ", "). Keep every option label within 280 '
                'characters and put supporting context in the question description. The user can '
                'always type a free-form answer instead — so do NOT include a catch-all option '
                "like 'Other' or 'Something else': the answer UI always offers free-form input on "
                'its own.',
 'schema': {'type': 'object',
            'properties': {'questions': {'type': 'array',
                                         'minItems': 1,
                                         'maxItems': 4,
                                         'description': 'One to four related questions presented '
                                                        'in one interaction.',
                                         'items': {'type': 'object',
                                                   'properties': {'id': {'type': 'string',
                                                                         'pattern': '^[A-Za-z][A-Za-z0-9_-]{0,63}$',
                                                                         'description': 'Unique '
                                                                                        'answer '
                                                                                        'key for '
                                                                                        'this '
                                                                                        'question.'},
                                                                  'header': {'type': 'string',
                                                                             'minLength': 1,
                                                                             'maxLength': 80,
                                                                             'description': 'Optional '
                                                                                            'short '
                                                                                            'heading '
                                                                                            'shown '
                                                                                            'above '
                                                                                            'the '
                                                                                            'question.'},
                                                                  'question': {'type': 'string',
                                                                               'minLength': 1,
                                                                               'maxLength': 2000,
                                                                               'description': 'One '
                                                                                              'clarifying '
                                                                                              'question '
                                                                                              'to '
                                                                                              'ask '
                                                                                              'the '
                                                                                              'user.'},
                                                                  'description': {'type': 'string',
                                                                                  'maxLength': 4000,
                                                                                  'description': 'Optional '
                                                                                                 'context '
                                                                                                 'rendered '
                                                                                                 'alongside '
                                                                                                 'the '
                                                                                                 'question.'},
                                                                  'options': {'type': 'array',
                                                                              'maxItems': 12,
                                                                              'description': 'Optional '
                                                                                             'pre-defined '
                                                                                             'choices. '
                                                                                             'Omit '
                                                                                             'for '
                                                                                             'free-form '
                                                                                             'only.',
                                                                              'items': {'type': 'object',
                                                                                        'properties': {'label': {'type': 'string',
                                                                                                                 'minLength': 1,
                                                                                                                 'maxLength': 280,
                                                                                                                 'description': 'Short '
                                                                                                                                'choice '
                                                                                                                                'shown '
                                                                                                                                'to '
                                                                                                                                'the '
                                                                                                                                'user. '
                                                                                                                                'Maximum '
                                                                                                                                '280 '
                                                                                                                                'characters; '
                                                                                                                                'put '
                                                                                                                                'supporting '
                                                                                                                                'context '
                                                                                                                                'in '
                                                                                                                                'the '
                                                                                                                                'question '
                                                                                                                                'description.'},
                                                                                                       'value': {'type': 'string',
                                                                                                                 'minLength': 1,
                                                                                                                 'maxLength': 500,
                                                                                                                 'description': 'Value '
                                                                                                                                'returned '
                                                                                                                                'if '
                                                                                                                                'this '
                                                                                                                                'option '
                                                                                                                                'is '
                                                                                                                                'picked.'}},
                                                                                        'required': ['label',
                                                                                                     'value']}},
                                                                  'multiSelect': {'type': 'boolean',
                                                                                  'description': 'Allow '
                                                                                                 'several '
                                                                                                 'option '
                                                                                                 'values '
                                                                                                 'for '
                                                                                                 'this '
                                                                                                 'question.'}},
                                                   'required': ['id', 'question']}}},
            'required': ['questions']}}

ASK_USER_TOOLS = [{"type": "function", "function": {
    "name": ASK_USER_QUESTION_DEFINITION["name"],
    "description": ASK_USER_QUESTION_DEFINITION["description"],
    "parameters": ASK_USER_QUESTION_DEFINITION["schema"],
}}]
_QUESTION_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


def _string_length(value: str) -> int:
    # JavaScript/Zod use UTF-16 code units, including for astral characters.
    return len(value.encode("utf-16-le", errors="surrogatepass")) // 2


def _question(value: Any, *, batch: bool) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Invalid Ask User question")
    result = {}
    fields = {"question": (1, 2000), "description": (0, 4000)}
    if batch:
        fields["header"] = (1, 80)
        identity = value.get("id")
        if not isinstance(identity, str) or not _QUESTION_ID.fullmatch(identity):
            raise ValueError("Invalid Ask User question id")
        result["id"] = identity
    for field, (minimum, maximum) in fields.items():
        if field not in value and field != "question":
            continue
        text = value.get(field)
        if not isinstance(text, str) or not minimum <= _string_length(text) <= maximum:
            raise ValueError(f"Invalid Ask User {field}")
        result[field] = text
    if "options" in value:
        options = value["options"]
        if not isinstance(options, list) or len(options) > 12:
            raise ValueError("Invalid Ask User options")
        result["options"] = []
        for item in options:
            if not isinstance(item, dict):
                raise ValueError("Invalid Ask User option")
            cleaned = {}
            for name, limit in (("label", 280), ("value", 500)):
                text = item.get(name)
                if not isinstance(text, str) or not 1 <= _string_length(text) <= limit:
                    raise ValueError("Invalid Ask User option")
                cleaned[name] = text
            result["options"].append(cleaned)
    if "multiSelect" in value:
        if type(value["multiSelect"]) is not bool:
            raise ValueError("Invalid Ask User multiSelect")
        result["multiSelect"] = value["multiSelect"]
    return result


def build_ask_user_payload(arguments: Any, tool_call_id: str) -> dict:
    if not isinstance(arguments, dict):
        raise ValueError("Invalid Ask User arguments")
    # The upstream factory first tries its legacy schema for rolling-deploy
    # checkpoint replay, even when an object also contains unknown batch keys.
    if "question" in arguments:
        try:
            legacy = _question(arguments, batch=False)
        except ValueError:
            pass
        else:
            return {"type": ASK_USER_QUESTION_TOOL_NAME, "question": legacy,
                    "tool_call_id": tool_call_id}
    values = arguments.get("questions")
    if not isinstance(values, list) or not 1 <= len(values) <= 4:
        raise ValueError("Ask User requires one to four questions")
    questions = [_question(value, batch=True) for value in values]
    if len({q["id"] for q in questions}) != len(questions):
        raise ValueError("Question ids must be unique.")
    first = {name: value for name, value in questions[0].items() if name not in {"id", "header"}}
    return {"type": ASK_USER_QUESTION_TOOL_NAME, "question": first,
            "questions": questions, "tool_call_id": tool_call_id}


def resolve_ask_user_question_resume(payload: dict, body: dict) -> dict:
    """Port resolveAskUserQuestionResume, including its error ordering."""
    def error(message):
        return {"status": 400, "error": message}

    questions = payload.get("questions")
    if not isinstance(questions, list):
        answer = body.get("answer")
        if not isinstance(answer, str) or len(answer) == 0:
            return error("An answer is required")
        if _string_length(answer) > 16000:
            return error("Answer exceeds the maximum length")
        return {"resumeValue": {"answer": answer}}
    if not 1 <= len(questions) <= 4:
        return error("The pending question batch is invalid")
    submitted = body.get("answers")
    if not isinstance(submitted, dict):
        return error("Answers are required for every question")
    answers = {}
    for question in questions:
        identity = question.get("id") if isinstance(question, dict) else None
        if not isinstance(identity, str) or not _QUESTION_ID.fullmatch(identity) or identity in answers:
            return error("The pending question batch is invalid")
        answer = submitted.get(identity)
        if not isinstance(answer, str) or len(answer) == 0:
            return error("Answers are required for every question")
        if _string_length(answer) > 16000:
            return error("An answer exceeds the maximum length")
        answers[identity] = answer
    if any(identity not in answers for identity in submitted):
        return error("Answers contain an unknown question id")
    return {"resumeValue": {"answers": answers}}


ASK_USER_MANIFEST = {'name': 'Ask User',
 'pluginKey': 'ask_user_question',
 'description': 'Let the agent pause mid-run to ask you a clarifying question and wait for your '
                'answer.',
 'agentsOnly': True,
 'authConfig': []}


def ask_user_requested(agent: dict | None, payload: dict) -> bool:
    """Port the saved/ephemeral opt-in from agents/load.ts.

    Machine grants never enable this optional tool. Model-spec inheritance
    remains with the full loadAgent port, not an ad-hoc permission shortcut.
    """
    if agent is not None:
        return ASK_USER_QUESTION_TOOL_NAME in (agent.get("tools") or [])
    ephemeral = payload.get("ephemeralAgent")
    return isinstance(ephemeral, dict) and ephemeral.get("ask_user_question") is True
