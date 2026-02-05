import requests
import json
import base64
import time

# 1. 설정 정보
tenant_id = "c3ef7c629cad4448bd1f84bd32b21dee"
username = "test06"
password = "test0606"

url_auth = "https://api-identity-infrastructure.nhncloudservice.com"
url_compute = "https://kr1-api-instance-infrastructure.nhncloudservice.com"
url_network = "https://kr1-api-network-infrastructure.nhncloudservice.com/v2.0"

image_id = "7342b6e2-74d6-4d2c-a65c-90242d1ee218" 
flavor_id = "a4b6a0f7-aeff-4d78-a8d5-7de9f007012d" 
key_name = "vm1-key" 

# 2. 토큰 발급
auth_res = requests.post(f"{url_auth}/v2.0/tokens", 
                         json={"auth": {"tenantId": tenant_id, "passwordCredentials": {"username": username, "password": password}}})
auth_res.raise_for_status()
token = auth_res.json()["access"]["token"]["id"]
header = {"x-auth-token": token, "content-type": "application/json"}

# ---------------------------------------------------------------------------
# 3. VPC 및 외부망 ID 확보
# ---------------------------------------------------------------------------
print("🔍 네트워크 리소스 확인 중...")
vpcs_res = requests.get(f"{url_network}/vpcs", headers=header).json().get("vpcs", [])
# 이름이 일치하거나 Default인 VPC 선택
target_vpc = next((v for v in vpcs_res if v.get("name") == "secure-auto-vpc-final"), 
                  next((v for v in vpcs_res if v.get("default") is True), vpcs_res[0] if vpcs_res else None))

if not target_vpc:
    print("❌ 사용 가능한 VPC를 찾을 수 없습니다."); exit()
vpc_id = target_vpc["id"]
print(f"✅ 사용 VPC: {target_vpc.get('name')} ({vpc_id})")

nets = requests.get(f"{url_network}/networks", headers=header).json()["networks"]
pub_id = next(n["id"] for n in nets if n.get("router:external"))

# 서브넷 확인
sub_res = requests.get(f"{url_network}/vpcsubnets", headers=header).json().get("vpcsubnets", [])
target_subnet = next((s for s in sub_res if s.get("vpc_id") == vpc_id), None)
if not target_subnet:
    print("❌ 서브넷을 찾을 수 없습니다."); exit()
subnet_id = target_subnet["id"]

# ---------------------------------------------------------------------------
# 4. [핵심] 기본 라우팅 테이블 탐색 및 IGW 연결 (구조적 해결)
# ---------------------------------------------------------------------------
print("🌐 기본 라우팅 테이블에 인터넷 통로 연결 중...")

# 4.1 인터넷 게이트웨이(IGW) 확보
igw_payload = {"internetgateway": {"name": "auto-igw-final", "vpc_id": vpc_id, "external_network_id": pub_id}}
igw_res = requests.post(f"{url_network}/internetgateways", headers=header, json=igw_payload)
if igw_res.status_code == 201:
    igw_id = igw_res.json()["internetgateway"]["id"]
else:
    igw_list = requests.get(f"{url_network}/internetgateways", headers=header).json().get("internetgateways", [])
    igw_id = next(i["id"] for i in igw_list if i.get("vpc_id") == vpc_id)

# 4.2 API 응답 구조(image_bf20c5.png)에 맞춘 정밀 탐색
rt_list = requests.get(f"{url_network}/routingtables", headers=header).json().get("routingtables", [])
target_rt_id = None

for rt in rt_list:
    # 1. 'vpcs' 리스트 내부의 'id' 필드를 전수 조사
    vpcs_in_rt = rt.get("vpcs", [])
    is_match = False
    
    if isinstance(vpcs_in_rt, list):
        is_match = any(v.get("id") == vpc_id for v in vpcs_in_rt)
    elif isinstance(vpcs_in_rt, dict):
        is_match = vpcs_in_rt.get("id") == vpc_id
    
    # 2. VPC가 일치하고 '기본' 설정된 테이블 선택
    if is_match and rt.get("default") is True:
        target_rt_id = rt["id"]
        break

