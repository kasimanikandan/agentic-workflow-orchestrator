"""
Workflow 1 — Hello World
========================
Two sequential tasks: greet then shout (uppercase).
Introduces: basic skill registration, sequential deps, template resolution.

    cd sdk-python && python3 examples/01_hello_world.py
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orchestrator import Orchestrator, Registry, Workflow

# ------------------------------------------------------------------
# 1.  Define the workflow as a dict (or load from JSON/YAML file)
# ------------------------------------------------------------------
SPEC = {
    "workflow": {
        "name": "hello-world",
        "inputs": {
            "name": {"type": "string", "required": True}
        },
        "tasks": [
            {
                "id": "greet",
                "skill": "text.greet",
                "inputs": {"name": "${input.name}"}
            },
            {
                "id": "shout",
                "skill": "text.shout",
                "depends_on": ["greet"],          # runs AFTER greet
                "inputs": {"text": "${greet.output}"}
            }
        ],
        "output": "${shout.output}"
    }
}

# ------------------------------------------------------------------
# 2.  Register skill handlers
# ------------------------------------------------------------------
reg = Registry()

@reg.skill("text.greet")
def greet(ctx, inputs):
    message = f"Hello, {inputs['name']}!"
    ctx.record_decision("composed greeting", rationale="standard format")
    return message

@reg.skill("text.shout")
def shout(ctx, inputs):
    return inputs["text"].upper()

# ------------------------------------------------------------------
# 3.  Run the workflow
# ------------------------------------------------------------------
if __name__ == "__main__":
    wf     = Workflow.from_dict(SPEC)
    report = Orchestrator(reg).run_sync(wf, inputs={"name": "World"})

    print("=== Report ===")
    for task in report.tasks:
        print(f"  {task.id:10s}  status={task.status}  duration={task.duration_ms}ms")
        for d in task.decisions:
            print(f"             decision: {d.summary!r}  ({d.rationale})")

    print(f"\nOutput : {report.output}")
    print(f"Status : {report.status}  ({report.duration_ms}ms total)")
