# 🚀 NHN Cloud 인스턴스 자동 배포 및 백업 시스템

이 프로젝트는 NHN Cloud API를 활용하여 네트워크 인프라(VPC, 서브넷, 보안 그룹)를 자동으로 구축하고, 인스턴스 배포 시 사용자 맞춤형 sudo 백업 함수를 자동으로 설정하는 도구입니다.

## ✨ 주요 기능
- 인프라 자동화: 클릭 한 번으로 VPC, 인터넷 게이트웨이, 라우팅 테이블, 보안 그룹 설정 완료
- 스마트 리전 지원: 판교(KR1), 평촌(KR2) 등 NHN Cloud 리전 엔드포인트 완벽 지원
- 자동 백업 시스템: 인스턴스 접속 시 `sudo vi`, `sed` 등의 명령어를 사용할 때 자동으로 원본 파일을 `/var/tmp/sudo_backups`에 저장
- SSH 키 관리: 새 키 페어 자동 생성 및 `.pem` 파일 즉시 다운로드 지원

## 🛠 구성 파일
- `app.py`: Flask 기반 웹 서버 및 API 라우팅
- `nhn_api.py`: NHN Cloud 자원 조회 및 인프라 구축 로직 (User Data 포함)
- `config.py`: 리전별 API 엔드포인트 설정 정보
- `index.html`: 사용자 UI 및 배포 제어 화면

## 📋 사전 준비 사항
1. NHN Cloud 계정: API 전용 사용자 ID/PW
2. 테넌트 ID: Compute -> Instance ->API 엔드포인트 설정에서 확인가능
3. Python: 3.8 버전 이상 설치 권장