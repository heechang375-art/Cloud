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
print("🔑 토큰 발급 중...")
auth_res = requests.post(f"{url_auth}/v2.0/tokens", 
                         json={"auth": {"tenantId": tenant_id, "passwordCredentials": {"username": username, "password": password}}})
auth_res.raise_for_status()
token = auth_res.json()["access"]["token"]["id"]
header = {"x-auth-token": token, "content-type": "application/json"}

# 3. 네트워크 리소스 확보 (가장 확실한 탐색)
print("🔍 네트워크 리소스 확인 중...")
vpcs = requests.get(f"{url_network}/vpcs", headers=header).json().get("vpcs", [])
# 사용자님의 실제 운영 VPC인 'secure-auto-vpc-final'을 최우선으로 찾습니다.
target_vpc = next((v for v in vpcs if v.get("name") == "secure-auto-vpc-final"), 
                  next((v for v in vpcs if v.get("default") is True), vpcs[0]))
vpc_id = target_vpc["id"]
print(f"✅ 사용 VPC: {target_vpc.get('name')} ({vpc_id})")

nets = requests.get(f"{url_network}/networks", headers=header).json()["networks"]
pub_id = next(n["id"] for n in nets if n.get("router:external"))

sub_res = requests.get(f"{url_network}/vpcsubnets", headers=header).json().get("vpcsubnets", [])
subnet_id = next(s["id"] for s in sub_res if s.get("vpc_id") == vpc_id)

# 4. [수정 핵심] 라우팅 테이블 탐색 로직 (API 가이드 준수)
print("🌐 라우팅 테이블 분석 중...")
rt_list = requests.get(f"{url_network}/routingtables", headers=header).json().get("routingtables", [])
target_rt_id = None

for rt in rt_list:
    # 가이드에 명시된 vpcs 리스트 구조 분석
    vpcs_in_rt = rt.get("vpcs", [])
    
    # 1. 리스트 내부 객체의 ID와 비교
    has_vpc = False
    if isinstance(vpcs_in_rt, list):
        has_vpc = any(v.get("id") == vpc_id for v in vpcs_in_rt)
    
    # 2. 조건 만족 시 선택 (해당 VPC의 기본 테이블)
    if has_vpc and rt.get("default") is True:
        target_rt_id = rt["id"]
        break

if not target_rt_id:
    # 예외 케이스: 이름으로라도 찾기 (vpc-892c93c0-0363 형태 대응)
    target_rt_id = next((rt["id"] for rt in rt_list if vpc_id in str(rt.get("vpcs"))), None)

if target_rt_id:
    print(f"✅ 라우팅 테이블 발견: {target_rt_id}")
    # IGW 생성 및 연결
    igw_payload = {"internetgateway": {"name": "auto-igw", "vpc_id": vpc_id, "external_network_id": pub_id}}
    igw_res = requests.post(f"{url_network}/internetgateways", headers=header, json=igw_payload)
    igw_id = igw_res.json()["internetgateway"]["id"] if igw_res.status_code == 201 else \
             next(i["id"] for i in requests.get(f"{url_network}/internetgateways", headers=header).json()["internetgateways"] if i["vpc_id"] == vpc_id)
    
    requests.put(f"{url_network}/routingtables/{target_rt_id}/attach_gateway", headers=header, json={"gateway_id": igw_id})
    requests.put(f"{url_network}/routingtables/{target_rt_id}", headers=header, 
                 json={"routingtable": {"routes": [{"destination": "0.0.0.0/0", "target_id": igw_id, "target_type": "INTERNET_GATEWAY"}]}})
    print("🚀 인터넷 경로 설정 완료!")
else:
    print("❌ 라우팅 테이블 매칭에 실패했습니다. API 응답 형식을 다시 확인해야 합니다."); exit()

