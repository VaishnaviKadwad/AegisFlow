# core/orchestrator.py
from agent.planner import create_plan
from executor.runner import run_command
from evidence.verifier import verify

def run_mission(objective: str):
    print(f"\n[AegisFlow Mission Start]: {objective}")
    
    # Step 1: Generate dynamic execution plan using Member 1's Gemini Planner
    print("🤖 Requesting execution graph from Gemini Planner...")
    try:
        plan = create_plan(objective)
        print(f"✅ Plan Generated Successfully! Objective: {plan.objective}")
        for step in plan.steps:
            print(f"   - [{step.id}] Action: {step.action} | File: {step.file} | Command: {step.command}")
    except Exception as e:
        print(f"❌ Planner failed to generate a valid plan: {e}")
        return False

    # Step 2: Execute plan steps sequentially
    last_exec_result = None
    for step in plan.steps:
        if step.action == "create_file" or step.action == "modify_file":
            print(f"\n--- Writing File: {step.file} ---")
            os_path = step.file
            # Ensure workspace directory exists if needed
            os.makedirs(os.path.dirname(os_path), exist_ok=True) if "/" in os_path or "\\" in os_path else None
            with open(os_path, "w", encoding="utf-8") as f:
                f.write(step.content or "")
            print(f"Successfully wrote content to {os_path}")
            
        elif step.action == "run_command":
            print(f"\n--- Executing Command: {step.command} ---")
            last_exec_result = run_command(step.command)
            print(f"Exit Code: {last_exec_result['exit_code']}")
            print(f"Stdout:\n{last_exec_result['stdout'].strip()}")

    # Step 3: Verify execution using the Evidence Gate
    if last_exec_result:
        evidence = verify(last_exec_result, expected_output=832040)
        
        print("\n========== EVIDENCE GATE RESULT ==========")
        print(f"Verified: {evidence['verified']}")
        print(f"Reason: {evidence['reason']}")
        
        if evidence["verified"]:
            print("✅ Mission Verified Successfully!")
            return True
        else:
            print("❌ Evidence Gate Failed. Triggering Self-Healing Loop...")
            return False
            
    print("⚠️ No execution command was run.")
    return False

if __name__ == "__main__":
    run_mission("Create a Python Fibonacci function and verify that Fibonacci(30) = 832040.")