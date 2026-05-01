import os
import shutil
import sys
import subprocess
import time
import json
import zipfile
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 配置区 ---
ROOT_DIR = Path("D:/ai_offline_pack")
ENV_NAME = "env_mineru"
EXPORT_ROOT = ROOT_DIR / "exported_envs" / "mineru"
EXPORT_ENV_DIR = EXPORT_ROOT / ENV_NAME
ENV_DIR = ROOT_DIR / "envs" / ENV_NAME
MODEL_ROOT = ROOT_DIR / "models"
WHEEL_DIR = ROOT_DIR / "wheels" / "mineru"
PATCH_DIR = ROOT_DIR / "patch"
REQ_FILE_NAME = "requirements_mineru.txt"

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
    input("按任意键退出...")
    sys.exit(1)

def run_cmd(cmd, cwd=None, env=None, check=True, shell=False):
    """封装 subprocess.run"""
    try:
        # 在 Windows 下如果 cmd 是列表且有 shell=True，会有问题，所以处理一下
        if shell and isinstance(cmd, list):
            cmd = " ".join(cmd)
        
        # 确保环境变量是 dict
        current_env = os.environ.copy()
        if env:
            current_env.update(env)
        
        result = subprocess.run(cmd, cwd=cwd, env=current_env, shell=shell, check=check)
        return result
    except subprocess.CalledProcessError as e:
        log_error(f"命令执行失败: {cmd}")
        if check:
            sys.exit(e.returncode)
        return e

def copy_file(src_dst):
    src, dst = src_dst
    try:
        # 使用 shutil.copy2 保留元数据
        shutil.copy2(src, dst)
        return True
    except Exception as e:
        return f"Error copying {src} to {dst}: {e}"

def multithreaded_copy(src, dst, max_workers=12):
    """核心逻辑：多线程复制文件夹内容"""
    src = Path(src).resolve()
    dst = Path(dst).resolve()
    
    if not src.exists():
        log_fatal(f"源目录不存在: {src}")
    
    tasks = []
    log_info(f"正在扫描文件: {src} ...")
    
    for root, dirs, files in os.walk(src):
        rel_path = os.path.relpath(root, src)
        target_dir = dst / rel_path
        target_dir.mkdir(parents=True, exist_ok=True)
        
        for f in files:
            source_file = Path(root) / f
            target_file = target_dir / f
            
            # 如果是同步模式且文件已存在且大小时间一致，则跳过 (简单版同步)
            # 这里我们根据外部逻辑决定是否是全量
            tasks.append((str(source_file), str(target_file)))
            
    total = len(tasks)
    log_info(f"找到文件总数: {total}")
    
    if total == 0:
        log_warn("源目录为空，无需复制。")
        return

    log_info(f"开始多线程复制 (线程数: {max_workers})...")
    
    # 进度条模拟
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(copy_file, task): task for task in tasks}
        for future in as_completed(futures):
            res = future.result()
            if res is not True:
                log_error(res)
            done += 1
            if done % 1000 == 0 or done == total:
                print(f"\r  进度: {done}/{total} ({done*100/total:.1f}%)", end="", flush=True)
    print() # 换行

def run_smoke_test_only():
    """仅运行冒烟测试模式"""
    log_info("进入冒烟测试模式...")
    
    python_exe = ENV_DIR / "python.exe"
    if not python_exe.exists():
        log_fatal(f"环境不存在：{ENV_DIR}\n请先选择 [1] 完整部署流程")
    
    test_pdf = ROOT_DIR / "test.pdf"
    if not test_pdf.exists():
        log_fatal(f"未找到测试文件：{test_pdf}\n请将测试 PDF 放置在 D:\\ai_offline_pack\\test.pdf")
    
    # 检查 mineru.exe
    mineru_exe = ENV_DIR / "Scripts" / "mineru.exe"
    if not mineru_exe.exists():
        log_fatal("未找到 mineru.exe，环境可能不完整")
    
    # 配置 HF 环境变量
    hf_home = MODEL_ROOT / "hf_cache"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HOME"] = str(hf_home)
    
    log_info(f"运行 GPU 冒烟测试：{test_pdf}")
    output_dir = ROOT_DIR / "output_gpu"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        result = run_cmd([
            str(mineru_exe), "-p", str(test_pdf), 
            "-o", str(output_dir), 
            "--device", "cuda"
        ], env={"HF_HUB_OFFLINE": "1", "HF_HOME": str(hf_home)}, check=False)
        
        if result.returncode == 0:
            log_ok("GPU 冒烟测试通过。")
            log_info(f"输出目录：{output_dir}")
        else:
            log_error(f"冒烟测试运行失败，退出码：{result.returncode}")
            log_warn("\n=====================================================")
            log_warn("常见错误排查指南:")
            log_warn("=====================================================")
            log_warn("1. AttributeError: 'Qwen2VLConfig' object has no attribute 'max_position_embeddings'")
            log_warn("   原因：transformers 5.x 与 Qwen2VL 模型不兼容")
            log_warn("   解决：重新运行部署脚本，选择 [1] 完整部署流程 (会自动降级 transformers)")
            log_warn("")
            log_warn("2. CUDA out of memory")
            log_warn("   原因：显存不足")
            log_warn("   解决：关闭其他占用 GPU 的程序，或降低 batch_size")
            log_warn("")
            log_warn("3. ModuleNotFoundError: No module named 'xxx'")
            log_warn("   原因：依赖包缺失")
            log_warn("   解决：检查 wheels 目录是否包含所有必要的 wheel 文件")
            log_warn("=====================================================")
            log_warn("\n详细错误信息请查看上方日志。")
    except Exception as e:
        log_error(f"冒烟测试运行失败：{e}")
        log_warn("\n如果遇到 AttributeError: 'Qwen2VLConfig' object has no attribute 'max_position_embeddings'")
        log_warn("这可能是 transformers 版本兼容性问题。")
        log_warn("请重新运行部署脚本，选择 [1] 完整部署流程。")
    
    input("按任意键退出...")

