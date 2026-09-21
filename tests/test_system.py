from executor.runner import run_command
from evidence.verifier import verify


result = run_command("python workspace/fibonacci.py")

evidence = verify(result, expected_output=832040)

print("========== AEGISFLOW ==========")
print("Command:", result["command"])
print("Output:", result["stdout"])
print("Error:",result["stderr"])
print("Exit Code:", result["exit_code"])
print("Verified:", evidence["verified"])
print("Reason:", evidence["reason"])