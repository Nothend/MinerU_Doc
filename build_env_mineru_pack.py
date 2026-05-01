import os
import sys
import json
import shutil
import subprocess
import zipfile
import hashlib
from pathlib import Path
from datetime import datetime

# --- 配置区 ---
ROOT_DIR = Path("D:/ai_offline_pack")
WHEEL_DIR = ROOT_DIR / "wheels" / "mineru"
PATCH_DIR = ROOT_DIR / "patch"
REQ_FILE = Path(__file__).parent / "requirements_mineru.txt"
REQ_LOCK_FILE = Path(__file__).parent / "requirements_mineru_lock.txt"
PATCH_CONFIG_FILE = Path(__file__).parent / "patch_config.json"

# --- 颜色与格式 ---
class Color:
    PURPLE = '\033[95m'
    CYAN = '\033[96m'
    DARKCYAN = '\033[36m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

def log_info(msg): print(f"{Color.CYAN}[INFO]{Color.END} {msg}")
def log_ok(msg): print(f"{Color.GREEN}[OK]{Color.END} {msg}")
def log_warn(msg): print(f"{Color.YELLOW}[WARN]{Color.END} {msg}")
def log_error(msg): print(f"{Color.RED}[ERROR]{Color.END} {msg}")
def log_fatal(msg): 
    print(f"{Color.BOLD}{Color.RED}[FATAL]{Color.END} {msg}")
    sys.exit(1)

def run_cmd(cmd, cwd=None, check=True, shell=False, capture=False):
    """封装 subprocess.run"""
    try:
        if shell and isinstance(cmd, list):
            cmd = " ".join(cmd)
        
        if capture:
            result = subprocess.run(cmd, cwd=cwd, shell=shell, check=check, capture_output=True, text=True)
            return result
        else:
            result = subprocess.run(cmd, cwd=cwd, shell=shell, check=check)
            return result
    except subprocess.CalledProcessError as e:
        log_error(f"命令执行失败：{cmd}")
        if check:
            raise
        return e

def calculate_file_hash(filepath):
    """计算文件的 SHA256 哈希值"""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def download_package(package_spec, wheel_dir):
    """下载指定包及其依赖到 wheels 目录"""
    log_info(f"正在下载：{package_spec}")
    
    wheel_dir.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        sys.executable, "-m", "pip", "download",
        package_spec,
        "-d", str(wheel_dir),
        "--no-deps"
    ]
    
    result = run_cmd(cmd, check=False, capture=True)
    if result.returncode != 0:
        log_error(f"下载失败：{result.stderr}")
        return False
    
    log_ok(f"下载完成：{package_spec}")
    return True

def download_with_deps(package_spec, wheel_dir):
    """下载指定包及其所有依赖"""
    log_info(f"正在下载包及依赖：{package_spec}")
    
    wheel_dir.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        sys.executable, "-m", "pip", "download",
        package_spec,
        "-d", str(wheel_dir)
    ]
    
    result = run_cmd(cmd, check=False, capture=True)
    if result.returncode != 0:
        log_error(f"下载失败：{result.stderr}")
        return False
    
    log_ok(f"下载完成：{package_spec} 及其依赖")
    return True

def uninstall_package_from_env(python_exe, package_name):
    """从环境中卸载包"""
    log_info(f"正在卸载：{package_name}")
    cmd = [str(python_exe), "-m", "pip", "uninstall", "-y", package_name]
    result = run_cmd(cmd, check=False, capture=True)
    return result.returncode == 0

def install_package_from_wheels(python_exe, package_spec, wheel_dir):
    """从本地 wheels 安装包"""
    log_info(f"正在安装：{package_spec}")
    cmd = [
        str(python_exe), "-m", "pip", "install",
        "--no-index",
        f"--find-links={wheel_dir}",
        package_spec,
        "--force-reinstall"
    ]
    result = run_cmd(cmd, check=False, capture=True)
    if result.returncode != 0:
        log_error(f"安装失败：{result.stderr}")
        return False
    log_ok(f"安装完成：{package_spec}")
    return True

