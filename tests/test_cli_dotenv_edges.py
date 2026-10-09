from __future__ import annotations

import pytest

import local_shell_mcp.cli_call as cli_call


def test_cli_dotenv_value_edge_cases() -> None:
    assert cli_call._parse_dotenv_value("") == ""
    assert cli_call._parse_dotenv_value("'unterminated") == "unterminated"
    assert cli_call._parse_dotenv_value("'quoted' ignored") == "quoted"
    assert (
        cli_call._parse_dotenv_value('"hello\\n${NAME}\\q"', variables={"NAME": "world"})
        == "hello\nworld\\q"
    )
    assert cli_call._parse_dotenv_value('"trailing\\', variables={}) == "trailing\\"
    assert cli_call._parse_dotenv_value("value # comment") == "value"

def test_cli_dotenv_interpolation_edge_paths() -> None:
    variables = {"NAME": "world", "EMPTY": ""}
    assert cli_call._interpolate_dotenv("x$$y$", variables) == "x$y$"
    assert cli_call._interpolate_dotenv("$NAME-$MISSING-$9", variables) == "world--$9"
    assert (
        cli_call._interpolate_dotenv(r"\n\r\t\"\\\$\q", variables, decode_escapes=True)
        == '\n\r\t"\\$\\q'
    )
    assert cli_call._interpolate_dotenv("${MISSING:-${NAME}}", variables) == "world"
    with pytest.raises(ValueError, match="missing"):
        cli_call._interpolate_dotenv("${NAME", variables)
    with pytest.raises(ValueError, match="nested too deeply"):
        cli_call._interpolate_dotenv("x", variables, depth=21)

@pytest.mark.parametrize(
    ("value", "start", "decode", "expected"),
    [
        ("a}", 0, False, 1),
        ("${A}}", 0, False, 4),
        (r"\${A}}", 0, True, 5),
        (r"\q}", 0, True, 2),
        (r"\n}", 0, True, 2),
        ("unterminated", 0, False, None),
    ],
)
def test_cli_dotenv_interpolation_end_paths(
    value: str, start: int, decode: bool, expected: int | None
) -> None:
    assert cli_call._dotenv_interpolation_end(value, start, decode_escapes=decode) == expected

def test_cli_additional_interpolation_branches() -> None:
    # Dotenv escaped backslash and escaped dollar-without-brace paths.
    assert cli_call._dotenv_interpolation_end(r"\\}", 0, decode_escapes=True) == 2
    assert cli_call._dotenv_interpolation_end(r"\$}", 0, decode_escapes=True) == 2
    assert cli_call._interpolate_dotenv("${NAME:+yes}", {"NAME": "x"}) == "yes"
    assert cli_call._interpolate_dotenv("${MISSING:+yes}", {}) == ""
