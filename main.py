"""
测试效能平台（TEP）V1.0 - FastAPI 主应用
========================================
实现 Phase 1 + Phase 2 + Phase 3 全部功能：
- 核心执行引擎（subprocess 异步执行 Pytest）
- 任务状态管理
- Allure 报告静态托管
- YAML 用例数据管理
- 前端界面集成
"""

import os
import re
import json
import uuid
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

# ============================================================
# 全局配置
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"
TESTCASES_DIR = BASE_DIR / "testcases"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# 确保目录存在
for d in [DATA_DIR, REPORTS_DIR, TESTCASES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================
# 任务状态存储（内存字典，Phase 2 可替换为数据库）
# ============================================================
tasks_store: dict = {}

# ============================================================
# Pydantic 数据模型
# ============================================================

class RunRequest(BaseModel):
    """执行测试的请求体"""
    env: str = "test_env"  # test_env | staging_env
    markers: Optional[str] = None  # pytest markers 过滤
    testcase_path: Optional[str] = None  # 指定测试路径

class CaseUpdateRequest(BaseModel):
    """更新用例数据的请求体"""
    filename: str
    content: str  # YAML 文件的完整内容


class TaskInfo(BaseModel):
    """任务信息模型"""
    task_id: str
    env: str
    status: str  # PENDING | RUNNING | FINISHED | ERROR
    command: str
    created_at: str
    finished_at: Optional[str] = None
    duration: Optional[str] = None
    exit_code: Optional[int] = None
    log: Optional[str] = None
    report_url: Optional[str] = None


# ============================================================
# FastAPI 应用实例
# ============================================================
app = FastAPI(
    title="测试效能平台 TEP V1.0",
    description="接口自动化测试的 Web 管控平台，支持用例管理、一键执行和报告查看",
    version="1.0.0",
)

# 挂载静态文件
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
# 挂载 Allure 报告目录（如果存在）
if REPORTS_DIR.exists():
    app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR), html=True), name="reports")

# Jinja2 模板引擎（直接使用 Jinja2，绕过 starlette 1.0 的 Jinja2Templates 缓存兼容问题）
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


# ============================================================
# 工具函数
# ============================================================

def generate_task_id() -> str:
    """生成唯一的任务 ID"""
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