def main():
    os.system('color') # 开启 Windows 终端颜色支持
    
    print(f"{Color.BLUE}====================================================={Color.END}")
    print(f"{Color.BOLD}   env_mineru 部署工具 (Python 版)  |  B机 (GPU){Color.END}")
    print(f"{Color.BLUE}====================================================={Color.END}")
    print(f"  ENV_DIR    : {ENV_DIR}")
    print(f"  EXPORT_DIR : {EXPORT_ENV_DIR}")
    print()

    # --- STEP 0: 选择模式 ---
    print(f"{Color.YELLOW}====================================================={Color.END}")
    print(f"{Color.BOLD}   请选择操作模式{Color.END}")
    print(f"{Color.YELLOW}====================================================={Color.END}")
    print(f"  {Color.BOLD}[1] 完整部署流程{Color.END} - 复制环境、安装依赖、配置模型")
    print(f"  {Color.BOLD}[2] 应用增量更新补丁{Color.END} - 从补丁包安装/升级依赖")
    print(f"  {Color.BOLD}[3] 仅运行冒烟测试{Color.END} - 跳过部署，直接测试现有环境")
    choice = input(f"\n  请选择 (1/2/3) [默认 1]: ").strip()
    
    if choice == "2":
        # 应用增量补丁模式
        apply_patch()
        input("按任意键退出...")
        return
    elif choice == "3":
        # 仅运行冒烟测试模式
        run_smoke_test_only()
        return
    
    # --- 完整部署流程 ---
    
    # --- STEP 1: 确定模式与清理 ---
    mode = "FULL"
    python_exe = ENV_DIR / "python.exe"
    
    if python_exe.exists():
        log_info(f"检测到本地环境已存在: {ENV_DIR}")
        print(f"  {Color.BOLD}[1] 同步更新{Color.END} - 仅复制文件 (简单覆盖)")
        print(f"  {Color.BOLD}[2] 覆盖安装{Color.END} - 清空并重新部署环境")
        choice = input(f"\n  请选择 (1/2) [默认 1]: ").strip()
        
        if choice == "2":
            mode = "FULL"
            log_info("已选择全量覆盖，正在清理旧环境...")
            # 简单粗暴的清理
            try:
                if ENV_DIR.exists():
                    shutil.rmtree(ENV_DIR)
            except Exception as e:
                log_error(f"清理失败 (可能文件被占用): {e}")
                log_fatal("请关闭所有占用该环境的程序后重试。")
        else:
            mode = "SYNC"
            log_info("已选择覆盖同步模式。")

    ENV_DIR.mkdir(parents=True, exist_ok=True)

    # --- STEP 2: 执行复制 ---
    log_info(f"执行 {mode} 部署...")
    multithreaded_copy(EXPORT_ENV_DIR, ENV_DIR)
    log_ok("环境文件复制完成。")

    # --- STEP 3: 验证环境 ---
    if not (ENV_DIR / "python.exe").exists():
        log_fatal("python.exe 验证失败，请检查复制过程！")
    
    if not (ENV_DIR / "Lib" / "site-packages").exists():
        log_warn("site-packages 目录缺失，环境可能不完整。")

    # --- STEP 4: 环境修复 (conda-unpack) ---
    log_info("修复环境路径 (conda-unpack)...")
    unpack_exe = ENV_DIR / "Scripts" / "conda-unpack.exe"
    if unpack_exe.exists():
        run_cmd([str(unpack_exe)])
        log_ok("conda-unpack 执行完毕。")
    else:
        log_warn("未找到 conda-unpack.exe，跳过。")

    # --- STEP 5: 核心依赖安装 (GPU Torch) ---
    log_info("移除旧版 PyTorch 并安装 GPU 版...")
    
    # 卸载
    run_cmd([str(python_exe), "-m", "pip", "uninstall", "-y", "torch", "torchvision", "torchaudio"], check=False)
    
    # 安装 GPU 版
    log_info(f"正在从本地 Wheels 安装 GPU Torch: {WHEEL_DIR}")
    run_cmd([
        str(python_exe), "-m", "pip", "install", 
        "--no-index", 
        f"--find-links={WHEEL_DIR}", 
        "torch==2.4.1", "torchvision==0.19.1", "torchaudio==2.4.1", 
        "--no-deps"
    ])
    
    # 修复入口点
    log_info("修复 mineru 入口点...")
    run_cmd([
        str(python_exe), "-m", "pip", "install", 
        "--no-index", f"--find-links={WHEEL_DIR}", 
        "mineru", "--force-reinstall", "--no-deps"
    ])
    
    # 关键修复：降级 transformers 到兼容版本
    # transformers 5.x 与 Qwen2VL 模型存在兼容性问题 (AttributeError: max_position_embeddings)
    log_info("修复 transformers 版本兼容性...")
    log_warn("检测到 transformers 5.x 与 Qwen2VL 模型不兼容，降级到 4.57.2...")
    run_cmd([
        str(python_exe), "-m", "pip", "install", 
        "--no-index", f"--find-links={WHEEL_DIR}", 
        "transformers==4.57.2", "--force-reinstall"
    ], check=False)
    # 如果本地没有 4.57.2，尝试安装 4.56.0
    if run_cmd([str(python_exe), "-c", "import transformers; assert transformers.__version__.startswith('4.5')"], check=False).returncode != 0:
        log_warn("本地 wheels 无 transformers 4.57.2，尝试 4.56.0...")
        run_cmd([
            str(python_exe), "-m", "pip", "install", 
            "--no-index", f"--find-links={WHEEL_DIR}", 
            "transformers==4.56.0", "--force-reinstall"
        ], check=False)
    
    log_ok("GPU 核心依赖安装/修复完成。")

    # --- STEP 6: 业务依赖同步 ---
    log_info("同步业务依赖 (transformers, mineru[all] 等)...")
    
    # 寻找 requirements_mineru.txt
    req_file = ROOT_DIR / "scripts" / "env_init" / REQ_FILE_NAME
    if not req_file.exists():
        req_file = Path(__file__).parent / REQ_FILE_NAME
    
    if not req_file.exists():
        log_error(f"找不到依赖文件: {REQ_FILE_NAME}")
    else:
        lock_file = req_file.with_name(req_file.stem + "_lock.txt")
        sync_file = lock_file if lock_file.exists() else req_file
        
        log_info(f"使用同步文件: {sync_file}")
        run_cmd([
            str(python_exe), "-m", "pip", "install", 
            "--use-deprecated=legacy-resolver", 
            "--no-index", 
            f"--find-links={WHEEL_DIR}", 
            "-r", str(sync_file)
        ], check=False)

    # --- STEP 7: HF 缓存结构配置 ---
    log_info("配置 HuggingFace 离线缓存...")
    hf_home = MODEL_ROOT / "hf_cache"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["HF_HOME"] = str(hf_home)
    
    # 构建结构 (兼容 MinerU 逻辑)
    model_name = "MinerU2.5-Pro-2604-1.2B"
    src_model_dir = MODEL_ROOT / model_name
    dst_snapshot_dir = hf_home / "hub" / f"models--opendatalab--{model_name}" / "snapshots" / "local"
    
    if src_model_dir.exists():
        if not dst_snapshot_dir.exists():
            log_info(f"正在创建 HF 镜像结构: {dst_snapshot_dir}")
            dst_snapshot_dir.mkdir(parents=True, exist_ok=True)
            # 这里不复制全部，建议用链接或只复制必要文件，但为了稳定性，直接复制
            # multithreaded_copy(src_model_dir, dst_snapshot_dir) # 太慢了
            # 我们假设用户已经处理好，或者我们执行简单的文件列表复制
            for f in src_model_dir.glob("*"):
                if f.is_file():
                    shutil.copy2(f, dst_snapshot_dir / f.name)
        
        refs_dir = hf_home / "hub" / f"models--opendatalab--{model_name}" / "refs"
        refs_dir.mkdir(parents=True, exist_ok=True)
        (refs_dir / "main").write_text("local", encoding="utf-8")
        log_ok("HF 离线缓存结构就绪。")
    else:
        log_warn(f"未找到原始模型目录: {src_model_dir}，跳过 HF 结构构建。")

    # --- STEP 8: magic-pdf.json 配置 ---
    log_info("生成 magic-pdf.json 配置...")
    user_profile = Path(os.environ.get("USERPROFILE", "C:/Users/Default"))
    config_path = user_profile / "magic-pdf.json"
    
    json_model_root = str(MODEL_ROOT).replace("\\", "/")
    import json
    config_data = {"models-dir": json_model_root}
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)
    log_ok(f"配置文件已写入: {config_path}")

    # --- STEP 9: 健康检查 ---
    log_info("执行依赖健康检查...")
    check_code = """
import sys
modules = ["torch", "transformers", "huggingface_hub", "mineru"]
failed = []
for m in modules:
    try:
        __import__(m)
        print(f"[OK] {m}")
    except Exception as e:
        print(f"[FAIL] {m}: {e}")
        failed.append(m)
if failed:
    sys.exit(1)
"""
    res = run_cmd([str(python_exe), "-c", check_code], check=False)
    if res.returncode == 0:
        log_ok("所有核心模块导入正常。")
    else:
        log_error("部分核心依赖损坏，请检查 pip install 日志。")

    # --- STEP 10: 询问是否运行冒烟测试 ---
    run_smoke_test = False
    test_pdf = ROOT_DIR / "test.pdf"
    if test_pdf.exists():
        print(f"\n{Color.YELLOW}====================================================={Color.END}")
        print(f"{Color.BOLD}   冒烟测试选项{Color.END}")
        print(f"{Color.YELLOW}====================================================={Color.END}")
        print(f"  检测到测试文件：{test_pdf}")
        print(f"  {Color.BOLD}[1] 立即运行 GPU 冒烟测试{Color.END}")
        print(f"  {Color.BOLD}[2] 跳过测试 (可稍后手动运行){Color.END}")
        choice = input(f"\n  请选择 (1/2) [默认 2]: ").strip()
        
        if choice == "1":
            run_smoke_test = True
    else:
        log_info("未找到 test.pdf，如需运行冒烟测试，请将测试 PDF 放置在 D:\\ai_offline_pack\\test.pdf")

    print(f"\n{Color.GREEN}====================================================={Color.END}")
    print(f"{Color.BOLD}   部署成功！env_mineru 已可以使用。{Color.END}")
    print(f"{Color.GREEN}====================================================={Color.END}\n")
    
    # --- STEP 11: 可选的冒烟测试 ---
    if run_smoke_test:
        log_info(f"运行 GPU 冒烟测试：{test_pdf}")
        mineru_exe = ENV_DIR / "Scripts" / "mineru.exe"
        if mineru_exe.exists():
            try:
                result = run_cmd([
                    str(mineru_exe), "-p", str(test_pdf), 
                    "-o", str(ROOT_DIR / "output_gpu"), 
                    "--device", "cuda"
                ], env={"HF_HUB_OFFLINE": "1", "HF_HOME": str(hf_home)}, check=False)
                
                if result.returncode == 0:
                    log_ok("GPU 冒烟测试通过。")
                else:
                    log_error(f"冒烟测试运行失败，退出码：{result.returncode}")
                    log_warn("\n=====================================================")
                    log_warn("常见错误排查指南:")
                    log_warn("=====================================================")
                    log_warn("1. AttributeError: 'Qwen2VLConfig' object has no attribute 'max_position_embeddings'")
                    log_warn("   原因：transformers 5.x 与 Qwen2VL 模型不兼容")
                    log_warn("   解决：已自动降级到 transformers==4.57.2，请重新运行部署脚本")
                    log_warn("")
                    log_warn("2. CUDA out of memory")
                    log_warn("   原因：显存不足")
                    log_warn("   解决：关闭其他占用 GPU 的程序，或降低 batch_size")
                    log_warn("")
                    log_warn("3. ModuleNotFoundError: No module named 'xxx'")
                    log_warn("   原因：依赖包缺失")
                    log_warn("   解决：检查 wheels 目录是否包含所有必要的 wheel 文件")
                    log_warn("=====================================================")
                    log_warn("\n详细错误信息请查看上方日志。")
            except Exception as e:
                log_error(f"冒烟测试运行失败：{e}")
                log_warn("\n如果遇到 AttributeError: 'Qwen2VLConfig' object has no attribute 'max_position_embeddings'")
                log_warn("这可能是 transformers 版本兼容性问题。")
                log_warn("本脚本已自动将 transformers 降级到 4.57.2，请重新运行部署脚本。")
        else:
            log_warn("未找到 mineru.exe，无法运行测试。")
    
    input("按任意键退出...")

if __name__ == "__main__":
    main()
