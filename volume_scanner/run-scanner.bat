@echo off
REM Runs the volume scanner from anywhere. Forwards all arguments to the CLI.
REM Example:  run-scanner.bat --market us --top 25 --min-rvol 3
pushd "%~dp0.."
python -m volume_scanner.cli %*
popd
