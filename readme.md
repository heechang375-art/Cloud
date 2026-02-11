🚀 NHN Cloud Instance Auto-Deployer & Backup System
NHN Cloud API를 활용하여 인프라 생성부터 웹 서버 설정, 그리고 운영 안전성을 위한 자동 백업 시스템까지 한 번에 구축하는 자동화 도구입니다.

📌 프로젝트 개요
NHN Cloud의 REST API를 사용하여 복잡한 콘솔 조작 없이 VPC 네트워크 구축, 보안 설정, 인스턴스 생성, 공인 IP 할당을 원클릭으로 완료합니다. 특히 배포 시 인스턴스 내부에 파일 수정 자동 백업 로직을 주입하여 운영 실수를 방지합니다.

🛠 주요 기능
인프라 자동화: 클릭 한 번으로 VPC, 인터넷 게이트웨이, 라우팅 테이블, 보안 그룹 설정을 완료합니다.

스마트 리전 지원: 판교(KR1), 평촌(KR2), 일본(JP1), 미국(US1) 등 NHN Cloud의 주요 리전 엔드포인트를 완벽히 지원합니다.

자동 백업 시스템 (User Data):

인스턴스 생성 시 sudo_backup.sh 스크립트를 자동 주입합니다.

sudo vi, sed, awk 등 편집 명령 사용 시 원본 파일을 /var/tmp/sudo_backups에 타임스탬프와 함께 자동 저장합니다.

SSH 키 관리: 기존 키 재사용은 물론, 새 키 페어 자동 생성 및 .pem 파일 즉시 다운로드 기능을 제공합니다.

실시간 리소스 조회: 선택한 리전의 최신 이미지와 사양(Flavor) 정보를 실시간으로 반영하여 정렬합니다.

📂 프로젝트 구조
app.py: Flask 기반의 웹 백엔드 서버 및 API 라우팅 로직.

nhn_api.py: NHN Cloud REST API 통신 및 인프라/인스턴스 배포 핵심 엔진.

config.py: 리전별(KR1, KR2, JP1, US1) API 엔드포인트 설정 정보.

index.html: 사용자 친화적인 배포 제어 인터페이스 (UI).

⚙️ 배포 프로세스 (Workflow)
1. 인증 및 리소스 스캔
사용자의 자격 증명을 통해 x-auth-token을 발급받고, 리전별 가용 이미지 및 사양 리스트를 정렬하여 불러옵니다.

2. 네트워크 및 보안 레이어 구성
VPC & Gateway: 독립 가설 망(10.0.0.0/16) 구축 및 외부 통신용 인터넷 게이트웨이 연결.

Routing & Subnet: 라우팅 테이블 설정 및 인스턴스가 위치할 전용 서브넷(10.0.0.0/24) 생성.

Security Group: SSH(22), HTTP(80) 포트 개방 등 방화벽 규칙 자동 적용.

3. 인스턴스 생성 및 프로비저닝
인스턴스 생성과 동시에 Nginx 설치 및 Sudo Backup 함수가 포함된 User Data를 주입합니다.

서버 활성화 후 Floating IP를 생성하여 외부 접속 주소를 최종 할당합니다.

📋 사전 준비 사항
NHN Cloud 계정: API 접근 권한이 있는 사용자 ID 및 비밀번호.

테넌트 ID: NHN Cloud 콘솔(Compute > Instance > API 엔드포인트 설정)에서 확인 가능한 프로젝트 고유 ID.

Python 환경: Python 3.8 버전 이상 및 requests, flask 라이브러리 설치 필요.