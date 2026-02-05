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

url_auth = "https://api-identity-infrastructure.nhncloudservice.com"
url_compute = "https://kr1-api-instance-infrastructure.nhncloudservice.com"
# 네트워크 API 베이스 (v2.0 포함)
url_net = "https://kr1-api-network-infrastructure.nhncloudservice.com/v2.0"

image_id = "7342b6e2-74d6-4d2c-a65c-90242d1ee218" 
flavor_id = "a4b6a0f7-aeff-4d78-a8d5-7de9f007012d" 
key_name = "vm1-key" 

# 2. 토큰 발급
auth_res = requests.post(f"{url_auth}/v2.0/tokens", 
                         json={"auth": {"tenantId": tenant_id, "passwordCredentials": {"username": username, "password": password}}})
auth_res.raise_for_status()
token = auth_res.json()["access"]["token"]["id"]
header = {"x-auth-token": token, "content-type": "application/json"}

# 3. VPC 및 외부망 ID 확보
vpcs = requests.get(f"{url_network}/vpcs", headers=header).json().get("vpcs", [])
target_vpc = next((v for v in vpcs if v.get("name") == "secure-auto-vpc-final"), None)
if not target_vpc:
    target_vpc = requests.post(f"{url_network}/vpcs", headers=header, json={"vpc": {"name": "secure-auto-vpc-final", "cidrv4": "10.0.0.0/16"}}).json()["vpc"]
vpc_id = target_vpc["id"]

nets = requests.get(f"{url_network}/networks", headers=header).json()["networks"]
pub_id = next(n["id"] for n in nets if n.get("router:external"))

# 4. 서브넷 확인 및 생성 (StopIteration 에러 방지)
sub_res = requests.get(f"{url_network}/vpcsubnets", headers=header).json().get("vpcsubnets", [])
target_subnet = next((s for s in sub_res if s.get("vpc_id") == vpc_id), None)

if not target_subnet:
    # 서브넷이 없으면 생성
    sub_payload = {"vpcsubnet": {"name": "auto-sub-final", "vpc_id": vpc_id, "cidr": "10.0.0.0/24"}}
    target_subnet = requests.post(f"{url_network}/vpcsubnets", headers=header, json=sub_payload).json()["vpcsubnet"]

subnet_id = target_subnet["id"]

# 5. 인터넷 게이트웨이 생성 및 기본 라우팅 테이블 설정
print("🌐 기본 라우팅 테이블에 인터넷 통로 연결 중...")

# 5.1 인터넷 게이트웨이(IGW) 확보
igw_payload = {"internetgateway": {"name": "auto-igw-final", "vpc_id": vpc_id, "external_network_id": pub_id}}
igw_res = requests.post(f"{url_network}/internetgateways", headers=header, json=igw_payload)
if igw_res.status_code == 201:
    igw_id = igw_res.json()["internetgateway"]["id"]
else:
    igw_list = requests.get(f"{url_network}/internetgateways", headers=header).json().get("internetgateways", [])
    igw_id = next(i["id"] for i in igw_list if i.get("vpc_id") == vpc_id)

# 5.2 [해결] 모든 계층 구조를 뒤져서 기본 라우팅 테이블(vpc-892...) 찾기
rt_list = requests.get(f"{url_network}/routingtables", headers=header).json().get("routingtables", [])
target_rt_id = None

for rt in rt_list:
    # 가이드(image_bf20c5.png)에 따른 vpcs 리스트 전수 조사
    vpcs_list = rt.get("vpcs", [])
    is_my_vpc = False
    
    if isinstance(vpcs_list, list):
        is_my_vpc = any(v.get("id") == vpc_id for v in vpcs_list)
    elif isinstance(vpcs_list, dict): # 단일 객체인 경우 대비
        is_my_vpc = vpcs_list.get("id") == vpc_id
    
    # 직접 필드도 확인
    if not is_my_vpc:
        is_my_vpc = (rt.get("vpc_id") == vpc_id)

    # 내 VPC의 테이블이면서 '기본(default)'인 것 선택
    if is_my_vpc and rt.get("default") is True:
        target_rt_id = rt["id"]
        break

