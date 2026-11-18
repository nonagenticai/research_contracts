"""Importable implementations behind the repository's contract gates.

Every gate lives here rather than in an extensionless ``scripts/`` file so that
ruff, ty, bandit and the ``types: [python]`` pre-commit hooks actually see it.
``scripts/*.py`` are thin argv-forwarding entry points.
"""
