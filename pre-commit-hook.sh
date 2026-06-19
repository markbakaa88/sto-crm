#!/bin/sh
# Cross-platform pre-commit hook to check trailing whitespace.
# Works in Unix and Windows environments.

# In Git worktrees or different OS shells, determine the correct python interpreter
if command -v python3 >/dev/null 2>&1; then
  PYTHON_EXE="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_EXE="python"
elif command -v py >/dev/null 2>&1; then
  PYTHON_EXE="py"
else
  echo "Error: Python interpreter not found. Cannot run whitespace validation hooks." >&2
  exit 1
fi

# Run the validation script on staged files only
$PYTHON_EXE check_whitespace.py --staged
exit_code=$?

if [ $exit_code -ne 0 ]; then
  echo "Aborting commit due to trailing whitespace validation failure." >&2
  exit 1
fi

exit 0
