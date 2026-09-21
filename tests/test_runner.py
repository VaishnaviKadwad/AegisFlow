from executor.runner import run_command


result = run_command("python --version")

print("COMMAND:", result["command"])
print("OUTPUT:", result["stdout"])
print("ERROR:", result["stderr"])
print("EXIT CODE:", result["exit_code"])
print("TIME:", result["duration"])