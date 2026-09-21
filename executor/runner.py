import subprocess
import time


def run_command(command):
    start_time = time.time()

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True
        )

        duration = time.time() - start_time

        return {
            "command": command,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
            "duration": duration
        }

    except Exception as e:
        return {
            "command": command,
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1,
            "duration": time.time() - start_time
        }