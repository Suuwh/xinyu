"""
服务守护启动器
-以子进程方式运行app.py，控制台日志原样输出
-子进程因原生崩溃（如模型加载期0xC0000005）异常退出时，自动延时重启（最多5次）
-按 Ctrl+C/关闭窗口：正常结束，不重启
"""

import os
import sys
import time
import signal
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(BASE_DIR, "app.py")
PY = os.path.join(BASE_DIR, "python", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable

MAX_RESTARTS = 5
RESTART_WAIT = 3

_interrupted = False


def _handle_signal(signum, frame):
    global _interrupted
    _interrupted = True


signal.signal(signal.SIGINT, _handle_signal)
if hasattr(signal, "SIGBREAK"):
    signal.signal(signal.SIGBREAK, _handle_signal)


def main():
    attempt = 0
    while True:
        print("=" * 60, flush=True)
        print("  启动服务（第 %d 次）..." % (attempt + 1), flush=True)
        print("=" * 60, flush=True)
        child = subprocess.Popen([PY, APP], cwd=BASE_DIR)
        rc = child.wait()

        if _interrupted:
            print("\n已收到关闭信号，服务停止。", flush=True)
            return 0

        if rc == 0:
            print("\n服务已正常退出。", flush=True)
            return 0

        #异常退出（含原生崩溃）
        print("\n[守护] 服务异常退出，退出码 %s（%s）"
              % (rc, hex(rc) if isinstance(rc, int) else "未知"), flush=True)
        if attempt >= MAX_RESTARTS:
            print("[守护] 已连续重启 %d 次仍失败，停止重启。"
                  % MAX_RESTARTS, flush=True)
            print("[守护] 请检查模型文件是否完整。", flush=True)
            return rc

        attempt += 1
        print("[守护] %d 秒后自动重启（剩余重启次数 %d）..."
              % (RESTART_WAIT, MAX_RESTARTS - attempt + 1), flush=True)
        for _ in range(int(RESTART_WAIT * 2)):
            if _interrupted:
                print("\n已收到关闭信号，服务停止。", flush=True)
                return 0
            time.sleep(0.5)


if __name__ == "__main__":
    sys.exit(main())


