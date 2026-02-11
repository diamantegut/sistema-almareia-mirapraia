# Deployment Procedure - Sistema Almareia Mirapraia

This document outlines the standard procedure for deploying updates to the production environment using the `automated_updater.py` script.

## 1. Preparation

Before running the update:

1.  **Prepare Update Package**:
    *   Place all new/modified files in the `update_source` directory in the project root.
    *   Ensure a `version.txt` file exists in `update_source` with the new version number (e.g., `1.0.1`).
    *   Ensure `version.txt` in the project root reflects the *current* version.

2.  **Verify Integrity**:
    *   Run local tests to ensure the new code is stable.
    *   `python -m pytest tests/`

## 2. Execution

Run the automated updater script. This script will handle backup, version checking, applying updates, and restarting services.

```bash
python scripts/automated_updater.py
```

### What the script does:
1.  **Version Check**: Compares `version.txt` in root vs `update_source`.
2.  **Backup**: Creates a timestamped backup in `backups/` (includes `data/`, `system_config.json`, `Produtos/`, `app.py`).
3.  **Update**: Copies files from `update_source` to root, respecting protected paths (e.g., it won't overwrite `data/` or `system_config.json`).
4.  **Validation**: Checks integrity of all JSON files in `data/`.
5.  **Rollback**: If validation fails, it automatically restores the backup.
6.  **Restart**: Kills existing Python processes and starts:
    *   **Production Server**: Port 5000 (`FLASK_ENV=production`)
    *   **Development Server**: Port 5001 (`FLASK_ENV=development`)

## 3. Post-Update Verification

After the script completes:

1.  **Check Logs**:
    *   Review `scripts/updater.log` for any errors.
    *   Confirm "Update Process Completed Successfully".

2.  **Verify Services**:
    *   Access Production: [http://localhost:5000](http://localhost:5000)
    *   Access Development: [http://localhost:5001](http://localhost:5001)

3.  **Manual Checks**:
    *   Login to the system.
    *   Verify critical data (Reservations, Products) is present.
    *   Check the version number in the footer (if implemented).

## 4. Cross-Drive Deployment (F: to G:)

To deploy from Development (F:) to Production (G:) immediately:

1.  **Run Wrapper Script**:
    ```bash
    .\scripts\deploy_wrapper.bat
    ```

### What this does:
1.  **Stops Processes**: Kills all running Python processes to release file locks.
2.  **Backup**: Creates a timestamped backup in `G:\Almareia Mirapraia Sistema Producao\backups`.
3.  **Sync**: Copies files from F: to G:, excluding development artifacts (.git, .venv) and preserving G: configuration (data/, system_config.json).
4.  **Validate**: Checks JSON integrity in G:.
5.  **Restart**: Starts the Production Server on Port 5000 using G:'s virtual environment.
6.  **Verify**: Polls `http://localhost:5000` to ensure the service is up.

## Troubleshooting

*   **Update Failed**: Check `updater.log`. The system should have rolled back automatically.
*   **Services Not Starting**: Check if ports 5000/5001 are in use by other applications.
*   **JSON Errors**: The updater validates JSON integrity. if it fails, fix the JSON files in `update_source` and retry.
