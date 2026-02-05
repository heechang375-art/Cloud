from flask import Flask, render_template, request, jsonify
import requests
import base64
import math
from dotenv import load_dotenv # type: ignore
import os

app = Flask(__name__)
load_dotenv()
os.path.exists(".env")
tenantId = os.getenv("NHNCloud_tenant_id")
NHNClouduserId = os.getenv("NHNCloud_ID")  # NHNCloud_ID
NHNClouduserPass = os.getenv("NHNCloudpass")  # NHNCloudpass
def calculate_cidr(host_count):
    # 웹 폼에서 받은 값은 문자열일 수 있으므로 숫자로 변환합니다.
    count = int(host_count)
    # NHN Cloud 예약 IP(NW, GW, Broadcast)를 고려해 최소 3개를 더합니다.
    required_ips = count + 3
    # 필요한 IP 개수를 수용할 수 있는 가장 작은 서브넷 마스크(/n)를 계산합니다.
    mask = 32 - math.ceil(math.log2(required_ips))
    return f"10.0.0.0/{mask}"

# 리전별 엔드포인트 설정
REGION_MAP = {
    "KR1": {
        "auth": "https://api-identity-infrastructure.nhncloudservice.com",
        "network": "https://kr1-api-network-infrastructure.nhncloudservice.com/v2.0",
        "compute": "https://kr1-api-instance-infrastructure.nhncloudservice.com"
    },
    "KR2": {
        "auth": "https://api-identity-infrastructure.nhncloudservice.com",
        "network": "https://kr2-api-network-infrastructure.nhncloudservice.com/v2.0",
        "compute": "https://kr2-api-instance-infrastructure.nhncloudservice.com"
    }
}

@app.route('/get_tenants', methods=['POST'])
def fetch_tenants():
    data = request.json
    region = data['region']
    auth_url = REGION_MAP[region]['auth']
    compute_url = REGION_MAP[region]['compute']

    # 1. Scoped 토큰 요청 (.env의 테넌트 ID 사용)
    auth_payload = {
        "auth": {
            "tenantId": tenantId, 
            "passwordCredentials": {
                "username": data['user_id'], 
                "password": data['password']
            }
        }
    }
    
    res = requests.post(f"{auth_url}/v2.0/tokens", json=auth_payload)
    if res.status_code != 200:
        return jsonify({"error": "인증 실패"}), 401

    auth_data = res.json()
    token = auth_data["access"]["token"]["id"]
    headers = {"x-auth-token": token}

    # 2. 이미지/사양 목록 가져오기 및 터미널 출력
    images_res = requests.get(f"{compute_url}/v2/images", headers=headers).json()
    flavors_res = requests.get(f"{compute_url}/v2/flavors", headers=headers).json()
    
    images = images_res.get("images", [])
    flavors = flavors_res.get("flavors", [])

    # 🚀 [중요] 터미널에 데이터가 찍히는지 확인하세요!
    print(f"✅ 가져온 이미지 개수: {len(images)}")
    print(f"✅ 가져온 사양 개수: {len(flavors)}")

    tenant_info = {
        "id": auth_data["access"]["token"]["tenant"]["id"],
        "name": auth_data["access"]["token"]["tenant"]["name"]
    }
    
    return jsonify({
        "tenants": [tenant_info],
        "images": images,
        "flavors": flavors
    })
    
