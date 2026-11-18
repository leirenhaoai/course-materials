@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

rem ---------- 找一个能用的 Python ----------
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
  where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  echo.
  echo   没有找到 Python。
  echo   请到 https://www.python.org/downloads/ 装一个 3.10 或更高版本，
  echo   安装时记得勾选 "Add Python to PATH"，装完再双击本文件。
  echo.
  pause
  exit /b 1
)

"%PY%" -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
if errorlevel 1 (
  echo.
  echo   Python 版本太低，需要 3.10 或更高。当前版本：
  "%PY%" --version
  echo.
  pause
  exit /b 1
)

rem ---------- 首次运行：建库 + 灌演示数据 ----------
if not exist "data\adc.db" (
  echo [1/4] 初始化数据库...
  "%PY%" -X utf8 app\server.py --init-only || goto :fail
  echo [2/4] 灌入门诊主链路（门店、牙医、患者、预约、就诊、结算）...
  "%PY%" -X utf8 tools\seed.py || goto :fail
  echo [3/4] 灌入耗材、采购、对账、质量、核算、排班流转...
  "%PY%" -X utf8 tools\seed2.py || goto :fail
  echo [4/4] 补齐待审批与投诉样例...
  "%PY%" -X utf8 tools\seed3.py || goto :fail
  echo.
  echo 数据准备好了。
)

echo.
echo ============================================================
echo   ADC 诊疗管理系统已启动
echo   浏览器打开： http://127.0.0.1:8000
echo   账号口令都是 123456： zhangsan / recept1 / dentist1
echo                         manager1 / ops1 / finance1
echo   关闭本窗口即停止服务
echo ============================================================
echo.
start "" http://127.0.0.1:8000
"%PY%" -X utf8 app\server.py
goto :eof

:fail
echo.
echo   初始化失败，上面有具体报错。
echo   如果想从头再来，删掉 data\adc.db 再双击本文件。
echo.
pause
exit /b 1
