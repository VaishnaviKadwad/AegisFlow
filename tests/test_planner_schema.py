from agent.planner import ExecutionPlan


def test_plan_schema():

    plan = ExecutionPlan(
        objective="Test Fibonacci",
        steps=[
            {
                "id": "S1",
                "action": "create_file",
                "file": "fibonacci.py",
                "content": "print('hello')",
            },
            {
                "id": "S2",
                "action": "run_command",
                "command": "python fibonacci.py",
                "expected_output": "832040",
            },
        ],
    )

    assert plan.objective == "Test Fibonacci"
    assert len(plan.steps) == 2
    assert plan.steps[0].action == "create_file"
    assert plan.steps[1].action == "run_command"
    assert plan.steps[1].expected_output == "832040"