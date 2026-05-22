from datetime import datetime
import asyncio

import main
import repositories as repo


def test_environments_are_read_from_database():
    payload = asyncio.run(main.get_environments())

    assert payload["total"] >= 1
    assert any(env["id"] == "test_env" for env in payload["environments"])


def test_case_modules_are_available_from_database():
    payload = asyncio.run(main.get_modules())

    assert "modules" in payload
    assert payload["total"] >= 1


def test_task_repository_round_trip():
    task_id = f"pytest_storage_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    repo.create_task(
        {
            "task_id": task_id,
            "task_name": "storage test",
            "env": "test_env",
            "status": "PENDING",
            "command": "pytest",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "task_type": "pytest",
        }
    )
    repo.update_task(task_id, status="FINISHED", exit_code=0)
    repo.save_task_log(task_id, "1 passed")

    task = repo.get_task(task_id)

    assert task["status"] == "FINISHED"
    assert task["exit_code"] == 0
    assert task["log"] == "1 passed"
