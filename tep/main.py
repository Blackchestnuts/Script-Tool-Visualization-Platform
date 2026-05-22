"""
测试效能平台（TEP）V1.2 - FastAPI 主应用
========================================
功能模块：
- Pytest 自动化测试执行引擎
- YAML 用例数据管理（模块化目录结构）
- 执行环境管理（CRUD，JSON 持久化）
- 通用脚本管理（Python / Shell / Bat 等）
- Allure 报告静态托管
- 任务状态管理与实时日志
"""

import os
import re
import json
import uuid
import shutil
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
ENV_FILE = DATA_DIR / "environments.json"  # 环境配置持久化文件

# 确保目录存在
for d in [DATA_DIR, REPORTS_DIR, TESTCASES_DIR, SCRIPTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================
# 脚本类型配置
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
# 任务状态存储
# ============================================================
tasks_store: dict = {}

# ============================================================
# 环境配置管理（JSON 持久化）
# ============================================================

def load_environments() -> list:
    """从 JSON 文件加载环境配置列表"""
    if not ENV_FILE.exists():
        # 首次启动，创建默认环境
        default_envs = [
            {
                "id": "test_env",
                "name": "测试环境",
                "base_url": "http://test-api.example.com",
                "description": "日常测试环境",
                "db_host": "test-mysql.internal",
                "db_port": 3306,
                "timeout": 30,
            },
            {
                "id": "staging_env",
                "name": "预发环境",
                "base_url": "http://staging-api.example.com",
                "description": "预发布验证环境",
                "db_host": "staging-mysql.internal",
                "db_port": 3306,
                "timeout": 30,
            },
        ]
        save_environments(default_envs)
        return default_envs

    try:
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception):
        return []


def save_environments(envs: list):
    """保存环境配置列表到 JSON 文件"""
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        json.dump(envs, f, ensure_ascii=False, indent=2)


# ============================================================
# Pydantic 数据模型
# ============================================================

class RunRequest(BaseModel):
    """执行测试的请求体"""
    env: str = "test_env"
    markers: Optional[str] = None
    testcase_path: Optional[str] = None


class CaseUpdateRequest(BaseModel):
    """更新用例数据的请求体"""
    filename: str
    content: str
    module: Optional[str] = None  # 所属模块（子目录名）


class CaseCreateRequest(BaseModel):
    """创建用例的请求体"""
    filename: str
    module: str  # 所属模块
    content: str = ""


class ModuleCreateRequest(BaseModel):
    """创建模块的请求体"""
    name: str
    description: str = ""


class ModuleRenameRequest(BaseModel):
    """重命名模块的请求体"""
    old_name: str
    new_name: str


class EnvCreateRequest(BaseModel):
    """创建环境的请求体"""
    id: str  # 环境唯一标识，如 test_env
    name: str  # 显示名称，如 测试环境
    base_url: str = ""
    description: str = ""
    db_host: str = ""
    db_port: int = 3306
    timeout: int = 30


class EnvUpdateRequest(BaseModel):
    """更新环境的请求体"""
    id: str
    name: Optional[str] = None
    base_url: Optional[str] = None
    description: Optional[str] = None
    db_host: Optional[str] = None
    db_port: Optional[int] = None
    timeout: Optional[int] = None


class ScriptUpdateRequest(BaseModel):
    filename: str
    content: str


class ScriptCreateRequest(BaseModel):
    filename: str
    content: str = ""
    description: str = ""


class ScriptRunRequest(BaseModel):
    filename: str
    args: Optional[str] = None


class TaskInfo(BaseModel):
    task_id: str
    env: str
    status: str
    command: str
    created_at: str
    task_type: str = "pytest"
    finished_at: Optional[str] = None
    duration: Optional[str] = None
    exit_code: Optional[int] = None
    log: Optional[str] = None
    report_url: Optional[str] = None


# ============================================================
# FastAPI 应用实例
# ============================================================
app = FastAPI(
    title="测试效能平台 TEP V1.2",
    description="接口自动化测试 + 脚本管理 + 环境管理的 Web 管控平台",
    version="1.2.0",
)