# 5.3 게이트웨이 연결 및 경로 추가
if target_rt_id:
    print(f"✅ 기본 라우팅 테이블 발견: {target_rt_id}")
    # IGW 물리적 결합
    requests.put(f"{url_network}/routingtables/{target_rt_id}/attach_gateway", 
                 headers=header, json={"gateway_id": igw_id})
    # 외부망 경로(0.0.0.0/0) 기입
    requests.put(f"{url_network}/routingtables/{target_rt_id}", headers=header, 
                 json={"routingtable": {"routes": [{"destination": "0.0.0.0/0", "target_id": igw_id, "target_type": "INTERNET_GATEWAY"}]}})
    print("🚀 기본 라우팅 테이블에 외부 통로 개설 완료!")
else:
    print("❌ 기본 라우팅 테이블을 끝내 찾지 못했습니다. VPC ID 일치 여부를 확인하세요.")
    exit()
        
# 6. 보안 그룹(22, 80) 및 User Data (Nginx + 백업)
sgs = requests.get(f"{url_network}/security-groups", headers=header).json()["security_groups"]
sg_id = next(sg["id"] for sg in sgs if sg["name"] == "default")
for port in [22, 80]:
    requests.post(f"{url_network}/security-group-rules", headers=header, 
                  json={"security_group_rule": {"security_group_id": sg_id, "direction": "ingress", "protocol": "tcp", "port_range_min": port, "port_range_max": port, "remote_ip_prefix": "0.0.0.0/0"}})

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

# 6. 인스턴스 생성 (볼륨 사이즈 50GB로 상향)
print("💻 인스턴스 생성 시작 (볼륨 사이즈 상향)...")

server_payload = {
    "server": {
        "name": "final-stable-server",
        "imageRef": "7342b6e2-74d6-4d2c-a65c-90242d1ee218",
        "flavorRef": "a4b6a0f7-aeff-4d78-a8d5-7de9f007012d",
        "key_name": "vm1-key",
        "networks": [{"uuid": vpc_id, "subnet": subnet_id}],
        "block_device_mapping_v2": [
            {
                "uuid": "7342b6e2-74d6-4d2c-a65c-90242d1ee218", # 이미지 ID
                "source_type": "image",
                "destination_type": "volume",
                "boot_index": 0,
                "volume_size": 50,           # 20에서 50GB로 상향 조정
                "delete_on_termination": True
            }
        ],
        "security_groups": [{"name": "default"}]
    }
}

srv_res = requests.post(
    f"{url_compute}/v2/{tenant_id}/servers", 
    headers=header, 
    json=server_payload
)

if srv_res.status_code not in [200, 202]:
    print(f"❌ 인스턴스 생성 실패: {srv_res.status_code}")
    print(f"상세 메시지: {srv_res.text}")
    exit()

server_id = srv_res.json()["server"]["id"]
print(f"✅ 인스턴스 생성 요청 완료! (ID: {server_id})")

# 7. ACTIVE 대기 및 공인 IP 연결
while True:
    status_res = requests.get(f"{url_compute}/v2/{tenant_id}/servers/{server_id}", headers=header)
    status = status_res.json()["server"]["status"]
    if status == "ACTIVE": break
    if status == "ERROR":
        print("❌ 인스턴스가 ERROR 상태입니다.")
        exit()
    time.sleep(5)

# 7. 공인 IP(Floating IP) 할당 및 연결 (인스턴스 생성 완료 후 마지막 작업)
print("🔗 공인 IP 할당 및 인스턴스 연결 중...")
fip_res = requests.post(f"{url_network}/floatingips", headers=header, json={"floatingip": {"floating_network_id": pub_id}}).json()
fip_id = fip_res["floatingip"]["id"]
fip_addr = fip_res["floatingip"]["floating_ip_address"]

# 인스턴스의 포트 ID 확인 후 바인딩
time.sleep(3) # 포트 생성 시간 대기
ports = requests.get(f"{url_network}/ports?device_id={server_id}", headers=header).json()["ports"]
if ports:
    port_id = ports[0]["id"]
    requests.put(f"{url_network}/floatingips/{fip_id}", headers=header, json={"floatingip": {"port_id": port_id}})
    print(f"🚀 배포 성공! 공인 IP: {fip_addr}")
else:
    print("❌ 포트를 찾을 수 없습니다.")