def update_task_status(task_id: str, status: str, **kwargs):
    """更新任务状态"""
    if task_id in tasks_store:
        tasks_store[task_id]["status"] = status
        for key, value in kwargs.items():
            tasks_store[task_id][key] = value
        if status in ("FINISHED", "ERROR"):
            tasks_store[task_id]["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            created = datetime.strptime(tasks_store[task_id]["created_at"], "%Y-%m-%d %H:%M:%S")
            finished = datetime.strptime(tasks_store[task_id]["finished_at"], "%Y-%m-%d %H:%M:%S")
            tasks_store[task_id]["duration"] = str(finished - created)


def save_task_log(task_id: str, stdout: str, stderr: str = ""):
    """保存任务执行日志"""
    if task_id in tasks_store:
        tasks_store[task_id]["log"] = (stdout or "") + "\n" + (stderr or "")


def run_pytest_task(task_id: str, env: str, markers: Optional[str] = None, testcase_path: Optional[str] = None):
    """
    在后台线程中执行的测试任务
    核心执行引擎：通过 subprocess 代理执行 pytest 命令
    """
    update_task_status(task_id, "RUNNING")

    # 确定测试路径
    test_path = testcase_path or str(TESTCASES_DIR)

    # 拼接 pytest 执行命令
    command_parts = [
        "python", "-m", "pytest",
        test_path,
        f"--env={env}",
        f"--alluredir={REPORTS_DIR / task_id}",
        "-v",
        "--tb=short",
    ]

    # 如果指定了 markers，添加 -m 参数
    if markers:
        command_parts.extend(["-m", markers])

    command_str = " ".join(command_parts)
    tasks_store[task_id]["command"] = command_str

    try:
        # 执行命令并捕获输出
        result = subprocess.run(
            command_parts,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(BASE_DIR),
            env={**os.environ, "TEST_ENV": env},
        )

        # 保存执行结果
        save_task_log(task_id, result.stdout, result.stderr)
        tasks_store[task_id]["exit_code"] = result.returncode

        if result.returncode == 0:
            update_task_status(task_id, "FINISHED")
        else:
            # pytest 返回非0可能只是测试失败，仍标记为完成
            update_task_status(task_id, "FINISHED")

        # 生成 Allure HTML 报告
        report_dir = REPORTS_DIR / task_id
        html_report_dir = report_dir / "html"
        html_report_dir.mkdir(parents=True, exist_ok=True)

        allure_cmd = [
            "allure", "generate",
            str(report_dir),
            "-o", str(html_report_dir),
            "--clean",
        ]
        try:
            subprocess.run(allure_cmd, capture_output=True, text=True, timeout=120)
            tasks_store[task_id]["report_url"] = f"/reports/{task_id}/html/index.html"
        except FileNotFoundError:
            # allure 命令不存在，跳过 HTML 报告生成，使用原始数据
            tasks_store[task_id]["report_url"] = f"/reports/{task_id}/"
        except subprocess.TimeoutExpired:
            tasks_store[task_id]["report_url"] = f"/reports/{task_id}/"
        except Exception:
            tasks_store[task_id]["report_url"] = f"/reports/{task_id}/"

    except subprocess.TimeoutExpired:
        update_task_status(task_id, "ERROR")
        save_task_log(task_id, "", "测试执行超时（超过600秒）")
        tasks_store[task_id]["exit_code"] = -1
    except Exception as e:
        update_task_status(task_id, "ERROR")
        save_task_log(task_id, "", str(e))
        tasks_store[task_id]["exit_code"] = -1


def parse_yaml_cases(filepath: Path) -> dict:
    """解析单个 YAML 文件，返回结构化数据"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        # 安全计算相对路径
        try:
            rel_path = str(filepath.relative_to(BASE_DIR))
        except ValueError:
            rel_path = str(filepath)
        return {
            "filename": filepath.name,
            "path": rel_path,
            "data": data,
        }
    except yaml.YAMLError as e:
        try:
            rel_path = str(filepath.relative_to(BASE_DIR))
        except ValueError:
            rel_path = str(filepath)
        return {
            "filename": filepath.name,
            "path": rel_path,
            "error": f"YAML 解析错误: {str(e)}",
        }


def extract_summary_from_log(log: str) -> dict:
    """从 pytest 输出日志中提取测试摘要"""
    summary = {
        "total": None,
        "passed": None,
        "failed": None,
        "errors": None,
        "skipped": None,
    }
    if not log:
        return summary

    # 匹配 pytest 的汇总行，例如: "5 passed, 2 failed, 1 skipped in 10.5s"
    match = re.search(r"(\d+) passed", log)
    if match:
        summary["passed"] = int(match.group(1))

    match = re.search(r"(\d+) failed", log)
    if match:
        summary["failed"] = int(match.group(1))

    match = re.search(r"(\d+) error", log)
    if match:
        summary["errors"] = int(match.group(1))

    match = re.search(r"(\d+) skipped", log)
    if match:
        summary["skipped"] = int(match.group(1))

    if summary["passed"] is not None:
        total = summary["passed"]
        for k in ["failed", "errors", "skipped"]:
            if summary[k] is not None:
                total += summary[k]
        summary["total"] = total

    return summary


# ============================================================
# 页面路由
# ============================================================

def render_template(template_name: str, **context) -> HTMLResponse:
    """渲染 Jinja2 模板并返回 HTMLResponse（兼容 starlette 1.0+）"""
    template = jinja_env.get_template(template_name)
    html = template.render(**context)
    return HTMLResponse(html)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页 - 执行中心"""
    return render_template("index.html", request=request)


@app.get("/cases", response_class=HTMLResponse)
async def cases_page(request: Request):
    """用例管理页面"""
    return render_template("cases.html", request=request)


@app.get("/reports-page", response_class=HTMLResponse)
async def reports_page(request: Request):
    """报告看板页面"""
    return render_template("reports.html", request=request)


# ============================================================
# API 路由 - 用例管理
# ============================================================

@app.get("/api/cases")
async def get_cases():
    """
    获取用例列表
    读取 data/ 目录下的所有 YAML 文件，解析为 JSON 返回
    """
    yaml_files = list(DATA_DIR.glob("*.yaml")) + list(DATA_DIR.glob("*.yml"))

    if not yaml_files:
        return {"cases": [], "total": 0}

    cases = []
    for f in sorted(yaml_files):
        case_data = parse_yaml_cases(f)
        cases.append(case_data)

    return {"cases": cases, "total": len(cases)}


@app.get("/api/cases/{filename}")
async def get_case_detail(filename: str):
    """获取单个用例文件的详细内容"""
    filepath = DATA_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"文件 {filename} 不存在")

    case_data = parse_yaml_cases(filepath)
    # 同时返回原始 YAML 文本，便于编辑
    with open(filepath, "r", encoding="utf-8") as f:
        case_data["raw_content"] = f.read()

    return case_data


