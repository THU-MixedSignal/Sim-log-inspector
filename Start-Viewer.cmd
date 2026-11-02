@echo off
cd /d "%~dp0"
python -m simcheck --db .runtime/fixtures-v3.sqlite run examples/real-fixtures.json --port 0 --open
pause
