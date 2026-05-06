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
MODEL_ROOT = ROOT_DIR / "models"

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

def zip_directory_with_progress(src_dir: Path, zip_file: Path):
    src_dir = Path(src_dir)
    zip_file = Path(zip_file)
    if not src_dir.exists():
        log_warn(f"源目录不存在，无法打包: {src_dir}")
        return
        
    log_info(f"正在扫描文件: {src_dir}")
    file_list = []
    for root, dirs, files in os.walk(src_dir):
        for f in files:
            file_list.append(Path(root) / f)
            
    total_files = len(file_list)
    if total_files == 0:
        log_warn(f"源目录为空: {src_dir}")
        return
        
    log_info(f"开始打包 (共 {total_files} 个文件) -> {zip_file}")
    zip_file.parent.mkdir(parents=True, exist_ok=True)
    
    with zipfile.ZipFile(zip_file, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zipf:
        for i, file_path in enumerate(file_list, 1):
            arcname = file_path.relative_to(src_dir)
            zipf.write(file_path, arcname)
            
            # 简单的进度条
            if i % max(1, total_files // 100) == 0 or i == total_files:
                percent = i * 100 // total_files
                bar = "#" * (percent // 2) + "-" * (50 - percent // 2)
                sys.stdout.write(f"\r  [{bar}] {percent}% ({i}/{total_files})")
                sys.stdout.flush()
    print() # 换行
    log_ok(f"打包完成: {zip_file.name} (大小: {zip_file.stat().st_size / (1024*1024):.2f} MB)")

class EnvConfig:
    def __init__(self, name, env_dir_name, req_file, patch_file, wheel_dir_name, prefix_name):
        self.name = name
        self.prefix = prefix_name
        
        self.ENV_DIR = ROOT_DIR / "envs" / env_dir_name
        self.WHEEL_DIR = ROOT_DIR / "wheels" / wheel_dir_name
        
        # 导出目录 (全量产物)
        self.EXPORT_DIR = ROOT_DIR / "exported" / f"full_{prefix_name.lower()}"
        
        # 补丁目录 (增量产物)
        self.PATCH_DIR = ROOT_DIR / "patch" / f"patch_{prefix_name.lower()}"
        
        self.REQ_FILE = Path(__file__).parent / req_file
        self.LOCK_FILE = Path(__file__).parent / f"{req_file.replace('.txt', '_lock.txt')}"
        self.PATCH_CONFIG_FILE = ROOT_DIR / patch_file

ENV_PAPER_CONFIG = EnvConfig(
    name="大模型工作环境 (env_paper)",
    env_dir_name="env_paper",
    req_file="requirements_paper.txt",
    patch_file="patch_config_paper.json",
    wheel_dir_name="paper",
    prefix_name="Paper"
)

ENV_MINERU_CONFIG = EnvConfig(
    name="MinerU 工作环境 (env_mineru)",
    env_dir_name="env_mineru",
    req_file="requirements_mineru.txt",
    patch_file="patch_config_mineru.json",
    wheel_dir_name="mineru",
    prefix_name="MinERU"
)

def build_patch_package(config: EnvConfig):
    """构建增量补丁包"""
    log_info(f"=== 开始构建增量补丁包 ({config.name}) ===")
    
    if not config.PATCH_CONFIG_FILE.exists():
        log_fatal(f"未找到补丁配置文件：{config.PATCH_CONFIG_FILE}\n请先创建该文件定义需要更新的包。")
    
    with open(config.PATCH_CONFIG_FILE, 'r', encoding='utf-8') as f:
        patch_config = json.load(f)
    
    version = patch_config.get("version", "1.0.0")
    description = patch_config.get("description", "未知补丁")
    packages = patch_config.get("packages", {})
    
    install_list = packages.get("install", [])
    upgrade_list = packages.get("upgrade", [])
    uninstall_list = packages.get("uninstall", [])
    
    log_info(f"补丁版本：{version}")
    log_info(f"描述：{description}")
    log_info(f"待安装包：{[p['spec'] if isinstance(p, dict) else p for p in install_list]}")
    log_info(f"待升级包：{[p['spec'] if isinstance(p, dict) else p for p in upgrade_list]}")
    log_info(f"待卸载包：{uninstall_list}")
    
    # 创建一个临时环境来解析依赖和下载 Wheels (避免污染主环境)
    temp_env_dir = ROOT_DIR / "envs" / f"temp_patch_env_{config.prefix.lower()}"
    if temp_env_dir.exists():
        log_info("清理临时环境...")
        shutil.rmtree(temp_env_dir)
    
    conda_exe = shutil.which("conda")
    if not conda_exe:
        log_fatal("未找到 conda 命令。")
        
    log_info("创建临时环境用于解析依赖...")
    run_cmd([conda_exe, "create", "-y", "-p", str(temp_env_dir), "python=3.10"])
    temp_python = str(temp_env_dir / "python.exe")
    
    patch_wheels_dir = config.PATCH_DIR / "wheels_temp"
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
        
    # 打包
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    patch_filename = f"{config.prefix}_Patch_v{version}_{ts}.zip"
    patch_zip_path = config.PATCH_DIR / patch_filename
    
    log_info("正在打包增量补丁包...")
    zip_directory_with_progress(patch_wheels_dir, patch_zip_path)
                
    # 清理
    log_info("清理临时环境...")
    shutil.rmtree(temp_env_dir)
    shutil.rmtree(patch_wheels_dir)
    
    print(f"\n{Color.GREEN}====================================================={Color.END}")
    print(f"{Color.BOLD}   补丁包构建成功！产物已存放在：{config.PATCH_DIR}{Color.END}")
    print(f"{Color.BOLD}   请将 {patch_filename} 拷贝至 B 机进行增量部署。{Color.END}")
    print(f"{Color.GREEN}====================================================={Color.END}\n")
    input("按任意键退出...")

def build_full_package(config: EnvConfig):
    """全量构建逻辑"""
    log_info(f"=== 开始全量构建 ({config.name}) ===")
    
    # --- STEP 1: 检查 Conda ---
    log_info("检查 Conda 环境...")
    conda_exe = shutil.which("conda")
    if not conda_exe:
        log_fatal("未找到 conda 命令，请确保已安装 Anaconda/Miniconda 并加入 PATH。")

    # --- STEP 2: 创建/准备环境 ---
    log_info(f"正在清理并重建环境：{config.ENV_DIR}")
    if config.ENV_DIR.exists(): 
        shutil.rmtree(config.ENV_DIR)
    run_cmd([conda_exe, "create", "-y", "-p", str(config.ENV_DIR), "python=3.10"])
    
    python_exe = str(config.ENV_DIR / "python.exe")

    # --- STEP 3: 安装依赖 ---
    log_info("正在安装依赖到 A 机环境...")
    
    # 基础安装参数
    pip_args = [
        "-m", "pip", "install", 
        "--use-deprecated=legacy-resolver",
        "--index-url", MAIN_INDEX,
        "--extra-index-url", EXTRA_INDEX_1,
        "--extra-index-url", EXTRA_INDEX_2
    ]

    # 不同环境的特殊前置处理
    if config.prefix == "MinERU":
        log_info("安装 av...")
        run_cmd([python_exe] + pip_args + ["av"])
    elif config.prefix == "Paper":
        log_info("预安装 GPU Torch (Paper 环境要求)...")
        run_cmd([python_exe] + pip_args + [
            "torch==2.1.2", "torchvision==0.16.2", "torchaudio==2.1.2",
            "--index-url", "https://download.pytorch.org/whl/cu121"
        ])

    # 从 requirements 文件安装
    if config.REQ_FILE.exists():
        log_info(f"使用配置文件安装：{config.REQ_FILE}")
        run_cmd([python_exe] + pip_args + ["-r", str(config.REQ_FILE)])
    else:
        log_warn(f"未找到 {config.REQ_FILE.name}，直接安装核心包。")
        run_cmd([python_exe] + pip_args + CORE_PKGS)

    # 强制校验核心包版本
    log_info("强制校验核心依赖版本...")
    run_cmd([python_exe] + pip_args + CORE_PKGS)
    
    # 生成锁定表
    log_info(f"更新锁定表：{config.LOCK_FILE.name}")
    with open(config.LOCK_FILE, "w", encoding="utf-8") as f:
        subprocess.run([python_exe, "-m", "pip", "freeze"], stdout=f)

    # --- STEP 4: 下载 Wheels ---
    log_info("开始下载离线 Wheels 包...")
    config.WHEEL_DIR.mkdir(parents=True, exist_ok=True)
    
    download_args = [
        "-m", "pip", "download",
        "-d", str(config.WHEEL_DIR),
        "--index-url", MAIN_INDEX,
        "--extra-index-url", EXTRA_INDEX_1,
        "--extra-index-url", EXTRA_INDEX_2
    ]

    # 下载 GPU Torch
    if config.prefix == "MinERU":
        log_info("下载 GPU Torch 2.4.1 (cu121)...")
        run_cmd([python_exe] + download_args + [
            "torch==2.4.1", "torchvision==0.19.1", "torchaudio==2.4.1",
            "--index-url", "https://download.pytorch.org/whl/cu121/",
            "--no-deps"
        ])
    elif config.prefix == "Paper":
        log_info("下载 GPU Torch 2.1.2 (cu121)...")
        run_cmd([python_exe] + download_args + [
            "torch==2.1.2", "torchvision==0.16.2", "torchaudio==2.1.2",
            "--index-url", "https://download.pytorch.org/whl/cu121/",
            "--no-deps"
        ])

    # 下载其他
    log_info("下载全量依赖包...")
    if config.LOCK_FILE.exists():
        run_cmd([python_exe] + download_args + ["-r", str(config.LOCK_FILE)])
    else:
        log_warn("锁定表不存在，跳过全量依赖下载。")

    # --- STEP 5: 下载模型 (仅限 MinERU) ---
    if config.prefix == "MinERU":
        log_info("准备 VLM 模型...")
        model_name = "MinerU2.5-Pro-2604-1.2B"
        model_dir = MODEL_ROOT / model_name
        if (model_dir / "model.safetensors").exists():
            log_ok("模型已存在，跳过。")
        else:
            log_info("模型不存在，尝试下载 (需要 modelscope)...")
            MODEL_ROOT.mkdir(parents=True, exist_ok=True)
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

    # --- STEP 6: 导出产物 (ZIP 打包) ---
    log_info("导出环境与产物...")
    if config.EXPORT_DIR.exists():
        shutil.rmtree(config.EXPORT_DIR)
    config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 复制 requirements 文件
    if config.REQ_FILE.exists():
        shutil.copy2(config.REQ_FILE, config.EXPORT_DIR / config.REQ_FILE.name)
        log_info(f"已复制: {config.REQ_FILE.name}")
    if config.LOCK_FILE.exists():
        shutil.copy2(config.LOCK_FILE, config.EXPORT_DIR / config.LOCK_FILE.name)
        log_info(f"已复制: {config.LOCK_FILE.name}")
        
    # 打包 Wheels
    log_info("正在打包离线依赖包 (Wheels)...")
    wheel_zip_path = config.EXPORT_DIR / f"full_wheel_{config.prefix.lower()}.zip"
    zip_directory_with_progress(config.WHEEL_DIR, wheel_zip_path)
    
    # 打包 Environment
    log_info("正在打包 Conda 环境 (这可能需要几分钟)...")
    env_zip_path = config.EXPORT_DIR / f"full_env_{config.prefix.lower()}.zip"
    zip_directory_with_progress(config.ENV_DIR, env_zip_path)

    print(f"\n{Color.GREEN}====================================================={Color.END}")
    print(f"{Color.BOLD}   构建完成！全量产物已存放在：{config.EXPORT_DIR}{Color.END}")
    print(f"{Color.BOLD}   请将整个 {config.EXPORT_DIR.name} 目录拷贝至 B 机进行部署。{Color.END}")
    print(f"{Color.GREEN}====================================================={Color.END}\n")
    input("按任意键退出...")

def main():
    print(f"{Color.BOLD}========================================{Color.END}")
    print(f"{Color.BOLD}   AI 离线环境构建工具 (A 机){Color.END}")
    print(f"{Color.BOLD}========================================{Color.END}\n")
    
    print(f"{Color.CYAN}第一步：请选择要构建的工作环境{Color.END}")
    print(f"  {Color.BOLD}[1]{Color.END} 构建大模型工作环境 (env_paper)")
    print(f"  {Color.BOLD}[2]{Color.END} 构建MinerU工作环境 (env_mineru)")
    
    env_choice = input(f"\n  请输入选项 (1/2) [默认 1]: ").strip()
    
    target_config = ENV_MINERU_CONFIG if env_choice == "2" else ENV_PAPER_CONFIG
    
    print(f"\n{Color.GREEN}已选择：{target_config.name}{Color.END}")
    print(f"环境目录：{target_config.ENV_DIR}")
    print(f"Wheels 目录：{target_config.WHEEL_DIR}")
    print(f"全量产出：{target_config.EXPORT_DIR}")
    print(f"补丁产出：{target_config.PATCH_DIR}")
    print("-" * 40)
    
    print(f"{Color.CYAN}第二步：请选择构建模式{Color.END}")
    print(f"  {Color.BOLD}[1]{Color.END} 全量构建环境 - 删除旧环境重新安装，下载所有依赖并打包为 ZIP (最稳定)")
    print(f"  {Color.BOLD}[2]{Color.END} 增量补丁包   - 根据 {target_config.PATCH_CONFIG_FILE.name} 生成 ZIP 补丁包 (最快)")
    
    mode_choice = input(f"\n  请输入选项 (1/2) [默认 1]: ").strip()
    
    if mode_choice == "2":
        build_patch_package(target_config)
    else:
        # 二次确认全量构建
        if target_config.ENV_DIR.exists():
            confirm = input(f"\n{Color.YELLOW}[警告]{Color.END} 即将删除现有环境 {target_config.ENV_DIR} 并重建。确认？(y/n): ").strip().lower()
            if confirm != 'y':
                log_info("操作已取消。")
                return
        build_full_package(target_config)

if __name__ == "__main__":
    main()
