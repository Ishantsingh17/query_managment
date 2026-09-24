# Launch backend (port 8000) and frontend (port 5173) in separate windows.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; python -m uvicorn app.main:app --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; if (-not (Test-Path node_modules)) { npm install }; npm run dev"
Write-Host "Backend: http://127.0.0.1:8000/docs   Frontend: http://localhost:5173"
