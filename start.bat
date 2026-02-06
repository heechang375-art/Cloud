@echo off
:: 한글 깨짐 방지를 위해 코드 페이지를 UTF-8(65001)로 변경
chcp 65001 >nul

echo [NHN Cloud Deployer] 시스템을 시작합니다...

:: 1. 가상환경이 없으면 생성
if not exist "venv" (
    echo 가상환경 생성 중...
    python -m venv venv
)

:: 2. 가상환경 활성화 및 패키지 설치
call venv\Scripts\activate
echo 필수 패키지 설치 중...
pip install flask requests

:: 3. 브라우저 자동 실행 및 서버 시작
echo 서버 실행 중... 브라우저를 확인하세요.
start http://127.0.0.1:5000
python app.py

pause