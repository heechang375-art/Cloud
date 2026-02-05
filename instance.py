import requests
import json
import base64
import time

# 1. 설정 정보
TENANT_ID = "c3ef7c629cad4448bd1f84bd32b21dee"
USERNAME = "test06"
PASSWORD = "test0606"

# API 엔드포인트 (KR1 평촌 리전)
URL_AUTH = "https://api-identity-infrastructure.nhncloudservice.com"
URL_COMPUTE = "https://kr1-api-instance-infrastructure.nhncloudservice.com"
URL_NETWORK = "https://kr1-api-network-infrastructure.nhncloudservice.com/v2.0"

IMAGE_ID = "7342b6e2-74d6-4d2c-a65c-90242d1ee218" 
FLAVOR_ID = "a4b6a0f7-aeff-4d78-a8d5-7de9f007012d" 
KEY_NAME = "vm1-key"

# 2. 토큰 발급
def get_token():
    auth_data = {"auth": {"tenantId": TENANT_ID, "passwordCredentials": {"username": USERNAME, "password": PASSWORD}}}
    res = requests.post(f"{URL_AUTH}/v2.0/tokens", json=auth_data)
    res.raise_for_status()
    return res.json()["access"]["token"]["id"]

TOKEN = get_token()
HEADER = {"x-auth-token": TOKEN, "content-type": "application/json"}

# 3. 네트워크 인프라 구축
print("🌐 [1/4] 네트워크 인프라 구축 시작...")

# 3.1 VPC 생성
vpc = requests.post(f"{URL_NETWORK}/vpcs", headers=HEADER, json={"vpc": {"name": "secure-final-vpc", "cidrv4": "10.0.0.0/16"}}).json()["vpc"]
vpc_id = vpc["id"]

# 3.2 외부망 ID 조회
nets = requests.get(f"{URL_NETWORK}/networks", headers=HEADER).json()["networks"]
pub_net_id = next(n["id"] for n in nets if n.get("router:external"))

# 3.3 서브넷 생성
subnet = requests.post(f"{URL_NETWORK}/vpcsubnets", headers=HEADER, json={"vpcsubnet": {"name": "secure-final-sub", "vpc_id": vpc_id, "cidr": "10.0.0.0/24"}}).json()["vpcsubnet"]
subnet_id = subnet["id"]

# 3.4 인터넷 게이트웨이(IGW) 생성
igw = requests.post(f"{URL_NETWORK}/internetgateways", headers=HEADER, json={"internetgateway": {"name": "secure-final-igw", "vpc_id": vpc_id, "external_network_id": pub_net_id}}).json()["internetgateway"]
igw_id = igw["id"]

# 3.5 새로 만든 라우팅 테이블을 VPC의 '기본'으로 설정
print("🛤️ [3/4] 새 라우팅 테이블 생성 및 VPC 기본 테이블로 지정 중...")

# 1. 라우팅 테이블 생성 (이미 생성 로직이 있다면 rt_id 사용)
rt_res = requests.post(f"{URL_NETWORK}/routingtables", headers=HEADER, 
                        json={"routingtable": {"name": "secure-final-rt", "vpc_id": vpc_id}}).json()
rt_id = rt_res["routingtable"]["id"]

# 2. 인터넷 게이트웨이 연결 및 외부 경로 추가
requests.put(f"{URL_NETWORK}/routingtables/{rt_id}/attach_gateway", headers=HEADER, json={"gateway_id": igw_id})
requests.put(f"{URL_NETWORK}/routingtables/{rt_id}", headers=HEADER, 
             json={"routingtable": {"routes": [{"destination": "0.0.0.0/0", "target_id": igw_id, "target_type": "INTERNET_GATEWAY"}]}})

# 3. [핵심] 가이드에서 찾아내신 API: 이 테이블을 VPC의 '기본'으로 지정
# 이 명령을 내리면 vpc-3d814a... 대신 우리가 만든 테이블이 '기본'이 됩니다.
requests.put(f"{URL_NETWORK}/routingtables/{rt_id}/set_as_default", headers=HEADER)

# 4. 서브넷이 새로운 '기본' 설정을 즉시 반영하도록 업데이트
requests.put(f"{URL_NETWORK}/vpcsubnets/{subnet_id}", headers=HEADER, json={"vpcsubnet": {"routingtable_id": rt_id}})

print(f"✅ 'secure-final-rt'({rt_id})가 VPC의 새로운 기본 라우팅 테이블로 설정되었습니다.")
        
# 4. 보안 그룹 생성 (22, 80 포트)
print("🔒 [2/4] 보안 그룹 생성 및 규칙 설정 중...")
sg = requests.post(f"{URL_NETWORK}/security-groups", headers=HEADER, 
                   json={"security_group": {"name": "secure-web-sg"}}).json()["security_group"]
sg_id = sg["id"]

for port in [22, 80]:
    requests.post(f"{URL_NETWORK}/security-group-rules", headers=HEADER, 
                  json={"security_group_rule": {"security_group_id": sg_id, "direction": "ingress", 
                                                "protocol": "tcp", "port_range_min": port, "port_range_max": port, "remote_ip_prefix": "0.0.0.0/0"}})