@app.post("/api/cases/update")
async def update_case(request: CaseUpdateRequest):
    """
    更新用例数据
    接收 JSON 中的 YAML 内容，反写回 data/*.yaml 文件
    """
    filepath = DATA_DIR / request.filename

    # 安全检查：防止路径穿越
    if not str(filepath.resolve()).startswith(str(DATA_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法文件路径")

    # 验证 YAML 格式
    try:
        yaml.safe_load(request.content)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"YAML 格式错误: {str(e)}")

    # 写入文件
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(request.content)
        return {"message": f"文件 {request.filename} 更新成功", "filename": request.filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入文件失败: {str(e)}")


@app.post("/api/cases/create")
async def create_case(filename: str, content: str = ""):
    """创建新的用例文件"""
    if not filename.endswith((".yaml", ".yml")):
        filename += ".yaml"

    filepath = DATA_DIR / filename
    if filepath.exists():
        raise HTTPException(status_code=400, detail=f"文件 {filename} 已存在")

    # 验证 YAML 格式
    if content:
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise HTTPException(status_code=400, detail=f"YAML 格式错误: {str(e)}")
    else:
        content = "# 新建用例文件\n"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return {"message": f"文件 {filename} 创建成功", "filename": filename}


@app.delete("/api/cases/{filename}")
async def delete_case(filename: str):
    """删除用例文件"""
    filepath = DATA_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"文件 {filename} 不存在")

    filepath.unlink()
    return {"message": f"文件 {filename} 删除成功"}


# ============================================================
# API 路由 - 任务执行
# ============================================================

@app.post("/api/run")
async def run_tests(request: RunRequest):
    """
    触发测试执行
    启动后台线程执行 pytest 命令，立即返回 task_id
    """
    # 验证环境参数
    valid_envs = ["test_env", "staging_env"]
    if request.env not in valid_envs:
        raise HTTPException(
            status_code=400,
            detail=f"无效的环境参数: {request.env}，可选值: {valid_envs}",
        )

    task_id = generate_task_id()

    # 初始化任务记录
    tasks_store[task_id] = {
        "task_id": task_id,
        "env": request.env,
        "status": "PENDING",
        "command": "",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": None,
        "duration": None,
        "exit_code": None,
        "log": None,
        "report_url": None,
    }

    # 创建 Allure 报告目录
    report_dir = REPORTS_DIR / task_id
    report_dir.mkdir(parents=True, exist_ok=True)

    # 启动后台线程执行测试
    thread = threading.Thread(
        target=run_pytest_task,
        args=(task_id, request.env, request.markers, request.testcase_path),
        daemon=True,
    )
    thread.start()

    return {
        "task_id": task_id,
        "status": "PENDING",
        "message": "测试任务已提交，请通过 /api/status/{task_id} 查询执行状态",
    }


@app.get("/api/status/{task_id}")
async def get_task_status(task_id: str):
    """查询任务执行状态"""
    if task_id not in tasks_store:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    task = tasks_store[task_id]
    # 提取测试摘要
    summary = extract_summary_from_log(task.get("log", ""))

    return {
        **task,
        "summary": summary,
    }


@app.get("/api/tasks")
async def get_tasks(limit: int = 20, status: Optional[str] = None):
    """获取任务列表"""
    tasks = list(tasks_store.values())

    # 按状态过滤
    if status:
        tasks = [t for t in tasks if t["status"] == status]

    # 按创建时间倒序
    tasks.sort(key=lambda x: x["created_at"], reverse=True)

    # 限制返回数量
    tasks = tasks[:limit]

    # 为每个任务提取摘要
    for task in tasks:
        task["summary"] = extract_summary_from_log(task.get("log", ""))

    return {"tasks": tasks, "total": len(tasks)}


# ============================================================
# API 路由 - 报告管理
# ============================================================

@app.get("/api/reports")
async def get_reports():
    """
    获取历史报告列表
    遍历 reports/ 目录返回文件列表
    """
    if not REPORTS_DIR.exists():
        return {"reports": [], "total": 0}

    reports = []
    for d in sorted(REPORTS_DIR.iterdir(), reverse=True):
        if d.is_dir() and not d.name.startswith("."):
            html_dir = d / "html"
            has_html = html_dir.exists() and (html_dir / "index.html").exists()

            # 检查是否在任务存储中
            task_info = tasks_store.get(d.name, {})

            report_entry = {
                "task_id": d.name,
                "created_at": task_info.get("created_at", ""),
                "env": task_info.get("env", ""),
                "has_html_report": has_html,
                "report_url": f"/reports/{d.name}/html/index.html" if has_html else f"/reports/{d.name}/",
                "status": task_info.get("status", "UNKNOWN"),
            }

            if task_info:
                report_entry["summary"] = extract_summary_from_log(task_info.get("log", ""))
            else:
                report_entry["summary"] = {}

            reports.append(report_entry)

    return {"reports": reports, "total": len(reports)}


@app.get("/api/log/{task_id}")
async def get_task_log(task_id: str, tail: Optional[int] = None):
    """获取任务执行日志"""
    if task_id not in tasks_store:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    log = tasks_store[task_id].get("log", "")

    if tail and log:
        lines = log.splitlines()
        log = "\n".join(lines[-tail:])

    return {"task_id": task_id, "log": log}


# ============================================================
# 健康检查
# ============================================================

@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "version": "1.0.0",
        "running_tasks": len([t for t in tasks_store.values() if t["status"] == "RUNNING"]),
        "total_tasks": len(tasks_store),
    }


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
