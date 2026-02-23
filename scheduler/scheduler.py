import os
import sys
import subprocess
import shutil
import time
from datetime import datetime
from pathlib import Path
import logging

class TaskQueueManager:
    def __init__(self, script_folder, result_folder):
        """
        初始化任务队列管理器
        
        Args:
            script_folder: 待调度的脚本文件夹路径
            result_folder: 运行结果文件夹路径
        """
        self.script_folder = Path(script_folder)
        self.result_folder = Path(result_folder)
        
        # 确保文件夹存在
        self.script_folder.mkdir(parents=True, exist_ok=True)
        self.result_folder.mkdir(parents=True, exist_ok=True)
        
        # 设置日志
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
    def get_next_script(self):
        """
        按照文件名字母序获取下一个脚本
        """
        # 获取所有脚本文件
        scripts = list(self.script_folder.glob("*"))
        
        # 过滤掉目录，只保留文件
        scripts = [s for s in scripts if s.is_file()]
        
        # 按文件名排序（字母序）
        scripts.sort(key=lambda x: x.name)
        
        if scripts:
            return scripts[0]
        return None
    
    def run_script(self, script_path):
        """
        运行脚本并记录结果
        
        Args:
            script_path: 脚本文件路径
            
        Returns:
            bool: 是否成功运行
        """
        try:
            script_file = Path(script_path)
            script_name = script_file.name
            
            # 生成时间戳
            timestamp = datetime.now().strftime("%Y%m%d%H%M")
            
            # 创建日志文件名
            log_filename = f"{timestamp}-{script_name}.log"
            log_path = self.result_folder / log_filename
            
            self.logger.info(f"开始运行脚本: {script_name}")
            
            # 记录开始时间
            start_time = datetime.now()
            
            # 打开日志文件准备写入（二进制模式）
            with open(log_path, 'wb') as log_file:
                # 写入开始时间戳
                log_file.write(f"=== 脚本开始运行 ===\n".encode('utf-8'))
                log_file.write(f"开始时间: {start_time}\n".encode('utf-8'))
                log_file.write(f"脚本名称: {script_name}\n".encode('utf-8'))
                log_file.write(("=" * 50 + "\n\n").encode('utf-8'))

                # 运行脚本并捕获输出
                try:
                    # 检查脚本是否有执行权限
                    if not os.access(script_path, os.X_OK):
                        # 如果没有执行权限，尝试添加执行权限
                        os.chmod(script_path, os.stat(script_path).st_mode | 0o111)

                    # 运行脚本，捕获标准输出和标准错误（二进制模式）
                    process = subprocess.Popen(
                        [script_path],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        bufsize=0
                    )

                    # 实时读取输出并写入日志文件（原样写入二进制数据）
                    while True:
                        chunk = process.stdout.read(4096)
                        if not chunk:
                            break
                        log_file.write(chunk)
                        log_file.flush()  # 确保实时写入

                    # 等待进程结束
                    return_code = process.wait()

                    # 记录结束时间
                    end_time = datetime.now()
                    duration = end_time - start_time

                    # 写入结束信息
                    log_file.write(("\n" + "=" * 50 + "\n").encode('utf-8'))
                    log_file.write(f"=== 脚本运行结束 ===\n".encode('utf-8'))
                    log_file.write(f"结束时间: {end_time}\n".encode('utf-8'))
                    log_file.write(f"运行时长: {duration}\n".encode('utf-8'))
                    log_file.write(f"退出代码: {return_code}\n".encode('utf-8'))

                    self.logger.info(f"脚本运行完成: {script_name}, 退出代码: {return_code}")

                    return return_code == 0

                except Exception as e:
                    end_time = datetime.now()
                    log_file.write(f"\n运行过程中发生错误: {str(e)}\n".encode('utf-8'))
                    log_file.write(f"错误时间: {end_time}\n".encode('utf-8'))
                    self.logger.error(f"运行脚本时出错: {script_name}, 错误: {e}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"处理脚本时出错: {script_path}, 错误: {e}")
            return False
    
    def move_script_to_result(self, script_path):
        """
        将脚本移动到结果文件夹并添加时间戳
        
        Args:
            script_path: 原始脚本路径
        """
        try:
            script_file = Path(script_path)
            script_name = script_file.name
            
            # 获取当前时间戳（与日志文件相同）
            timestamp = datetime.now().strftime("%Y%m%d%H%M")
            
            # 创建新的文件名
            new_filename = f"{timestamp}-{script_name}"
            new_path = self.result_folder / new_filename
            
            # 移动文件
            shutil.move(str(script_path), str(new_path))
            
            self.logger.info(f"已移动脚本到结果文件夹: {new_filename}")
            
        except Exception as e:
            self.logger.error(f"移动脚本时出错: {script_path}, 错误: {e}")
    
    def run_queue(self):
        """
        运行任务队列
        """
        self.logger.info("任务队列管理器启动")
        self.logger.info(f"脚本文件夹: {self.script_folder}")
        self.logger.info(f"结果文件夹: {self.result_folder}")
        
        try:
            while True:
                # 获取下一个脚本
                script = self.get_next_script()
                
                if script:
                    self.logger.info(f"找到脚本: {script.name}")
                    
                    # 运行脚本
                    success = self.run_script(str(script))
                    
                    # 移动脚本到结果文件夹
                    if success:
                        self.move_script_to_result(str(script))
                    else:
                        # 即使运行失败也移动脚本，以便清理
                        self.move_script_to_result(str(script))
                    
                    # 等待一下再检查下一个脚本
                    time.sleep(1)
                else:
                    self.logger.info("没有找到待运行的脚本，等待5秒后重试...")
                    time.sleep(5)
                    
        except KeyboardInterrupt:
            self.logger.info("收到中断信号，程序退出")
        except Exception as e:
            self.logger.error(f"队列运行过程中发生错误: {e}")
            raise

def main():
    """
    主函数
    """
    # 脚本所在目录的上级目录
    script_dir = Path(__file__).resolve().parent

    # 默认值：脚本所在文件夹旁边的 queue 和 result 文件夹
    default_queue = script_dir / "queue"
    default_result = script_dir / "result"

    script_folder = sys.argv[1] if len(sys.argv) > 1 else str(default_queue)
    result_folder = sys.argv[2] if len(sys.argv) > 2 else str(default_result)

    # 创建队列管理器并运行
    manager = TaskQueueManager(script_folder, result_folder)
    manager.run_queue()

if __name__ == "__main__":
    main()