# 5. 사용자 데이터(Cloud-Init 스크립트) - 요청하신 sudo 백업 로직 전체 포함
user_script = r"""#!/bin/bash
# Nginx 설치 및 설정
apt-get update -y && apt-get install nginx -y
systemctl start nginx && systemctl enable nginx
echo "<h1>NHN Cloud Web Server - Advanced Backup Script Deployed</h1>" > /var/www/html/index.html

# ubuntu 사용자의 .bashrc에 고도화된 sudo 백업 함수 삽입
cat << 'EOF' >> /home/ubuntu/.bashrc

# sudo로 편집기/sed/awk 실행 시 자동 백업 함수
sudo() {
    local cmd="$1"
    local args=("${@:2}")
    local target_file=""
    local backup_needed=false
    local editors=("vi" "vim" "nano" "gedit" "nvim")

    # 1. 편집기 대응
    if [[ " ${editors[@]} " =~ " ${cmd} " ]]; then
        target_file="${@: -1}"
        [ -f "$target_file" ] && backup_needed=true

    # 2. sed 대응 (-i 옵션 존재 시)
    elif [[ "$cmd" == "sed" ]]; then
        if [[ "$*" == *"-i"* ]]; then
            for arg in "${args[@]}"; do
                if [[ -f "$arg" ]]; then target_file="$arg"; backup_needed=true; break; fi
            done
        fi

    # 3. awk 대응
    elif [[ "$cmd" == "awk" ]]; then
        if [[ "$*" == *"-i"* && "$*" == *"inplace"* ]] || [[ "$*" == *">"* ]]; then
            for arg in "${args[@]}"; do
                if [[ "$arg" != -* && -f "$arg" ]]; then
                    target_file="$arg"
                    backup_needed=true
                    break
                fi
            done
        fi
    fi

    # 4. 백업 실행
    if [ "$backup_needed" = true ] && [ -n "$target_file" ]; then
        local backup_dir="/var/tmp/sudo_backups"
        local timestamp=$(date +%Y%m%d_%H%M%S)
        local filename=$(basename "$target_file")
        
        command sudo mkdir -p "$backup_dir"
        command sudo chmod 733 "$backup_dir"
        
        command sudo cp -p "$target_file" "$backup_dir/${filename}_${timestamp}.bak"
        echo "📂 [Backup] '$target_file' 이(가) 안전하게 백업되었습니다."
        echo "   ㄴ 경로: $backup_dir/${filename}_${timestamp}.bak"
    fi

    # 5. 원본 명령어 실행
    command sudo "$@"
}
EOF
chown ubuntu:ubuntu /home/ubuntu/.bashrc
"""
encoded_user_data = base64.b64encode(user_script.encode()).decode()

# 6. 인스턴스 생성 (50GB 볼륨)
print("💻 [3/4] 인스턴스 생성 요청 중 (50GB 볼륨)...")
server_payload = {
    "server": {
        "name": "final-backup-server",
        "imageRef": IMAGE_ID,
        "flavorRef": FLAVOR_ID,
        "key_name": KEY_NAME,
        "networks": [{"uuid": vpc_id, "subnet": subnet_id}],
        "security_groups": [{"name": "secure-web-sg"}],
        "user_data": encoded_user_data,
        "block_device_mapping_v2": [{
            "uuid": IMAGE_ID,
            "source_type": "image",
            "destination_type": "volume",
            "boot_index": 0,
            "volume_size": 50,
            "delete_on_termination": True
        }]
    }
}

srv_res = requests.post(f"{URL_COMPUTE}/v2/{TENANT_ID}/servers", headers=HEADER, json=server_payload).json()
server_id = srv_res["server"]["id"]

# 7. ACTIVE 대기 및 공인 IP 연결
print("⏳ 인스턴스 활성화 대기 중...")
while True:
    res = requests.get(f"{URL_COMPUTE}/v2/{TENANT_ID}/servers/{server_id}", headers=HEADER).json()
    status = res["server"]["status"]
    if status == "ACTIVE": break
    if status == "ERROR": exit("❌ 인스턴스 생성 오류 발생")
    time.sleep(5)

print("🔗 [4/4] 공인 IP 할당 및 인스턴스 포트 연결 중...")
fip = requests.post(f"{URL_NETWORK}/floatingips", headers=HEADER, 
                    json={"floatingip": {"floating_network_id": pub_net_id}}).json()["floatingip"]
fip_addr = fip["floating_ip_address"]

# 포트 ID 조회 후 Floating IP 바인딩
time.sleep(3)
ports = requests.get(f"{URL_NETWORK}/ports?device_id={server_id}", headers=HEADER).json()["ports"]
if ports:
    requests.put(f"{URL_NETWORK}/floatingips/{fip['id']}", headers=HEADER, json={"floatingip": {"port_id": ports[0]["id"]}})
    print("-" * 50)
    print(f"🚀 배포가 성공적으로 완료되었습니다!")
    print(f"🌐 접속 URL: http://{fip_addr}")
    print(f"🔐 SSH 접속: ssh ubuntu@{fip_addr}")
    print("-" * 50)