from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.types import JSON


Base = declarative_base()


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


class TimestampMixin:
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Environment(Base, TimestampMixin):
    __tablename__ = "environments"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    base_url = Column(String(512), default="", nullable=False)
    description = Column(Text, default="", nullable=False)
    db_host = Column(String(255), default="", nullable=False)
    db_port = Column(Integer, default=3306, nullable=False)
    timeout = Column(Integer, default=30, nullable=False)


class CaseModule(Base, TimestampMixin):
    __tablename__ = "case_modules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), unique=True, nullable=False, index=True)
    description = Column(Text, default="", nullable=False)

    files = relationship("CaseFile", back_populates="module", cascade="all, delete-orphan")


class CaseFile(Base, TimestampMixin):
    __tablename__ = "case_files"
    __table_args__ = (UniqueConstraint("module_id", "filename", name="uq_case_file_module_filename"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    module_id = Column(Integer, ForeignKey("case_modules.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(32), nullable=False, default="yaml")
    source_path = Column(String(1024), default="", nullable=False)
    raw_content = Column(Text, default="", nullable=False)

    module = relationship("CaseModule", back_populates="files")
    test_cases = relationship("TestCase", back_populates="case_file", cascade="all, delete-orphan")


class TestCase(Base, TimestampMixin):
    __tablename__ = "test_cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_file_id = Column(Integer, ForeignKey("case_files.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    endpoint = Column(String(512), default="", nullable=False)
    method = Column(String(16), default="GET", nullable=False)
    headers = Column(JSON, nullable=True)
    params = Column(JSON, nullable=True)
    expected = Column(JSON, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    case_file = relationship("CaseFile", back_populates="test_cases")


class Task(Base):
    __tablename__ = "tasks"

    task_id = Column(String(64), primary_key=True)
    task_name = Column(String(255), nullable=True)
    env = Column(String(64), default="", nullable=False)
    status = Column(String(32), default="PENDING", nullable=False)
    command = Column(Text, default="", nullable=False)
    task_type = Column(String(32), default="pytest", nullable=False)
    script_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    duration = Column(String(64), nullable=True)
    exit_code = Column(Integer, nullable=True)
    report_url = Column(String(1024), nullable=True)

    logs = relationship("TaskLog", back_populates="task", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="task", cascade="all, delete-orphan")


class TaskLog(Base):
    __tablename__ = "task_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), ForeignKey("tasks.task_id"), nullable=False, index=True)
    log = Column(Text, default="", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    task = relationship("Task", back_populates="logs")


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), ForeignKey("tasks.task_id"), nullable=False, index=True)
    report_url = Column(String(1024), default="", nullable=False)
    report_path = Column(String(1024), default="", nullable=False)
    has_html_report = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    task = relationship("Task", back_populates="reports")


class Script(Base, TimestampMixin):
    __tablename__ = "scripts"

    filename = Column(String(255), primary_key=True)
    suffix = Column(String(32), nullable=False)
    type_label = Column(String(64), default="", nullable=False)
    description = Column(Text, default="", nullable=False)
    file_path = Column(String(1024), default="", nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
