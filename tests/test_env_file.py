"""Settings and keys read from a `.env` file when the service starts."""

from tests.fake_openrouter import fake_openrouter
from tests.test_preparation import save_capture, submit, wait_until_settled

KEY = "sk-or-from-env-file"


def test_settings_and_the_key_come_from_the_env_file(start_service, tmp_path):
    with fake_openrouter() as fake:
        fake.answer("white desk")
        env_file = tmp_path / "settings.env"
        env_file.write_text(
            "# Comments and blank lines are skipped.\n"
            "\n"
            "ESCAPE_ROOM_PREPARATION_WORKER=openrouter\n"
            f'ESCAPE_ROOM_OPENROUTER_URL="{fake.url}"\n'
            f"export OPENROUTER_API_KEY='{KEY}'\n",
            encoding="utf-8",
        )
        with start_service(tmp_path / "data", ESCAPE_ROOM_ENV_FILE=str(env_file)) as url:
            capture = save_capture(url, "overview.png")
            job = wait_until_settled(url, submit(url, capture).json()["id"])

    assert job["state"] == "awaiting_review", job["error"]
    assert job["config"]["worker"] == "openrouter"
    [request] = fake.received
    assert request.headers["Authorization"] == f"Bearer {KEY}"


def test_a_variable_set_in_the_environment_wins_over_the_env_file(start_service, tmp_path):
    env_file = tmp_path / "settings.env"
    env_file.write_text(
        "ESCAPE_ROOM_PREPARATION_WORKER=openrouter\nESCAPE_ROOM_FIXTURE_STAGE_SECONDS=0.1\n",
        encoding="utf-8",
    )
    settings = {"ESCAPE_ROOM_ENV_FILE": str(env_file), "ESCAPE_ROOM_PREPARATION_WORKER": "fixture"}
    with start_service(tmp_path / "data", **settings) as url:
        capture = save_capture(url, "overview.png")
        job = wait_until_settled(url, submit(url, capture).json()["id"])

    assert job["config"]["worker"] == "fixture"
    assert job["config"]["stage_seconds"] == 0.1
