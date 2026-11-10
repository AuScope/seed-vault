#!/bin/bash

# Activate virtual environment
if [ -d ".venv" ]; then
  echo "Activating virtual environment..."
  source .venv/bin/activate
else
  echo "Virtual environment not found. Please run setup_env.sh first."
  exit 1
fi

# Set the PYTHONPATH to include the root directory of your package
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Run the desktop app
echo "Starting SEED Vault..."
python -m seed_vault.qt
