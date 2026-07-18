"""
agent/__main__.py — entry point для `python -m agent`.

Делегирует в agent.graph.main().
"""
from agent.graph import main

if __name__ == "__main__":
    main()