# 挂载静态文件
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
if REPORTS_DIR.exists():
    app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR), html=True), name="reports")

# Jinja2 模板引擎
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)


# ============================================================
# 工具函数
# ============================================================

def generate_task_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


def update_task_status(task_id: str, status: str, **kwargs):
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
    if task_id in tasks_store:
        tasks_store[task_id]["log"] = (stdout or "") + "\n" + (stderr or "")


def get_script_type_info(suffix: str) -> dict:
    return SCRIPT_TYPES.get(suffix, {"label": "未知", "command": "", "icon": "📄", "color": "#999"})


def parse_script_info(filepath: Path) -> dict:
    suffix = filepath.suffix.lower()
    type_info = get_script_type_info(suffix)
    stat = filepath.stat()
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


def get_module_dir(module_name: str) -> Path:
    """获取模块目录路径，并进行安全检查"""
    module_dir = DATA_DIR / module_name
    if not str(module_dir.resolve()).startswith(str(DATA_DIR.resolve())):
        raise ValueError("非法模块路径")
    return module_dir


def parse_yaml_cases(filepath: Path, module_name: str = "") -> dict:
    """解析单个 YAML 文件，返回结构化数据"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        try:
            rel_path = str(filepath.relative_to(BASE_DIR))
        except ValueError:
            rel_path = str(filepath)

        # 计算用例数量
        case_count = 0
        if data:
            if isinstance(data, list):
                case_count = len(data)
            elif isinstance(data, dict):
                if "test_cases" in data:
                    case_count = len(data["test_cases"])
                else:
                    case_count = 1

        return {
            "filename": filepath.name,
            "path": rel_path,
            "module": module_name,
            "case_count": case_count,
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
            "module": module_name,
            "case_count": 0,
            "error": f"YAML 解析错误: {str(e)}",
        }


def extract_summary_from_log(log: str) -> dict:
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
# 执行引擎
# ============================================================

def run_pytest_task(task_id: str, env: str, markers: Optional[str] = None, testcase_path: Optional[str] = None):
    update_task_status(task_id, "RUNNING")
    test_path = testcase_path or str(TESTCASES_DIR)

    command_parts = [
        "python", "-m", "pytest", test_path,
        f"--env={env}",
        f"--alluredir={REPORTS_DIR / task_id}",
        "-v", "--tb=short",
    ]
    if markers:
        command_parts.extend(["-m", markers])

    tasks_store[task_id]["command"] = " ".join(command_parts)

    try:
        result = subprocess.run(
            command_parts, capture_output=True, text=True, timeout=600,
            cwd=str(BASE_DIR), env={**os.environ, "TEST_ENV": env},
        )
        save_task_log(task_id, result.stdout, result.stderr)
        tasks_store[task_id]["exit_code"] = result.returncode
        update_task_status(task_id, "FINISHED")

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
    update_task_status(task_id, "RUNNING")
    filepath = SCRIPTS_DIR / filename
    suffix = filepath.suffix.lower()
    type_info = get_script_type_info(suffix)

    if suffix == ".bat":
        command_parts = ["cmd", "/c", str(filepath)]
    elif suffix == ".ps1":
        command_parts = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(filepath)]
    else:
        command_parts = [type_info["command"], str(filepath)]

    if args:
        command_parts.extend(args.split())

    tasks_store[task_id]["command"] = " ".join(command_parts)

    try:
        result = subprocess.run(
            command_parts, capture_output=True, text=True, timeout=600,
            cwd=str(BASE_DIR), env={**os.environ, "SCRIPT_NAME": filename},
        )
        save_task_log(task_id, result.stdout, result.stderr)
        tasks_store[task_id]["exit_code"] = result.returncode
        update_task_status(task_id, "FINISHED")
    except subprocess.TimeoutExpired:
        update_task_status(task_id, "ERROR")
        save_task_log(task_id, "", "脚本执行超时")
        tasks_store[task_id]["exit_code"] = -1
    except FileNotFoundError:
        update_task_status(task_id, "ERROR")
        save_task_log(task_id, "", f"找不到执行器: {type_info['command']}")
        tasks_store[task_id]["exit_code"] = -1
    except Exception as e:
        update_task_status(task_id, "ERROR")
        save_task_log(task_id, "", str(e))
        tasks_store[task_id]["exit_code"] = -1


# ============================================================
# 页面路由
# ============================================================

def render_template(template_name: str, **context) -> HTMLResponse:
    template = jinja_env.get_template(template_name)
    html = template.render(**context)
    return HTMLResponse(html)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return render_template("index.html", request=request)


@app.get("/cases", response_class=HTMLResponse)
async def cases_page(request: Request):
    return render_template("cases.html", request=request)


@app.get("/scripts", response_class=HTMLResponse)
async def scripts_page(request: Request):
    return render_template("scripts.html", request=request)


@app.get("/reports-page", response_class=HTMLResponse)
async def reports_page(request: Request):
    return render_template("reports.html", request=request)


# ============================================================
# API 路由 - 环境管理
# ============================================================

@app.get("/api/environments")
async def get_environments():
    """获取所有执行环境"""
    envs = load_environments()
    return {"environments": envs, "total": len(envs)}


@app.post("/api/environments")
async def create_environment(request: EnvCreateRequest):
    """新增执行环境"""
    envs = load_environments()

    # 检查 ID 唯一性
    if any(e["id"] == request.id for e in envs):
        raise HTTPException(status_code=400, detail=f"环境标识 '{request.id}' 已存在")

    new_env = {
        "id": request.id,
        "name": request.name,
        "base_url": request.base_url,
        "description": request.description,
        "db_host": request.db_host,
        "db_port": request.db_port,
        "timeout": request.timeout,
    }
    envs.append(new_env)
    save_environments(envs)

    # 同步更新 config.yaml 供 pytest 使用
    _sync_config_yaml(envs)

    return {"message": f"环境 '{request.name}' 创建成功", "environment": new_env}


@app.put("/api/environments")
async def update_environment(request: EnvUpdateRequest):
    """更新执行环境"""
    envs = load_environments()
    target = None
    for e in envs:
        if e["id"] == request.id:
            target = e
            break

    if not target:
        raise HTTPException(status_code=404, detail=f"环境 '{request.id}' 不存在")

    # 只更新提供了的字段
    if request.name is not None:
        target["name"] = request.name
    if request.base_url is not None:
        target["base_url"] = request.base_url
    if request.description is not None:
        target["description"] = request.description
    if request.db_host is not None:
        target["db_host"] = request.db_host
    if request.db_port is not None:
        target["db_port"] = request.db_port
    if request.timeout is not None:
        target["timeout"] = request.timeout

    save_environments(envs)
    _sync_config_yaml(envs)

    return {"message": f"环境 '{request.id}' 更新成功", "environment": target}


@app.delete("/api/environments/{env_id}")
async def delete_environment(env_id: str):
    """删除执行环境"""
    envs = load_environments()
    new_envs = [e for e in envs if e["id"] != env_id]

    if len(new_envs) == len(envs):
        raise HTTPException(status_code=404, detail=f"环境 '{env_id}' 不存在")

    # 至少保留一个环境
    if len(new_envs) == 0:
        raise HTTPException(status_code=400, detail="至少需要保留一个执行环境")

    save_environments(new_envs)
    _sync_config_yaml(new_envs)

    return {"message": f"环境 '{env_id}' 删除成功", "total": len(new_envs)}


def _sync_config_yaml(envs: list):
    """将环境配置同步写入 config.yaml，供 pytest conftest 读取"""
    config = {}
    for e in envs:
        config[e["id"]] = {
            "base_url": e.get("base_url", ""),
            "db_host": e.get("db_host", ""),
            "db_port": e.get("db_port", 3306),
            "timeout": e.get("timeout", 30),
        }
    config_path = BASE_DIR / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)


# ============================================================
# API 路由 - 模块管理
# ============================================================

@app.get("/api/modules")
async def get_modules():
    """获取所有用例模块（data/ 下的子目录）"""
    modules = []
    # 扫描 data/ 下的子目录
    for d in sorted(DATA_DIR.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            yaml_files = list(d.glob("*.yaml")) + list(d.glob("*.yml"))
            # 检查是否有模块描述文件
            desc_file = d / "_module.json"
            description = ""
            if desc_file.exists():
                try:
                    with open(desc_file, "r", encoding="utf-8") as f:
                        mod_info = json.load(f)
                        description = mod_info.get("description", "")
                except Exception:
                    pass

            modules.append({
                "name": d.name,
                "description": description,
                "case_count": len(yaml_files),
                "path": str(d.relative_to(BASE_DIR)),
            })

    return {"modules": modules, "total": len(modules)}


@app.post("/api/modules")
async def create_module(request: ModuleCreateRequest):
    """创建新模块（在 data/ 下新建子目录）"""
    module_name = request.name.strip()

    # 校验名称合法性
    if not module_name or not re.match(r'^[\w\u4e00-\u9fff]+$', module_name):
        raise HTTPException(status_code=400, detail="模块名称只能包含中文、字母、数字和下划线")

    try:
        module_dir = get_module_dir(module_name)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法模块名称")

    if module_dir.exists():
        raise HTTPException(status_code=400, detail=f"模块 '{module_name}' 已存在")

    module_dir.mkdir(parents=True, exist_ok=True)

    # 写入模块描述文件
    if request.description:
        desc_file = module_dir / "_module.json"
        with open(desc_file, "w", encoding="utf-8") as f:
            json.dump({"name": module_name, "description": request.description}, f, ensure_ascii=False, indent=2)

    return {"message": f"模块 '{module_name}' 创建成功", "name": module_name}


@app.put("/api/modules")
async def rename_module(request: ModuleRenameRequest):
    """重命名模块"""
    try:
        old_dir = get_module_dir(request.old_name)
        new_dir = get_module_dir(request.new_name)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法模块名称")

    if not old_dir.exists():
        raise HTTPException(status_code=404, detail=f"模块 '{request.old_name}' 不存在")
    if new_dir.exists():
        raise HTTPException(status_code=400, detail=f"模块 '{request.new_name}' 已存在")

    old_dir.rename(new_dir)
    return {"message": f"模块 '{request.old_name}' 已重命名为 '{request.new_name}'"}


@app.delete("/api/modules/{module_name}")
async def delete_module(module_name: str):
    """删除模块及其所有用例"""
    try:
        module_dir = get_module_dir(module_name)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法模块名称")

    if not module_dir.exists():
        raise HTTPException(status_code=404, detail=f"模块 '{module_name}' 不存在")

    # 删除整个目录
    shutil.rmtree(module_dir)
    return {"message": f"模块 '{module_name}' 及其所有用例已删除"}


# ============================================================
# API 路由 - 用例管理（模块化）
# ============================================================

@app.get("/api/cases")
async def get_cases(module: Optional[str] = None):
    """获取用例列表，支持按模块过滤"""
    if module:
        # 获取指定模块下的用例
        try:
            module_dir = get_module_dir(module)
        except ValueError:
            raise HTTPException(status_code=400, detail="非法模块名称")
        if not module_dir.exists():
            raise HTTPException(status_code=404, detail=f"模块 '{module}' 不存在")

        yaml_files = list(module_dir.glob("*.yaml")) + list(module_dir.glob("*.yml"))
        cases = []
        for f in sorted(yaml_files):
            cases.append(parse_yaml_cases(f, module))
        return {"cases": cases, "total": len(cases), "module": module}
    else:
        # 获取所有模块的所有用例
        all_cases = []
        for d in sorted(DATA_DIR.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                yaml_files = list(d.glob("*.yaml")) + list(d.glob("*.yml"))
                for f in sorted(yaml_files):
                    all_cases.append(parse_yaml_cases(f, d.name))
        # 兼容：也扫描 data/ 根目录下的 YAML（非模块化用例）
        root_yamls = [f for f in DATA_DIR.glob("*.yaml") if f.name != "environments.json"] + list(DATA_DIR.glob("*.yml"))
        for f in sorted(root_yamls):
            all_cases.append(parse_yaml_cases(f, "(根目录)"))
        return {"cases": all_cases, "total": len(all_cases)}


@app.get("/api/cases/{module}/{filename}")
async def get_case_detail(module: str, filename: str):
    """获取单个用例文件详情"""
    try:
        module_dir = get_module_dir(module)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法模块名称")

    filepath = module_dir / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"文件 {module}/{filename} 不存在")

    case_data = parse_yaml_cases(filepath, module)
    with open(filepath, "r", encoding="utf-8") as f:
        case_data["raw_content"] = f.read()
    return case_data


@app.post("/api/cases/create")
async def create_case(request: CaseCreateRequest):
    """在指定模块下创建用例文件"""
    try:
        module_dir = get_module_dir(request.module)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法模块名称")

    if not module_dir.exists():
        raise HTTPException(status_code=404, detail=f"模块 '{request.module}' 不存在")

    filename = request.filename
    if not filename.endswith((".yaml", ".yml")):
        filename += ".yaml"

    filepath = module_dir / filename
    if filepath.exists():
        raise HTTPException(status_code=400, detail=f"文件 {filename} 已存在")
    if not str(filepath.resolve()).startswith(str(module_dir.resolve())):
        raise HTTPException(status_code=400, detail="非法文件路径")

    content = request.content or f"# {request.module} - {filename}\ntest_module: {request.module}\ntest_cases: []\n"
    if content:
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise HTTPException(status_code=400, detail=f"YAML 格式错误: {str(e)}")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return {"message": f"文件 {request.module}/{filename} 创建成功", "filename": filename, "module": request.module}


@app.post("/api/cases/update")
async def update_case(request: CaseUpdateRequest):
    """更新用例数据"""
    module = request.module or ""
    if module:
        try:
            base = get_module_dir(module)
        except ValueError:
            raise HTTPException(status_code=400, detail="非法模块名称")
    else:
        base = DATA_DIR

    filepath = base / request.filename
    if not str(filepath.resolve()).startswith(str(base.resolve())):
        raise HTTPException(status_code=400, detail="非法文件路径")
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"文件 {request.filename} 不存在")

    try:
        yaml.safe_load(request.content)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"YAML 格式错误: {str(e)}")

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(request.content)
        return {"message": f"文件 {request.filename} 更新成功"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入文件失败: {str(e)}")


@app.delete("/api/cases/{module}/{filename}")
async def delete_case(module: str, filename: str):
    """删除用例文件"""
    try:
        module_dir = get_module_dir(module)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法模块名称")

    filepath = module_dir / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"文件 {module}/{filename} 不存在")

    filepath.unlink()
    return {"message": f"文件 {module}/{filename} 删除成功"}


# ============================================================
# API 路由 - 脚本管理
# ============================================================

@app.get("/api/scripts")
async def get_scripts():
    supported_suffixes = set(SCRIPT_TYPES.keys())
    script_files = [f for f in SCRIPTS_DIR.iterdir() if f.is_file() and f.suffix.lower() in supported_suffixes]
    if not script_files:
        return {"scripts": [], "total": 0}
    scripts = []
    for f in sorted(script_files):
        scripts.append(parse_script_info(f))
    return {"scripts": scripts, "total": len(scripts)}


@app.get("/api/scripts/{filename}")
async def get_script_detail(filename: str):
    filepath = SCRIPTS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"脚本 {filename} 不存在")
    if not str(filepath.resolve()).startswith(str(SCRIPTS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法文件路径")
    info = parse_script_info(filepath)
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        info["content"] = f.read()
    return info


@app.post("/api/scripts/create")
async def create_script(request: ScriptCreateRequest):
    suffix = Path(request.filename).suffix.lower()
    if suffix not in SCRIPT_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的脚本类型: {suffix}")
    filepath = SCRIPTS_DIR / request.filename
    if filepath.exists():
        raise HTTPException(status_code=400, detail=f"脚本 {request.filename} 已存在")
    if not str(filepath.resolve()).startswith(str(SCRIPTS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法文件路径")
    content = request.content or f"# {request.description or request.filename}\n"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return {"message": f"脚本 {request.filename} 创建成功", "filename": request.filename}


@app.post("/api/scripts/update")
async def update_script(request: ScriptUpdateRequest):
    filepath = SCRIPTS_DIR / request.filename
    if not str(filepath.resolve()).startswith(str(SCRIPTS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法文件路径")
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"脚本 {request.filename} 不存在")
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(request.content)
        return {"message": f"脚本 {request.filename} 更新成功"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/scripts/{filename}")
async def delete_script(filename: str):
    filepath = SCRIPTS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"脚本 {filename} 不存在")
    if not str(filepath.resolve()).startswith(str(SCRIPTS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法文件路径")
    filepath.unlink()
    return {"message": f"脚本 {filename} 删除成功"}


@app.post("/api/scripts/upload")
async def upload_script(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in SCRIPT_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的脚本类型: {suffix}")
    filepath = SCRIPTS_DIR / file.filename
    if not str(filepath.resolve()).startswith(str(SCRIPTS_DIR.resolve())):
        raise HTTPException(status_code=400, detail="非法文件路径")
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)
    return {"message": f"脚本 {file.filename} 上传成功", "filename": file.filename}


@app.post("/api/scripts/run")
async def run_script(request: ScriptRunRequest):
    filepath = SCRIPTS_DIR / request.filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"脚本 {request.filename} 不存在")
    suffix = filepath.suffix.lower()
    if suffix not in SCRIPT_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的脚本类型: {suffix}")

    task_id = generate_task_id()
    tasks_store[task_id] = {
        "task_id": task_id, "env": "script", "status": "PENDING", "command": "",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "task_type": "script", "script_name": request.filename,
        "finished_at": None, "duration": None, "exit_code": None, "log": None, "report_url": None,
    }
    thread = threading.Thread(target=run_script_task, args=(task_id, request.filename, request.args), daemon=True)
    thread.start()
    return {"task_id": task_id, "status": "PENDING", "message": f"脚本 {request.filename} 已提交执行"}


# ============================================================
# API 路由 - 任务执行
# ============================================================

@app.post("/api/run")
async def run_tests(request: RunRequest):
    """触发 Pytest 测试执行"""
    # 动态验证环境（从 environments.json 读取）
    envs = load_environments()
    valid_env_ids = [e["id"] for e in envs]
    if request.env not in valid_env_ids:
        raise HTTPException(status_code=400, detail=f"无效的环境: {request.env}，可选: {valid_env_ids}")

    task_id = generate_task_id()
    tasks_store[task_id] = {
        "task_id": task_id, "env": request.env, "status": "PENDING", "command": "",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "task_type": "pytest", "script_name": None,
        "finished_at": None, "duration": None, "exit_code": None, "log": None, "report_url": None,
    }
    report_dir = REPORTS_DIR / task_id
    report_dir.mkdir(parents=True, exist_ok=True)

    thread = threading.Thread(
        target=run_pytest_task,
        args=(task_id, request.env, request.markers, request.testcase_path),
        daemon=True,
    )
    thread.start()
    return {"task_id": task_id, "status": "PENDING", "message": "测试任务已提交"}


@app.get("/api/status/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in tasks_store:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    task = tasks_store[task_id]
    summary = extract_summary_from_log(task.get("log", ""))
    return {**task, "summary": summary}


@app.get("/api/tasks")
async def get_tasks(limit: int = 20, status: Optional[str] = None, task_type: Optional[str] = None):
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
    if task_id not in tasks_store:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    log = tasks_store[task_id].get("log", "")
    if tail and log:
        log = "\n".join(log.splitlines()[-tail:])
    return {"task_id": task_id, "log": log}


# ============================================================
# 健康检查 & 类型查询
# ============================================================

@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "version": "1.2.0",
        "running_tasks": len([t for t in tasks_store.values() if t["status"] == "RUNNING"]),
        "total_tasks": len(tasks_store),
    }


@app.get("/api/script-types")
async def get_script_types():
    result = []
    for suffix, info in SCRIPT_TYPES.items():
        result.append({"suffix": suffix, "label": info["label"], "command": info["command"],
                       "icon": info["icon"], "color": info["color"]})
    return {"types": result}


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