if target_rt_id:
    print(f"✅ 기본 라우팅 테이블 발견: {target_rt_id}")
    # IGW 연결 및 외부망(0.0.0.0/0) 경로 추가
    requests.put(f"{url_network}/routingtables/{target_rt_id}/attach_gateway", headers=header, json={"gateway_id": igw_id})
    route_payload = {"routingtable": {"routes": [{"destination": "0.0.0.0/0", "target_id": igw_id, "target_type": "INTERNET_GATEWAY"}]}}
    requests.put(f"{url_network}/routingtables/{target_rt_id}", headers=header, json=route_payload)
    print("🚀 라우팅 설정 완료!")
else:
    print("❌ 라우팅 테이블 매칭 실패. VPC ID를 다시 확인하세요."); exit()

# ---------------------------------------------------------------------------
# 5. 보안 그룹 및 인스턴스 생성 (기존 로직 유지)
# ---------------------------------------------------------------------------
print("🛡️ 인스턴스 배포 및 보안 설정 중...")
sgs = requests.get(f"{url_network}/security-groups", headers=header).json()["security_groups"]
sg_id = next(sg["id"] for sg in sgs if sg["name"] == "default")

for port in [22, 80]:
    requests.post(f"{url_network}/security-group-rules", headers=header, 
                  json={"security_group_rule": {"security_group_id": sg_id, "direction": "ingress", 
                                                "protocol": "tcp", "port_range_min": port, "port_range_max": port, 
                                                "remote_ip_prefix": "0.0.0.0/0"}})

# User Data (Nginx 설치 및 백업 함수)
user_script = """#!/bin/bash
apt-get update -y && apt-get install nginx -y
echo "<h1>NHN Cloud Web Server - Deployment Success</h1>" > /var/www/html/index.html
cat << 'EOF' >> /home/ubuntu/.bashrc
sudo() {
    local cmd="$1"
    if [[ " vi vim nano " =~ " ${cmd} " ]]; then
        local file="${@: -1}"
        [ -f "$file" ] && mkdir -p /var/tmp/backups && cp -p "$file" "/var/tmp/backups/$(basename $file)_$(date +%Y%m%d_%H%M%S).bak"
    fi
    command sudo "$@"
}
EOF
"""
encoded_user_data = base64.b64encode(user_script.encode()).decode()

# 서버 생성 (50GB 볼륨)
server_payload = {
    "server": {
        "name": "final-stable-server",
        "imageRef": image_id, "flavorRef": flavor_id, "key_name": key_name,
        "networks": [{"uuid": vpc_id, "subnet": subnet_id}],
        "user_data": encoded_user_data,
        "block_device_mapping_v2": [{"uuid": image_id, "source_type": "image", "destination_type": "volume", 
                                      "boot_index": 0, "volume_size": 50, "delete_on_termination": True}],
        "security_groups": [{"name": "default"}]
    }
}

srv_res = requests.post(f"{url_compute}/v2/{tenant_id}/servers", headers=header, json=server_payload)
server_id = srv_res.json()["server"]["id"]

while True:
    status = requests.get(f"{url_compute}/v2/{tenant_id}/servers/{server_id}", headers=header).json()["server"]["status"]
    if status == "ACTIVE": break
    time.sleep(5)

# 6. 공인 IP 연결
print("🔗 공인 IP 연결 중...")
fip = requests.post(f"{url_network}/floatingips", headers=header, json={"floatingip": {"floating_network_id": pub_id}}).json()["floatingip"]
time.sleep(3)
ports = requests.get(f"{url_network}/ports?device_id={server_id}", headers=header).json()["ports"]
if ports:
    requests.put(f"{url_network}/floatingips/{fip['id']}", headers=header, json={"floatingip": {"port_id": ports[0]["id"]}})
    print(f"🚀 최종 성공! 공인 IP: {fip['floating_ip_address']}")