# 2. 최종 배포 시 'Scoped Token'을 사용하여 모든 작업 수행
@app.route('/deploy', methods=['POST'])
def deploy():
    d = request.form
    region_info = REGION_MAP[d['region']]
    tenant_id = d['tenant_id']
    
    # 토큰 발급
    auth_payload = {"auth": {"tenantId": tenant_id, "passwordCredentials": {"username": d['user_id'], "password": d['password']}}}
    token = requests.post(f"{region_info['auth']}/v2.0/tokens", json=auth_payload).json()["access"]["token"]["id"]
    header = {"x-auth-token": token, "content-type": "application/json"}
    
    # 1/4 네트워크 구축
    cidr = calculate_cidr(d['host_count'])
    vpc = requests.post(f"{region_info['network']}/vpcs", headers=header, json={"vpc": {"name": f"{d['server_name']}-vpc", "cidrv4": "10.0.0.0/16"}}).json()["vpc"]
    vpc_id = vpc["id"]
    
    nets = requests.get(f"{region_info['network']}/networks", headers=header).json()["networks"]
    pub_net_id = next(n["id"] for n in nets if n.get("router:external"))
    
    subnet = requests.post(f"{region_info['network']}/vpcsubnets", headers=header, json={"vpcsubnet": {"name": f"{d['server_name']}-sub", "vpc_id": vpc_id, "cidr": cidr}}).json()["vpcsubnet"]
    subnet_id = subnet["id"]
    
    igw = requests.post(f"{region_info['network']}/internetgateways", headers=header, json={"internetgateway": {"name": f"{d['server_name']}-igw", "vpc_id": vpc_id, "external_network_id": pub_net_id}}).json()["internetgateway"]
    
    # 라우팅 테이블 및 set_as_default (사용자 제안 방식)
    rt = requests.post(f"{region_info['network']}/routingtables", headers=header, json={"routingtable": {"name": f"{d['server_name']}-rt", "vpc_id": vpc_id}}).json()["routingtable"]
    requests.put(f"{region_info['network']}/routingtables/{rt['id']}/attach_gateway", headers=header, json={"gateway_id": igw['id']})
    requests.put(f"{region_info['network']}/routingtables/{rt['id']}", headers=header, json={"routingtable": {"routes": [{"destination": "0.0.0.0/0", "target_id": igw['id'], "target_type": "INTERNET_GATEWAY"}]}})
    requests.put(f"{region_info['network']}/routingtables/{rt['id']}/set_as_default", headers=header)
    requests.put(f"{region_info['network']}/vpcsubnets/{subnet_id}", headers=header, json={"vpcsubnet": {"routingtable_id": rt['id']}})

    # 보안 그룹 (SSH, HTTP)
    sg = requests.post(f"{region_info['network']}/security-groups", headers=header, json={"security_group": {"name": f"{d['server_name']}-sg"}}).json()["security_group"]
    for port in [22, 80]:
        requests.post(f"{region_info['network']}/security-group-rules", headers=header, json={"security_group_rule": {"security_group_id": sg['id'], "direction": "ingress", "protocol": "tcp", "port_range_min": port, "port_range_max": port, "remote_ip_prefix": "0.0.0.0/0"}})

    # 인스턴스 생성 (사용자 데이터 포함)
    user_script = r"""#!/bin/bash
apt-get update -y && apt-get install nginx -y
cat << 'EOF' >> /home/ubuntu/.bashrc
sudo() {
    local cmd="$1"
    local args=("${@:2}")
    local target_file=""
    local backup_needed=false
    local editors=("vi" "vim" "nano" "gedit" "nvim")
    if [[ " ${editors[@]} " =~ " ${cmd} " ]]; then
        target_file="${@: -1}"
        [ -f "$target_file" ] && backup_needed=true
    elif [[ "$cmd" == "sed" ]] && [[ "$*" == *"-i"* ]]; then
        for arg in "${args[@]}"; do [ -f "$arg" ] && target_file="$arg" && backup_needed=true && break; done
    elif [[ "$cmd" == "awk" ]] && ([[ "$*" == *"-i"* ]] || [[ "$*" == *">"* ]]); then
        for arg in "${args[@]}"; do [[ "$arg" != -* && -f "$arg" ]] && target_file="$arg" && backup_needed=true && break; done
    fi
    if [ "$backup_needed" = true ]; then
        local backup_dir="/var/tmp/sudo_backups"
        command sudo mkdir -p "$backup_dir" && command sudo chmod 733 "$backup_dir"
        command sudo cp -p "$target_file" "$backup_dir/$(basename "$target_file")_$(date +%Y%m%d_%H%M%S).bak"
    fi
    command sudo "$@"
}
EOF
chown ubuntu:ubuntu /home/ubuntu/.bashrc
"""
    encoded_user_data = base64.b64encode(user_script.encode()).decode()
    
    server_payload = {
        "server": {
            "name": d['server_name'], "imageRef": d['image_id'], "flavorRef": d['flavor_id'],
            "networks": [{"uuid": vpc_id, "subnet": subnet_id}], "security_groups": [{"name": sg['name']}],
            "user_data": encoded_user_data,
            "block_device_mapping_v2": [{"uuid": d['image_id'], "source_type": "image", "destination_type": "volume", "boot_index": 0, "volume_size": 50, "delete_on_termination": True}]
        }
    }
    srv = requests.post(f"{region_info['compute']}/v2/{tenant_id}/servers", headers=header, json=server_payload).json()
    
    return f"✨ 인프라 생성 완료! (VPC: {vpc_id}, Subnet: {subnet_id})"

@app.route('/')
def index():
    return render_template('index.html', regions=REGION_MAP)
    

if __name__ == '__main__':
    app.run(debug=True, port=5000)
