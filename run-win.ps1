# Check if virtual environment exists
if (-not (Test-Path ".venv")) {
    Write-Output "Virtual environment not found. Please run setup_env.ps1 first."
    exit 1
}

# Activate virtual environment
Write-Output "Activating virtual environment..."
& .\.venv\Scripts\Activate

# Set the PYTHONPATH to include the root directory of your package
$env:PYTHONPATH = "${env:PYTHONPATH};$(Get-Location)"

# Run the desktop app
Write-Output "Starting SEED Vault..."
python -m seed_vault.qt
