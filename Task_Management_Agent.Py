"""
Launcher for the Project Management Agent team.

The agents live in the pm_agent/ package; see README.md for the architecture.
This file only starts it, so either of these works:

    python Task_Management_Agent.Py agents
    python -m pm_agent agents
"""
from pm_agent.cli import main

if __name__ == "__main__":
    main()
