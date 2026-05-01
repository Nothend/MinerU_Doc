import os
import sys
import subprocess
import shutil
import json
from pathlib import Path
from datetime import datetime
import zipfile
import re

# --- 配置区域 ---
ROOT_DIR = Path(r"D:\ai_offline_pack")
WHEEL_DIR = ROOT_DIR / "wheels" / "mineru"
ENV_DIR = ROOT_DIR / "envs" / "env_mineru"
EXPORT_ENV_DIR = ROOT_DIR / "envs" / "export_env_mineru"
MODEL_ROOT = ROOT_DIR / "models"
PATCH_DIR = ROOT_DIR / "patch"  # 新增：补丁包存放目录
PATCH_CONFIG_FILE = ROOT_DIR / "patch_config.json"  # 新增：补丁配置文件

REQ_FILE_NAME = "requirements_mineru.txt"
LOCK_FILE_NAME = "requirements_mineru_lock.txt"

# 镜像源
MAIN_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
EXTRA_INDEX_1 = "https://download.pytorch.org/whl/cu121"
EXTRA_INDEX_2 = "https://pypi.org/simple"

# 核心包 (用于兜底)
CORE_PKGS = ["pip", "setuptools", "wheel"]

# --- 工具函数 ---
class Color:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    END = '\033[0m'
    BOLD = '\033[1m'

def log_info(msg): print(f"{Color.BLUE}[INFO]{Color.END} {msg}")
def log_ok(msg): print(f"{Color.GREEN}[OK]{Color.END} {msg}")
def log_warn(msg): print(f"{Color.YELLOW}[WARN]{Color.END} {msg}")
def log_fatal(msg): 
    print(f"{Color.RED}[FATAL]{Color.END} {msg}")
    input("按任意键退出...")
    sys.exit(1)

def run_cmd(cmd, shell=False, check=True):
    """运行命令，支持列表或字符串"""
    try:
        if isinstance(cmd, list) and not shell:
            proc = subprocess.run(cmd, check=check, shell=False)
        else:
            proc = subprocess.run(cmd, check=check, shell=True)
        return proc
    except subprocess.CalledProcessError as e:
        if check:
            log_fatal(f"命令执行失败：{e}")
        return None

def parse_package_spec(spec_str):
    """解析包名和版本，例如 'transformers==4.57.2' -> ('transformers', '==4.57.2')"""
    match = re.match(r"([a-zA-Z0-9_-]+)(.*)", spec_str)
    if match:
        return match.group(1), match.group(2) if match.group(2) else ""
    return spec_str, ""

