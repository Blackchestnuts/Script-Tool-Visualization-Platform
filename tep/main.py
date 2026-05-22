"""
测试效能平台（TEP）V1.1 - FastAPI 主应用
========================================
功能模块：
- Pytest 自动化测试执行引擎
- YAML 用例数据管理
- 通用脚本管理（Python / Shell / Bat 等）
- 脚本在线编辑与一键执行
- Allure 报告静态托管
- 任务状态管理与实时日志
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
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
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
SCRIPTS_DIR = BASE_DIR / "scripts"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# 确保目录存在
for d in [DATA_DIR, REPORTS_DIR, TESTCASES_DIR, SCRIPTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================
# 脚本类型配置：后缀名 → 执行命令映射
# ============================================================
SCRIPT_TYPES = {
    ".py": {"label": "Python", "command": "python", "icon": "🐍", "color": "#3776ab"},
    ".sh": {"label": "Shell", "command": "bash", "icon": "🖥️", "color": "#4eaa25"},
    ".bat": {"label": "Batch", "command": "cmd", "icon": "📋", "color": "#0078d4"},
    ".ps1": {"label": "PowerShell", "command": "powershell", "icon": "⚡", "color": "#5391fe"},
    ".js": {"label": "Node.js", "command": "node", "icon": "🟢", "color": "#68a063"},
    ".rb": {"label": "Ruby", "command": "ruby", "icon": "💎", "color": "#cc342d"},
    ".lua": {"label": "Lua", "command": "lua", "icon": "🌙", "color": "#000080"},
}

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
    markers: Optional[str] = None
    testcase_path: Optional[str] = None


class CaseUpdateRequest(BaseModel):
    """更新用例数据的请求体"""
    filename: str
    content: str


class ScriptUpdateRequest(BaseModel):
    """更新脚本的请求体"""
    filename: str
    content: str


class ScriptCreateRequest(BaseModel):
    """创建脚本的请求体"""
    filename: str
    content: str = ""
    description: str = ""


class ScriptRunRequest(BaseModel):
    """执行脚本的请求体"""
    filename: str
    args: Optional[str] = None  # 命令行参数


class TaskInfo(BaseModel):
    """任务信息模型"""
    task_id: str
    env: str
    status: str  # PENDING | RUNNING | FINISHED | ERROR
    command: str
    created_at: str
    task_type: str = "pytest"  # pytest | script
    finished_at: Optional[str] = None
    duration: Optional[str] = None
    exit_code: Optional[int] = None
    log: Optional[str] = None
    report_url: Optional[str] = None


# ============================================================
# FastAPI 应用实例
# ============================================================
app = FastAPI(
    title="测试效能平台 TEP V1.1",
    description="接口自动化测试 + 通用脚本管理的 Web 管控平台",
    version="1.1.0",
)

# 挂载静态文件
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
# 挂载 Allure 报告目录
if REPORTS_DIR.exists():
    app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR), html=True), name="reports")

# Jinja2 模板引擎
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
            try:
                created = datetime.strptime(tasks_store[task_id]["created_at"], "%Y-%m-%d %H:%M:%S")
                finished = datetime.strptime(tasks_store[task_id]["finished_at"], "%Y-%m-%d %H:%M:%S")
                tasks_store[task_id]["duration"] = str(finished - created)
            except (ValueError, TypeError):
                pass


def save_task_log(task_id: str, stdout: str, stderr: str = ""):
    """保存任务执行日志"""
    if task_id in tasks_store:
        tasks_store[task_id]["log"] = (stdout or "") + "\n" + (stderr or "")


def get_script_type_info(suffix: str) -> dict:
    """根据后缀名获取脚本类型信息"""
    return SCRIPT_TYPES.get(suffix, {
        "label": "未知", "command": "", "icon": "📄", "color": "#999"
    })


def parse_script_info(filepath: Path) -> dict:
    """解析脚本文件信息"""
    suffix = filepath.suffix.lower()
    type_info = get_script_type_info(suffix)
    stat = filepath.stat()

    # 读取文件前 5 行作为描述预览
    preview_lines = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i >= 5:
                    break
                preview_lines.append(line.rstrip())
    except Exception:
        pass

    return {
        "filename": filepath.name,
        "suffix": suffix,
        "type_label": type_info["label"],
        "type_icon": type_info["icon"],
        "type_color": type_info["color"],
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "preview": "\n".join(preview_lines),
    }


# ============================================================
# 执行引擎
# ============================================================

def run_pytest_task(task_id: str, env: str, markers: Optional[str] = None, testcase_path: Optional[str] = None):
    """后台线程：执行 Pytest 测试"""
    update_task_status(task_id, "RUNNING")

    test_path = testcase_path or str(TESTCASES_DIR)

    command_parts = [
        "python", "-m", "pytest",
        test_path,
        f"--env={env}",
        f"--alluredir={REPORTS_DIR / task_id}",
        "-v", "--tb=short",
    ]
    if markers:
        command_parts.extend(["-m", markers])

    command_str = " ".join(command_parts)
    tasks_store[task_id]["command"] = command_str

    try:
        result = subprocess.run(
            command_parts,
            capture_output=True, text=True, timeout=600,
            cwd=str(BASE_DIR),
            env={**os.environ, "TEST_ENV": env},
        )
        save_task_log(task_id, result.stdout, result.stderr)
        tasks_store[task_id]["exit_code"] = result.returncode
        update_task_status(task_id, "FINISHED")

        # 尝试生成 Allure HTML 报告
        report_dir = REPORTS_DIR / task_id
        html_report_dir = report_dir / "html"
        html_report_dir.mkdir(parents=True, exist_ok=True)

        try:
            subprocess.run(
                ["allure", "generate", str(report_dir), "-o", str(html_report_dir), "--clean"],
                capture_output=True, text=True, timeout=120,
            )
            tasks_store[task_id]["report_url"] = f"/reports/{task_id}/html/index.html"
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


def run_script_task(task_id: str, filename: str, args: Optional[str] = None):
    """后台线程：执行通用脚本"""
    update_task_status(task_id, "RUNNING")

    filepath = SCRIPTS_DIR / filename
    suffix = filepath.suffix.lower()
    type_info = get_script_type_info(suffix)

    # 构建执行命令
    if suffix == ".bat":
        command_parts = ["cmd", "/c", str(filepath)]
    elif suffix == ".ps1":
        command_parts = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(filepath)]
    else:
        command_parts = [type_info["command"], str(filepath)]

    if args:
        command_parts.extend(args.split())

    command_str = " ".join(command_parts)
    tasks_store[task_id]["command"] = command_str

    try:
        result = subprocess.run(
            command_parts,
            capture_output=True, text=True, timeout=600,
            cwd=str(BASE_DIR),
            env={**os.environ, "SCRIPT_NAME": filename},
        )
        save_task_log(task_id, result.stdout, result.stderr)
        tasks_store[task_id]["exit_code"] = result.returncode
        update_task_status(task_id, "FINISHED")

    except subprocess.TimeoutExpired:
        update_task_status(task_id, "ERROR")
        save_task_log(task_id, "", "脚本执行超时（超过600秒）")
        tasks_store[task_id]["exit_code"] = -1
    except FileNotFoundError:
        update_task_status(task_id, "ERROR")
        save_task_log(task_id, "", f"找不到执行器: {type_info['command']}，请确认已安装 {type_info['label']} 环境")
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
        try:
            rel_path = str(filepath.relative_to(BASE_DIR))
        except ValueError:
            rel_path = str(filepath)
        return {"filename": filepath.name, "path": rel_path, "data": data}
    except yaml.YAMLError as e:
        try:
            rel_path = str(filepath.relative_to(BASE_DIR))
        except ValueError:
            rel_path = str(filepath)
        return {"filename": filepath.name, "path": rel_path, "error": f"YAML 解析错误: {str(e)}"}


def extract_summary_from_log(log: str) -> dict:
    """从 pytest 输出日志中提取测试摘要"""
    summary = {"total": None, "passed": None, "failed": None, "errors": None, "skipped": None}
    if not log:
        return summary

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
    """渲染 Jinja2 模板并返回 HTMLResponse"""
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


@app.get("/scripts", response_class=HTMLResponse)
async def scripts_page(request: Request):
    """脚本管理页面"""
    return render_template("scripts.html", request=request)


@app.get("/reports-page", response_class=HTMLResponse)
async def reports_page(request: Request):
    """报告看板页面"""
    return render_template("reports.html", request=request)


# ============================================================
# API 路由 - 用例管理
# ============================================================

@app.get("/api/cases")
async def get_cases():
    """获取用例列表"""
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
    """获取单个用例文件详情"""
    filepath = DATA_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"文件 {filename} 不存在")
    case_data = parse_yaml_cases(filepath)
    with open(filepath, "r", encoding="utf-8") as f:
        case_data["raw_content"] = f.read()
    return case_data


@app.post("/api/cases/update")
async def update_case(request: CaseUpdateRequest):
    """更新用例数据"""
    filepath = DATA_DIR / request.filename
    if not str(filepath.resolve()).startswith(str(DATA_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法文件路径")
    try:
        yaml.safe_load(request.content)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"YAML 格式错误: {str(e)}")
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
# API 路由 - 脚本管理
# ============================================================

@app.get("/api/scripts")
async def get_scripts():
    """获取脚本列表"""
    supported_suffixes = set(SCRIPT_TYPES.keys())
    script_files = [f for f in SCRIPTS_DIR.iterdir() if f.is_file() and f.suffix.lower() in supported_suffixes]

    if not script_files:
        return {"scripts": [], "total": 0}

    scripts = []
    for f in sorted(script_files):
        info = parse_script_info(f)
        scripts.append(info)

    return {"scripts": scripts, "total": len(scripts)}


@app.get("/api/scripts/{filename}")
async def get_script_detail(filename: str):
    """获取脚本详情（含完整源码）"""
    filepath = SCRIPTS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"脚本 {filename} 不存在")

    # 安全检查
    if not str(filepath.resolve()).startswith(str(SCRIPTS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法文件路径")

    info = parse_script_info(filepath)
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        info["content"] = f.read()

    return info


@app.post("/api/scripts/create")
async def create_script(request: ScriptCreateRequest):
    """创建新脚本"""
    filename = request.filename
    # 安全：只允许合法后缀
    suffix = Path(filename).suffix.lower()
    if suffix not in SCRIPT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的脚本类型: {suffix}，支持: {list(SCRIPT_TYPES.keys())}",
        )

    filepath = SCRIPTS_DIR / filename
    if filepath.exists():
        raise HTTPException(status_code=400, detail=f"脚本 {filename} 已存在")

    # 安全检查
    if not str(filepath.resolve()).startswith(str(SCRIPTS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法文件路径")

    content = request.content or f"# {request.description or filename}\n"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return {"message": f"脚本 {filename} 创建成功", "filename": filename}


@app.post("/api/scripts/update")
async def update_script(request: ScriptUpdateRequest):
    """更新脚本内容"""
    filepath = SCRIPTS_DIR / request.filename

    # 安全检查
    if not str(filepath.resolve()).startswith(str(SCRIPTS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法文件路径")
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"脚本 {request.filename} 不存在")

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(request.content)
        return {"message": f"脚本 {request.filename} 更新成功", "filename": request.filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入脚本失败: {str(e)}")


@app.delete("/api/scripts/{filename}")
async def delete_script(filename: str):
    """删除脚本"""
    filepath = SCRIPTS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"脚本 {filename} 不存在")

    # 安全检查
    if not str(filepath.resolve()).startswith(str(SCRIPTS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法文件路径")

    filepath.unlink()
    return {"message": f"脚本 {filename} 删除成功"}


@app.post("/api/scripts/upload")
async def upload_script(file: UploadFile = File(...)):
    """上传脚本文件"""
    filename = file.filename
    suffix = Path(filename).suffix.lower()

    if suffix not in SCRIPT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的脚本类型: {suffix}，支持: {list(SCRIPT_TYPES.keys())}",
        )

    filepath = SCRIPTS_DIR / filename
    if not str(filepath.resolve()).startswith(str(SCRIPTS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法文件路径")

    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    return {"message": f"脚本 {filename} 上传成功", "filename": filename}


@app.post("/api/scripts/run")
async def run_script(request: ScriptRunRequest):
    """执行指定脚本"""
    filepath = SCRIPTS_DIR / request.filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"脚本 {request.filename} 不存在")

    suffix = filepath.suffix.lower()
    if suffix not in SCRIPT_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的脚本类型: {suffix}")

    task_id = generate_task_id()

    tasks_store[task_id] = {
        "task_id": task_id,
        "env": "script",
        "status": "PENDING",
        "command": "",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "task_type": "script",
        "script_name": request.filename,
        "finished_at": None,
        "duration": None,
        "exit_code": None,
        "log": None,
        "report_url": None,
    }

    # 启动后台线程
    thread = threading.Thread(
        target=run_script_task,
        args=(task_id, request.filename, request.args),
        daemon=True,
    )
    thread.start()

    return {
        "task_id": task_id,
        "status": "PENDING",
        "message": f"脚本 {request.filename} 已提交执行，请通过 /api/status/{task_id} 查询状态",
    }


# ============================================================
# API 路由 - 任务执行（Pytest）
# ============================================================

@app.post("/api/run")
async def run_tests(request: RunRequest):
    """触发 Pytest 测试执行"""
    valid_envs = ["test_env", "staging_env"]
    if request.env not in valid_envs:
        raise HTTPException(status_code=400, detail=f"无效的环境参数: {request.env}，可选值: {valid_envs}")

    task_id = generate_task_id()

    tasks_store[task_id] = {
        "task_id": task_id,
        "env": request.env,
        "status": "PENDING",
        "command": "",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "task_type": "pytest",
        "script_name": None,
        "finished_at": None,
        "duration": None,
        "exit_code": None,
        "log": None,
        "report_url": None,
    }

    report_dir = REPORTS_DIR / task_id
    report_dir.mkdir(parents=True, exist_ok=True)

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
    summary = extract_summary_from_log(task.get("log", ""))

    return {**task, "summary": summary}


@app.get("/api/tasks")
async def get_tasks(limit: int = 20, status: Optional[str] = None, task_type: Optional[str] = None):
    """获取任务列表"""
    tasks = list(tasks_store.values())

    if status:
        tasks = [t for t in tasks if t["status"] == status]
    if task_type:
        tasks = [t for t in tasks if t.get("task_type") == task_type]

    tasks.sort(key=lambda x: x["created_at"], reverse=True)
    tasks = tasks[:limit]

    for task in tasks:
        task["summary"] = extract_summary_from_log(task.get("log", ""))

    return {"tasks": tasks, "total": len(tasks)}


# ============================================================
# API 路由 - 报告管理
# ============================================================

@app.get("/api/reports")
async def get_reports():
    """获取历史报告列表"""
    if not REPORTS_DIR.exists():
        return {"reports": [], "total": 0}

    reports = []
    for d in sorted(REPORTS_DIR.iterdir(), reverse=True):
        if d.is_dir() and not d.name.startswith("."):
            html_dir = d / "html"
            has_html = html_dir.exists() and (html_dir / "index.html").exists()
            task_info = tasks_store.get(d.name, {})

            report_entry = {
                "task_id": d.name,
                "created_at": task_info.get("created_at", ""),
                "env": task_info.get("env", ""),
                "has_html_report": has_html,
                "report_url": f"/reports/{d.name}/html/index.html" if has_html else f"/reports/{d.name}/",
                "status": task_info.get("status", "UNKNOWN"),
                "task_type": task_info.get("task_type", "unknown"),
                "script_name": task_info.get("script_name", ""),
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
# 健康检查 & 脚本类型查询
# ============================================================

@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "version": "1.1.0",
        "running_tasks": len([t for t in tasks_store.values() if t["status"] == "RUNNING"]),
        "total_tasks": len(tasks_store),
    }


@app.get("/api/script-types")
async def get_script_types():
    """获取支持的脚本类型列表"""
    result = []
    for suffix, info in SCRIPT_TYPES.items():
        result.append({
            "suffix": suffix,
            "label": info["label"],
            "command": info["command"],
            "icon": info["icon"],
            "color": info["color"],
        })
    return {"types": result}


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