# 5. 보안 그룹 설정 (22, 80 포트 오픈)
print("🛡️ 보안 그룹 설정 중...")
sgs = requests.get(f"{url_network}/security-groups", headers=header).json()["security_groups"]
sg_id = next(sg["id"] for sg in sgs if sg["name"] == "default")

for port in [22, 80]:
    requests.post(f"{url_network}/security-group-rules", headers=header, 
                  json={"security_group_rule": {"security_group_id": sg_id, "direction": "ingress", 
                                                "protocol": "tcp", "port_range_min": port, "port_range_max": port, 
                                                "remote_ip_prefix": "0.0.0.0/0"}})

# 6. User Data (Nginx 설치 및 백업 함수)
user_script = """#!/bin/bash
apt-get update -y && apt-get install nginx -y
systemctl start nginx && systemctl enable nginx
echo "<h1>NHN Cloud Web Server - Deployment Success</h1>" > /var/www/html/index.html
cat << 'EOF' >> /home/ubuntu/.bashrc
sudo() {
    local cmd="$1"
    local editors=("vi" "vim" "nano")
    if [[ " ${editors[@]} " =~ " ${cmd} " ]]; then
        local file="${@: -1}"
        [ -f "$file" ] && mkdir -p /var/tmp/backups && cp -p "$file" "/var/tmp/backups/$(basename $file)_$(date +%Y%m%d_%H%M%S).bak"
    fi
    command sudo "$@"
}
EOF
chown ubuntu:ubuntu /home/ubuntu/.bashrc
"""
encoded_user_data = base64.b64encode(user_script.encode()).decode()

# 7. 인스턴스 생성 (50GB 볼륨 적용)
print("💻 인스턴스 생성 시작 (볼륨 50GB)...")
server_payload = {
    "server": {
        "name": "default-vpc-server",
        "imageRef": image_id,
        "flavorRef": flavor_id,
        "key_name": key_name,
        "networks": [{"uuid": vpc_id, "subnet": subnet_id}],
        "user_data": encoded_user_data,
        "block_device_mapping_v2": [{
            "uuid": image_id,
            "source_type": "image",
            "destination_type": "volume",
            "boot_index": 0,
            "volume_size": 50,
            "delete_on_termination": True
        }],
        "security_groups": [{"name": "default"}]
    }
}

srv_res = requests.post(f"{url_compute}/v2/{tenant_id}/servers", headers=header, json=server_payload)
if srv_res.status_code not in [200, 202]:
    print(f"❌ 인스턴스 생성 실패: {srv_res.text}"); exit()

server_id = srv_res.json()["server"]["id"]

# ACTIVE 상태 대기
print("⏳ 인스턴스 생성 대기 중 (ACTIVE)...")
while True:
    res = requests.get(f"{url_compute}/v2/{tenant_id}/servers/{server_id}", headers=header).json()
    status = res["server"]["status"]
    if status == "ACTIVE": break
    if status == "ERROR": print("❌ 인스턴스 생성 에러 발생"); exit()
    time.sleep(5)

# 8. 공인 IP(Floating IP) 연결
print("🔗 공인 IP 할당 및 연결 중...")
fip_res = requests.post(f"{url_network}/floatingips", headers=header, json={"floatingip": {"floating_network_id": pub_id}}).json()
fip_id = fip_res["floatingip"]["id"]
fip_addr = fip_res["floatingip"]["floating_ip_address"]

# 포트 활성화 대기 후 바인딩
time.sleep(3)
ports = requests.get(f"{url_network}/ports?device_id={server_id}", headers=header).json()["ports"]
if ports:
    requests.put(f"{url_network}/floatingips/{fip_id}", headers=header, json={"floatingip": {"port_id": ports[0]["id"]}})
    print(f"🚀 [최종 성공] 배포가 완료되었습니다!")
    print(f"🌐 접속 IP: http://{fip_addr}")
else:
    print("❌ 서버 포트를 찾을 수 없어 IP 연결에 실패했습니다.")