def build_patch_package():
    """构建增量补丁包"""
    log_info("=== 开始构建增量补丁包 ===")
    
    if not PATCH_CONFIG_FILE.exists():
        log_fatal(f"未找到补丁配置文件：{PATCH_CONFIG_FILE}\n请先创建该文件定义需要更新的包。")
    
    with open(PATCH_CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    version = config.get("version", "1.0.0")
    description = config.get("description", "未知补丁")
    packages = config.get("packages", {})
    
    install_list = packages.get("install", [])
    upgrade_list = packages.get("upgrade", [])
    uninstall_list = packages.get("uninstall", [])
    
    log_info(f"补丁版本：{version}")
    log_info(f"描述：{description}")
    log_info(f"待安装包：{[p['spec'] if isinstance(p, dict) else p for p in install_list]}")
    log_info(f"待升级包：{[p['spec'] if isinstance(p, dict) else p for p in upgrade_list]}")
    log_info(f"待卸载包：{uninstall_list}")
    
    # 创建一个临时环境来解析依赖和下载 Wheels (避免污染主环境)
    temp_env_dir = ROOT_DIR / "envs" / "temp_patch_env"
    if temp_env_dir.exists():
        log_info("清理临时环境...")
        shutil.rmtree(temp_env_dir)
    
    conda_exe = shutil.which("conda")
    if not conda_exe:
        log_fatal("未找到 conda 命令。")
        
    log_info("创建临时环境用于解析依赖...")
    run_cmd([conda_exe, "create", "-y", "-p", str(temp_env_dir), "python=3.10"])
    temp_python = str(temp_env_dir / "python.exe")
    
    patch_wheels_dir = PATCH_DIR / "wheels_temp"
    if patch_wheels_dir.exists():
        shutil.rmtree(patch_wheels_dir)
    patch_wheels_dir.mkdir(parents=True, exist_ok=True)
    
    download_args = [
        temp_python, "-m", "pip", "download",
        "-d", str(patch_wheels_dir),
        "--index-url", MAIN_INDEX,
        "--extra-index-url", EXTRA_INDEX_1,
        "--extra-index-url", EXTRA_INDEX_2
    ]
    
    all_specs = []
    for pkg in install_list:
        spec = pkg['spec'] if isinstance(pkg, dict) else pkg
        all_specs.append(spec)
    for pkg in upgrade_list:
        spec = pkg['spec'] if isinstance(pkg, dict) else pkg
        all_specs.append(spec)
        
    if all_specs:
        log_info(f"正在下载补丁包依赖：{all_specs}")
        run_cmd(download_args + all_specs)
        
    # 打包
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    patch_filename = f"MinERU_Patch_v{version}_{ts}.zip"
    patch_zip_path = PATCH_DIR / patch_filename
    
    # 生成 manifest.json 记录补丁信息
    manifest = {
        "version": version,
        "description": description,
        "created_at": datetime.now().isoformat(),
        "packages": {
            "install": install_list,
            "upgrade": upgrade_list,
            "uninstall": uninstall_list
        }
    }
    manifest_path = patch_wheels_dir / "manifest.json"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        
    log_info(f"正在打包补丁至：{patch_zip_path}")
    with zipfile.ZipFile(patch_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in patch_wheels_dir.rglob("*"):
            if file.is_file():
                arcname = file.relative_to(patch_wheels_dir)
                zipf.write(file, arcname)
                
    # 清理
    log_info("清理临时环境...")
    shutil.rmtree(temp_env_dir)
    shutil.rmtree(patch_wheels_dir)
    
    log_ok(f"补丁包构建成功：{patch_filename}")
    log_info(f"请将此文件复制到 B 机的 {PATCH_DIR} 目录下。")
    input("按任意键退出...")

def build_full_package():
    """原有的全量构建逻辑"""
    log_info("=== 开始全量构建 ===")
    
    # --- STEP 1: 检查 Conda ---
    log_info("检查 Conda 环境...")
    conda_exe = shutil.which("conda")
    if not conda_exe:
        log_fatal("未找到 conda 命令，请确保已安装 Anaconda/Miniconda 并加入 PATH。")

    # --- STEP 3: 创建/准备环境 ---
    log_info(f"正在清理并重建环境：{ENV_DIR}")
    if ENV_DIR.exists(): 
        shutil.rmtree(ENV_DIR)
    run_cmd([conda_exe, "create", "-y", "-p", str(ENV_DIR), "python=3.10"])
    
    python_exe = str(ENV_DIR / "python.exe")

    # --- STEP 4: 安装依赖 ---
    log_info("正在安装依赖到 A 机环境...")
    
    # 基础安装参数
    pip_args = [
        "-m", "pip", "install", 
        "--use-deprecated=legacy-resolver",
        "--index-url", MAIN_INDEX,
        "--extra-index-url", EXTRA_INDEX_1,
        "--extra-index-url", EXTRA_INDEX_2
    ]

    # 先装 av (解决某些奇怪的编译问题)
    log_info("安装 av...")
    run_cmd([python_exe] + pip_args + ["av"])

    # 从 requirements 文件安装
    req_file = Path(__file__).parent / REQ_FILE_NAME
    if req_file.exists():
        log_info(f"使用配置文件安装：{req_file}")
        run_cmd([python_exe] + pip_args + ["-r", str(req_file)])
    else:
        log_warn(f"未找到 {REQ_FILE_NAME}，直接安装核心包。")
        run_cmd([python_exe] + pip_args + CORE_PKGS)

    # 强制校验核心包版本
    log_info("强制校验核心依赖版本...")
    run_cmd([python_exe] + pip_args + CORE_PKGS)
    
    # 生成锁定表
    lock_file = Path(__file__).parent / LOCK_FILE_NAME
    log_info(f"更新锁定表：{lock_file}")
    with open(lock_file, "w", encoding="utf-8") as f:
        subprocess.run([python_exe, "-m", "pip", "freeze"], stdout=f)

    # --- STEP 5: 下载 Wheels ---
    log_info("开始下载离线 Wheels 包...")
    WHEEL_DIR.mkdir(parents=True, exist_ok=True)
    
    # 记录下载前的文件
    before_wheels = set(f.name for f in WHEEL_DIR.glob("*.whl")) if WHEEL_DIR.exists() else set()
    
    download_args = [
        "-m", "pip", "download",
        "-d", str(WHEEL_DIR),
        "--index-url", MAIN_INDEX,
        "--extra-index-url", EXTRA_INDEX_1,
        "--extra-index-url", EXTRA_INDEX_2
    ]

    # 下载 GPU Torch
    log_info("下载 GPU Torch (cu121)...")
    run_cmd([python_exe] + download_args + [
        "torch==2.4.1", "torchvision==0.19.1", "torchaudio==2.4.1",
        "--index-url", "https://download.pytorch.org/whl/cu121/",
        "--no-deps"
    ])

    # 下载其他
    log_info("下载全量依赖包...")
    if lock_file.exists():
        run_cmd([python_exe] + download_args + ["-r", str(lock_file)])
    else:
        log_warn("锁定表不存在，跳过全量依赖下载。")
    
    # 提取新增 Wheels (用于增量分发参考)
    after_wheels = set(f.name for f in WHEEL_DIR.glob("*.whl"))
    new_wheels = after_wheels - before_wheels
    
    if new_wheels:
        ts = datetime.now().strftime("%Y%m%d%H%M")
        new_dir = WHEEL_DIR / f"newWheels_{ts}"
        new_dir.mkdir(exist_ok=True)
        for w in new_wheels:
            shutil.copy2(WHEEL_DIR / w, new_dir / w)
        log_ok(f"发现 {len(new_wheels)} 个新包，已提取至：{new_dir.name}")
    else:
        log_info("未发现新增依赖包。")

    # --- STEP 6: 下载模型 ---
    log_info("准备 VLM 模型...")
    model_name = "MinerU2.5-Pro-2604-1.2B"
    model_dir = MODEL_ROOT / model_name
    if (model_dir / "model.safetensors").exists():
        log_ok("模型已存在，跳过。")
    else:
        log_info("模型不存在，尝试下载 (需要 modelscope)...")
        MODEL_ROOT.mkdir(parents=True, exist_ok=True)
        # 检查 modelscope 是否安装
        try:
            subprocess.run([python_exe, "-c", "import modelscope"], check=True, capture_output=True)
            download_script = f"""
from modelscope.hub.snapshot_download import snapshot_download
snapshot_download('OpenDataLab/{model_name}', cache_dir=r'{MODEL_ROOT}', local_dir=r'{model_dir}')
"""
            run_cmd([python_exe, "-c", download_script])
            log_ok("模型下载完成。")
        except subprocess.CalledProcessError:
            log_warn("未安装 modelscope 或下载失败，请手动下载模型。")

    # --- STEP 7: 导出环境 ---
    log_info("导出环境快照...")
    EXPORT_ENV_DIR.mkdir(parents=True, exist_ok=True)
    
    if EXPORT_ENV_DIR.exists(): 
        shutil.rmtree(EXPORT_ENV_DIR)
    
    log_info(f"同步：{ENV_DIR} -> {EXPORT_ENV_DIR}")
    # Windows robocopy
    run_cmd(f'robocopy "{ENV_DIR}" "{EXPORT_ENV_DIR}" /MIR /R:2 /W:2 /NFL /NDL /NJH /NJS', shell=True, check=False)
    log_ok("环境导出成功。")

    print(f"\n{Color.GREEN}====================================================={Color.END}")
    print(f"{Color.BOLD}   构建完成！请将 {ROOT_DIR} 拷贝至 B 机。{Color.END}")
    print(f"{Color.GREEN}====================================================={Color.END}\n")
    input("按任意键退出...")

def main():
    print(f"{Color.BOLD}========================================{Color.END}")
    print(f"{Color.BOLD}   MinerU 离线环境构建工具 (A 机){Color.END}")
    print(f"{Color.BOLD}========================================{Color.END}\n")
    
    print(f"根目录：{ROOT_DIR}")
    print(f"Wheels 目录：{WHEEL_DIR}")
    print(f"环境目录：{ENV_DIR}")
    print(f"补丁目录：{PATCH_DIR}\n")
    
    # 模式选择
    print(f"{Color.YELLOW}[请选择构建模式]{Color.END}:")
    print(f"  {Color.BOLD}[1] 全量构建{Color.END} - 删除旧环境重新安装，下载所有依赖 (最稳定)")
    print(f"  {Color.BOLD}[2] 增量补丁包{Color.END} - 根据 patch_config.json 生成补丁包 (最快)")
    
    choice = input(f"\n  请输入选项 (1/2) [默认 1]: ").strip()
    
    if choice == "2":
        build_patch_package()
    else:
        # 二次确认全量构建
        if ENV_DIR.exists():
            confirm = input(f"\n{Color.YELLOW}[警告]{Color.END} 即将删除现有环境 {ENV_DIR} 并重建。确认？(y/n): ").strip().lower()
            if confirm != 'y':
                log_info("操作已取消。")
                return
        build_full_package()

if __name__ == "__main__":
    main()
