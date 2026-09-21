def verify(result, expected_output=None):
    if result["exit_code"] != 0:
        return {
            "verified": False,
            "reason": "Execution failed.",
            "actual_output": result["stdout"].strip()
        }

    actual = result["stdout"].strip()

    if expected_output is not None:
        if actual != str(expected_output):
            return {
                "verified": False,
                "reason": f"Expected {expected_output}, but got {actual}.",
                "actual_output": actual
            }

    return {
        "verified": True,
        "reason": "Execution and output verification passed.",
        "actual_output": actual
    }