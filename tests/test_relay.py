import pytest

from relay.relay import do_stuff


@pytest.mark.parametrize(
    "option",
    [("test1",), ("test1", "test2")],
)
def test_do_stuff(option: tuple[str, ...]) -> None:
    assert do_stuff(option) == option
