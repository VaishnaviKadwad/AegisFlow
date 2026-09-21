import os
from typing import List, Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from agent.prompts import PLANNER_PROMPT


load_dotenv()


class PlanStep(BaseModel):
    id: str = Field(
        description="Unique step identifier such as S1, S2"
    )

    action: Literal[
        "create_file",
        "modify_file",
        "run_command"
    ]

    file: Optional[str] = Field(
        default=None,
        description="File path for file operations"
    )

    content: Optional[str] = Field(
        default=None,
        description="Content to write when creating or modifying a file"
    )

    command: Optional[str] = Field(
        default=None,
        description="Command to execute"
    )


class ExecutionPlan(BaseModel):
    objective: str

    steps: List[PlanStep]


api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("GEMINI_API_KEY is not set")


client = genai.Client(api_key=api_key)


def create_plan(user_task: str) -> ExecutionPlan:

    prompt = f"""
{PLANNER_PROMPT}

USER TASK:
{user_task}
"""

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ExecutionPlan,
        ),
    )

    return ExecutionPlan.model_validate_json(response.text)


if __name__ == "__main__":

    task = """
    Create a Python Fibonacci function and verify that
    Fibonacci(30) = 832040.
    """

    plan = create_plan(task)

    print(plan.model_dump_json(indent=2))