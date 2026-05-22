from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import func, select

from database import get_session, init_db
from models import CaseFile, CaseModule, Environment, Report, Script, Task, TaskLog, TestCase


def _dt(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value or None


def _parse_dt(value):
    if isinstance(value, datetime) or value is None:
        return value
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d_%H%M%S"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None


def ensure_database():
    init_db()


def environment_to_dict(env: Environment) -> dict:
    return {
        "id": env.id,
        "name": env.name,
        "base_url": env.base_url,
        "description": env.description,
        "db_host": env.db_host,
        "db_port": env.db_port,
        "timeout": env.timeout,
    }


def list_environments() -> list:
    with get_session() as session:
        envs = session.execute(select(Environment).order_by(Environment.id)).scalars().all()
        return [environment_to_dict(e) for e in envs]


def count_environments() -> int:
    with get_session() as session:
        return session.scalar(select(func.count()).select_from(Environment)) or 0


def upsert_environment(data: dict):
    with get_session() as session:
        env = session.get(Environment, data["id"])
        if not env:
            env = Environment(id=data["id"])
            session.add(env)
        env.name = data.get("name") or data["id"]
        env.base_url = data.get("base_url", "")
        env.description = data.get("description", "")
        env.db_host = data.get("db_host", "")
        env.db_port = int(data.get("db_port") or 3306)
        env.timeout = int(data.get("timeout") or 30)


def create_environment(data: dict) -> dict:
    with get_session() as session:
        if session.get(Environment, data["id"]):
            raise ValueError("exists")
        env = Environment(**data)
        session.add(env)
        session.flush()
        return environment_to_dict(env)


def update_environment(env_id: str, data: dict) -> Optional[dict]:
    with get_session() as session:
        env = session.get(Environment, env_id)
        if not env:
            return None
        for key, value in data.items():
            if value is not None and hasattr(env, key):
                setattr(env, key, value)
        session.flush()
        return environment_to_dict(env)


def delete_environment(env_id: str) -> bool:
    with get_session() as session:
        env = session.get(Environment, env_id)
        if not env:
            return False
        session.delete(env)
        return True


def module_to_dict(module: CaseModule) -> dict:
    yaml_count = len([f for f in module.files if f.file_type == "yaml"])
    excel_count = len([f for f in module.files if f.file_type == "excel"])
    return {
        "name": module.name,
        "description": module.description,
        "case_count": len(module.files),
        "yaml_count": yaml_count,
        "excel_count": excel_count,
        "path": f"data/{module.name}",
    }


def list_modules() -> list:
    with get_session() as session:
        modules = session.execute(select(CaseModule).order_by(CaseModule.name)).scalars().unique().all()
        return [module_to_dict(m) for m in modules]


def get_module(name: str) -> Optional[dict]:
    with get_session() as session:
        module = session.execute(select(CaseModule).where(CaseModule.name == name)).scalar_one_or_none()
        return module_to_dict(module) if module else None


def upsert_module(name: str, description: str = "") -> int:
    with get_session() as session:
        module = session.execute(select(CaseModule).where(CaseModule.name == name)).scalar_one_or_none()
        if not module:
            module = CaseModule(name=name, description=description or "")
            session.add(module)
            session.flush()
        elif description:
            module.description = description
        return module.id


def create_module(name: str, description: str = "") -> dict:
    with get_session() as session:
        existing = session.execute(select(CaseModule).where(CaseModule.name == name)).scalar_one_or_none()
        if existing:
            raise ValueError("exists")
        module = CaseModule(name=name, description=description or "")
        session.add(module)
        session.flush()
        return module_to_dict(module)


def rename_module(old_name: str, new_name: str) -> bool:
    with get_session() as session:
        module = session.execute(select(CaseModule).where(CaseModule.name == old_name)).scalar_one_or_none()
        if not module:
            return False
        if session.execute(select(CaseModule).where(CaseModule.name == new_name)).scalar_one_or_none():
            raise ValueError("exists")
        module.name = new_name
        return True


def delete_module(name: str) -> bool:
    with get_session() as session:
        module = session.execute(select(CaseModule).where(CaseModule.name == name)).scalar_one_or_none()
        if not module:
            return False
        session.delete(module)
        return True


def _case_file_data(case_file: CaseFile) -> dict:
    return {
        "test_module": case_file.module.name if case_file.module else "",
        "test_cases": [
            {
                "name": case.name,
                "endpoint": case.endpoint,
                "method": case.method,
                "headers": case.headers,
                "params": case.params,
                "expected": case.expected,
            }
            for case in sorted(case_file.test_cases, key=lambda c: c.sort_order)
        ],
    }


def case_file_to_dict(case_file: CaseFile) -> dict:
    data = _case_file_data(case_file)
    return {
        "filename": case_file.filename,
        "path": case_file.source_path or f"data/{case_file.module.name}/{case_file.filename}",
        "module": case_file.module.name,
        "file_type": case_file.file_type,
        "case_count": len(case_file.test_cases),
        "data": data,
        "raw_content": case_file.raw_content,
    }


def _replace_test_cases(session, case_file: CaseFile, data: dict):
    case_file.test_cases.clear()
    for index, item in enumerate((data or {}).get("test_cases", []) or []):
        expected = item.get("expected") if isinstance(item, dict) else None
        case_file.test_cases.append(
            TestCase(
                name=str(item.get("name", "") if isinstance(item, dict) else ""),
                endpoint=str(item.get("endpoint", "") if isinstance(item, dict) else ""),
                method=str(item.get("method", "GET") if isinstance(item, dict) else "GET").upper(),
                headers=item.get("headers") if isinstance(item, dict) else None,
                params=item.get("params") if isinstance(item, dict) else None,
                expected=expected,
                sort_order=index,
            )
        )
    session.flush()


def upsert_case_file(module_name: str, filename: str, file_type: str, data: dict, raw_content: str = "", source_path: str = ""):
    with get_session() as session:
        module = session.execute(select(CaseModule).where(CaseModule.name == module_name)).scalar_one_or_none()
        if not module:
            module = CaseModule(name=module_name, description="")
            session.add(module)
            session.flush()
        case_file = session.execute(
            select(CaseFile).where(CaseFile.module_id == module.id, CaseFile.filename == filename)
        ).scalar_one_or_none()
        if not case_file:
            case_file = CaseFile(module_id=module.id, filename=filename)
            session.add(case_file)
            session.flush()
        case_file.file_type = file_type
        case_file.source_path = source_path
        case_file.raw_content = raw_content
        _replace_test_cases(session, case_file, data or {})


def create_case_file(module_name: str, filename: str, file_type: str, data: dict, raw_content: str = "", source_path: str = "") -> dict:
    with get_session() as session:
        module = session.execute(select(CaseModule).where(CaseModule.name == module_name)).scalar_one_or_none()
        if not module:
            return {}
        existing = session.execute(
            select(CaseFile).where(CaseFile.module_id == module.id, CaseFile.filename == filename)
        ).scalar_one_or_none()
        if existing:
            raise ValueError("exists")
        case_file = CaseFile(
            module_id=module.id,
            filename=filename,
            file_type=file_type,
            raw_content=raw_content,
            source_path=source_path,
        )
        session.add(case_file)
        _replace_test_cases(session, case_file, data or {})
        session.flush()
        return case_file_to_dict(case_file)


def list_case_files(module_name: Optional[str] = None) -> list:
    with get_session() as session:
        query = select(CaseFile).join(CaseModule)
        if module_name:
            query = query.where(CaseModule.name == module_name)
        query = query.order_by(CaseModule.name, CaseFile.filename)
        files = session.execute(query).scalars().unique().all()
        return [case_file_to_dict(f) for f in files]


def get_case_file(module_name: str, filename: str) -> Optional[dict]:
    with get_session() as session:
        case_file = session.execute(
            select(CaseFile).join(CaseModule).where(CaseModule.name == module_name, CaseFile.filename == filename)
        ).scalar_one_or_none()
        return case_file_to_dict(case_file) if case_file else None


def update_case_file(module_name: str, filename: str, data: dict, raw_content: str = "") -> Optional[dict]:
    with get_session() as session:
        case_file = session.execute(
            select(CaseFile).join(CaseModule).where(CaseModule.name == module_name, CaseFile.filename == filename)
        ).scalar_one_or_none()
        if not case_file:
            return None
        case_file.raw_content = raw_content
        _replace_test_cases(session, case_file, data or {})
        session.flush()
        return case_file_to_dict(case_file)


def delete_case_file(module_name: str, filename: str) -> bool:
    with get_session() as session:
        case_file = session.execute(
            select(CaseFile).join(CaseModule).where(CaseModule.name == module_name, CaseFile.filename == filename)
        ).scalar_one_or_none()
        if not case_file:
            return False
        session.delete(case_file)
        return True


def task_to_dict(task: Task, log: str = "") -> dict:
    return {
        "task_id": task.task_id,
        "task_name": task.task_name,
        "env": task.env,
        "status": task.status,
        "command": task.command,
        "created_at": _dt(task.created_at),
        "task_type": task.task_type,
        "script_name": task.script_name,
        "finished_at": _dt(task.finished_at),
        "duration": task.duration,
        "exit_code": task.exit_code,
        "log": log,
        "report_url": task.report_url,
    }


def create_task(data: dict):
    with get_session() as session:
        task = Task(
            task_id=data["task_id"],
            task_name=data.get("task_name"),
            env=data.get("env", ""),
            status=data.get("status", "PENDING"),
            command=data.get("command", ""),
            task_type=data.get("task_type", "pytest"),
            script_name=data.get("script_name"),
            created_at=_parse_dt(data.get("created_at")) or datetime.now(UTC).replace(tzinfo=None),
            finished_at=_parse_dt(data.get("finished_at")),
            duration=data.get("duration"),
            exit_code=data.get("exit_code"),
            report_url=data.get("report_url"),
        )
        session.merge(task)


def update_task(task_id: str, **kwargs):
    with get_session() as session:
        task = session.get(Task, task_id)
        if not task:
            return
        for key, value in kwargs.items():
            if key == "finished_at":
                value = _parse_dt(value)
            if hasattr(task, key):
                setattr(task, key, value)


def save_task_log(task_id: str, log: str):
    with get_session() as session:
        task_log = session.execute(select(TaskLog).where(TaskLog.task_id == task_id)).scalar_one_or_none()
        if not task_log:
            task_log = TaskLog(task_id=task_id, log=log or "")
            session.add(task_log)
        else:
            task_log.log = log or ""


def get_task(task_id: str) -> Optional[dict]:
    with get_session() as session:
        task = session.get(Task, task_id)
        if not task:
            return None
        task_log = session.execute(select(TaskLog).where(TaskLog.task_id == task_id)).scalar_one_or_none()
        return task_to_dict(task, task_log.log if task_log else "")


def list_tasks(limit: int = 20, status: Optional[str] = None, task_type: Optional[str] = None) -> list:
    with get_session() as session:
        query = select(Task).order_by(Task.created_at.desc()).limit(limit)
        if status:
            query = query.where(Task.status == status)
        if task_type:
            query = query.where(Task.task_type == task_type)
        tasks = session.execute(query).scalars().all()
        logs = {
            log.task_id: log.log
            for log in session.execute(select(TaskLog).where(TaskLog.task_id.in_([t.task_id for t in tasks]))).scalars().all()
        } if tasks else {}
        return [task_to_dict(t, logs.get(t.task_id, "")) for t in tasks]


def upsert_report(task_id: str, report_url: str, report_path: str, has_html_report: bool):
    with get_session() as session:
        report = session.execute(select(Report).where(Report.task_id == task_id)).scalar_one_or_none()
        if not report:
            report = Report(task_id=task_id)
            session.add(report)
        report.report_url = report_url
        report.report_path = report_path
        report.has_html_report = has_html_report
        task = session.get(Task, task_id)
        if task:
            task.report_url = report_url


def list_reports() -> list:
    with get_session() as session:
        reports = session.execute(select(Report).order_by(Report.created_at.desc())).scalars().all()
        result = []
        for report in reports:
            task = session.get(Task, report.task_id)
            task_log = session.execute(select(TaskLog).where(TaskLog.task_id == report.task_id)).scalar_one_or_none()
            entry = {
                "task_id": report.task_id,
                "created_at": _dt(task.created_at) if task else _dt(report.created_at),
                "env": task.env if task else "",
                "has_html_report": report.has_html_report,
                "report_url": report.report_url,
                "status": task.status if task else "UNKNOWN",
                "task_type": task.task_type if task else "unknown",
                "script_name": task.script_name if task else "",
                "log": task_log.log if task_log else "",
            }
            result.append(entry)
        return result


def upsert_script(filename: str, suffix: str, type_label: str, file_path: Path, description: str = ""):
    with get_session() as session:
        script = session.get(Script, filename)
        if not script:
            script = Script(filename=filename)
            session.add(script)
        script.suffix = suffix
        script.type_label = type_label
        script.file_path = str(file_path)
        if description:
            script.description = description


def delete_script_record(filename: str):
    with get_session() as session:
        script = session.get(Script, filename)
        if script:
            session.delete(script)