def check_patch_config():
    """检查补丁配置文件是否存在"""
    if not PATCH_CONFIG_FILE.exists():
        log_warn(f"未找到配置文件：{PATCH_CONFIG_FILE}")
        log_info("正在创建默认配置文件...")
        
        default_config = {
            "version": "1.0.0",
            "description": "MinERU 环境增量更新补丁",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "packages": {
                "install": [
                    # 示例：{"spec": "transformers==4.57.2", "with_deps": true}
                ],
                "uninstall": [
                    # 示例："old_package_name"
                ],
                "upgrade": [
                    # 示例：{"spec": "some_package==2.0.0", "with_deps": false}
                ]
            },
            "smoke_test": {
                "enabled": True,
                "test_code": """
import transformers
from transformers import AutoConfig
try:
    config = AutoConfig.from_pretrained('Qwen/Qwen2-VL-2B-Instruct', trust_remote_code=True)
    _ = getattr(config, 'max_position_embeddings', None)
    print('COMPATIBLE')
except AttributeError as e:
    if 'max_position_embeddings' in str(e):
        print('INCOMPATIBLE')
        exit(1)
    else:
        raise
"""
            }
        }
        
        with open(PATCH_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)
        
        log_ok(f"已创建默认配置文件：{PATCH_CONFIG_FILE}")
        log_info("请编辑该文件，添加需要安装/卸载/升级的包，然后重新运行此脚本。")
        return None
    
    with open(PATCH_CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    return config

def build_patch_pack():
    """构建增量补丁包"""
    log_info("=" * 60)
    log_info("开始构建增量补丁包")
    log_info("=" * 60)
    
    # 检查配置文件
    config = check_patch_config()
    if config is None:
        return
    
    # 验证配置
    packages = config.get("packages", {})
    install_list = packages.get("install", [])
    uninstall_list = packages.get("uninstall", [])
    upgrade_list = packages.get("upgrade", [])
    
    if not install_list and not uninstall_list and not upgrade_list:
        log_warn("配置文件中没有指定任何包操作，退出。")
        return
    
    # 创建临时工作目录
    work_dir = ROOT_DIR / "temp_patch_build"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    
    patch_wheels_dir = work_dir / "wheels"
    patch_wheels_dir.mkdir(parents=True)
    
    downloaded_packages = []
    
    try:
        # 下载需要安装的包
        for pkg in install_list:
            if isinstance(pkg, dict):
                spec = pkg.get("spec", "")
                with_deps = pkg.get("with_deps", False)
            else:
                spec = pkg
                with_deps = False
            
            if with_deps:
                success = download_with_deps(spec, patch_wheels_dir)
            else:
                success = download_package(spec, patch_wheels_dir)
            
            if success:
                downloaded_packages.append({"spec": spec, "with_deps": with_deps})
        
        # 下载需要升级的包
        for pkg in upgrade_list:
            if isinstance(pkg, dict):
                spec = pkg.get("spec", "")
                with_deps = pkg.get("with_deps", False)
            else:
                spec = pkg
                with_deps = False
            
            if with_deps:
                success = download_with_deps(spec, patch_wheels_dir)
            else:
                success = download_package(spec, patch_wheels_dir)
            
            if success:
                downloaded_packages.append({"spec": spec, "with_deps": with_deps, "is_upgrade": True})
        
        # 生成补丁清单
        patch_manifest = {
            "version": config.get("version", "1.0.0"),
            "description": config.get("description", ""),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "packages": {
                "install": downloaded_packages,
                "uninstall": uninstall_list,
                "upgrade": [p for p in downloaded_packages if p.get("is_upgrade", False)]
            },
            "smoke_test": config.get("smoke_test", {"enabled": False})
        }
        
        manifest_file = work_dir / "patch_manifest.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(patch_manifest, f, indent=2, ensure_ascii=False)
        
        log_ok("补丁清单已生成")
        
        # 复制 apply_patch.py 到工作目录
        deploy_script = Path(__file__).parent / "deploy_env_mineru.py"
        if deploy_script.exists():
            # 我们只需要提取 apply_patch 相关的函数，这里简化处理
            # 实际应用中应该单独维护 apply_patch.py
            log_info("注意：apply_patch 功能已集成在 deploy_env_mineru.py 中")
        
        # 统计文件
        wheel_files = list(patch_wheels_dir.glob("*.whl"))
        log_info(f"共收集 {len(wheel_files)} 个 wheel 文件")
        
        if not wheel_files and not uninstall_list:
            log_warn("没有下载任何 wheel 文件，也没有要卸载的包，跳过打包。")
            shutil.rmtree(work_dir)
            return
        
        # 创建补丁包
        PATCH_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        version = config.get("version", "1.0.0").replace(".", "_")
        patch_filename = f"MinERU_Patch_v{version}_{timestamp}.zip"
        patch_path = PATCH_DIR / patch_filename
        
        log_info(f"正在创建补丁包：{patch_path}")
        
        with zipfile.ZipFile(patch_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path in work_dir.rglob('*'):
                if file_path.is_file():
                    arcname = file_path.relative_to(work_dir)
                    zipf.write(file_path, arcname)
        
        # 计算补丁包哈希
        patch_hash = calculate_file_hash(patch_path)
        
        log_ok("=" * 60)
        log_ok("补丁包构建完成！")
        log_ok("=" * 60)
        log_info(f"补丁包路径：{patch_path}")
        log_info(f"补丁包大小：{patch_path.stat().st_size / 1024 / 1024:.2f} MB")
        log_info(f"SHA256 哈希：{patch_hash}")
        log_info("")
        log_info("下一步操作：")
        log_info(f"1. 将补丁包复制到离线机器 B 的 D:\\ai_offline_pack\\patch\\ 目录")
        log_info(f"2. 在 B 机运行 deploy_env_mineru.bat")
        log_info(f"3. 选择 [2] 应用增量更新补丁")
        
    finally:
        # 清理临时目录
        if work_dir.exists():
            shutil.rmtree(work_dir)
        log_info("临时文件已清理")

def build_full_pack():
    """构建完整环境包（原有逻辑）"""
    log_info("=" * 60)
    log_info("开始构建完整环境包")
    log_info("=" * 60)
    
    # 检查 Python 环境
    log_info(f"使用 Python: {sys.executable}")
    log_info(f"Python 版本：{sys.version}")
    
    # 创建 wheels 目录
    WHEEL_DIR.mkdir(parents=True, exist_ok=True)
    
    # 确定使用哪个 requirements 文件
    req_file = REQ_LOCK_FILE if REQ_LOCK_FILE.exists() else REQ_FILE
    
    if not req_file.exists():
        log_fatal(f"找不到 requirements 文件：{req_file}")
    
    log_info(f"使用依赖文件：{req_file}")
    
    # 下载所有依赖
    log_info("正在下载所有依赖包...")
    
    with open(req_file, "r", encoding="utf-8") as f:
        packages = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    
    log_info(f"共发现 {len(packages)} 个依赖包")
    
    failed_packages = []
    
    for i, pkg in enumerate(packages, 1):
        log_info(f"[{i}/{len(packages)}] 下载：{pkg}")
        try:
            # 下载包及其依赖
            cmd = [
                sys.executable, "-m", "pip", "download",
                pkg,
                "-d", str(WHEEL_DIR),
                "--no-deps"  # 先只下载指定的包，不下载依赖
            ]
            result = run_cmd(cmd, check=False, capture=True)
            if result.returncode != 0:
                log_error(f"下载失败：{pkg}")
                failed_packages.append(pkg)
        except Exception as e:
            log_error(f"下载异常：{pkg} - {e}")
            failed_packages.append(pkg)
    
    if failed_packages:
        log_warn(f"以下包下载失败：{failed_packages}")
        log_info("尝试第二次下载（带依赖解析）...")
        
        for pkg in failed_packages:
            log_info(f"重试下载：{pkg}")
            cmd = [
                sys.executable, "-m", "pip", "download",
                pkg,
                "-d", str(WHEEL_DIR)
            ]
            result = run_cmd(cmd, check=False, capture=True)
            if result.returncode != 0:
                log_error(f"最终下载失败：{pkg}")
    
    # 统计下载的 wheel 文件
    wheel_files = list(WHEEL_DIR.glob("*.whl"))
    log_info(f"共下载 {len(wheel_files)} 个 wheel 文件")
    
    total_size = sum(f.stat().st_size for f in wheel_files)
    log_info(f"总大小：{total_size / 1024 / 1024:.2f} MB")
    
    log_ok("=" * 60)
    log_ok("完整环境包构建完成！")
    log_ok("=" * 60)
    log_info(f"Wheels 目录：{WHEEL_DIR}")
    log_info("")
    log_info("下一步操作：")
    log_info(f"1. 将整个 D:\\ai_offline_pack\\wheels\\mineru 目录复制到离线机器 B")
    log_info(f"2. 同时复制导出的环境目录 (通过 conda-pack 或其他方式)")
    log_info(f"3. 在 B 机运行 deploy_env_mineru.bat 进行部署")

def main():
    os.system('color')
    
    print(f"{Color.BLUE}{'=' * 60}{Color.END}")
    print(f"{Color.BOLD}   MinERU 环境构建工具 (A 机 - 联网){Color.END}")
    print(f"{Color.BLUE}{'=' * 60}{Color.END}")
    print(f"  ROOT_DIR : {ROOT_DIR}")
    print(f"  WHEEL_DIR: {WHEEL_DIR}")
    print(f"  PATCH_DIR: {PATCH_DIR}")
    print()
    
    # 选择模式
    print(f"{Color.YELLOW}{'=' * 60}{Color.END}")
    print(f"{Color.BOLD}   请选择构建模式{Color.END}")
    print(f"{Color.YELLOW}{'=' * 60}{Color.END}")
    print(f"  {Color.BOLD}[1] 完整环境包{Color.END} - 下载所有依赖，用于首次部署")
    print(f"  {Color.BOLD}[2] 增量补丁包{Color.END} - 仅下载变更的包，用于后续更新")
    print()
    
    choice = input(f"  请选择 (1/2) [默认 1]: ").strip()
    
    if choice == "2":
        build_patch_pack()
    else:
        build_full_pack()
    
    print()
    input("按任意键退出...")

if __name__ == "__main__":
    main()
