import requests
import base64
import time
from config import REGION_MAP

def get_auth_and_resources(region, user_id, password, tenant_id):
    r_info = REGION_MAP[region]
    auth_url = f"{r_info['auth']}/tokens"
    
    # 인증 및 토큰 발급
    payload = {
        "auth": {
            "tenantId": tenant_id.strip(),
            "passwordCredentials": {"username": user_id.strip(), "password": password.strip()}
        }
    }
    res = requests.post(auth_url, json=payload)
    if res.status_code != 200:
        raise Exception(f"인증 실패: {res.text}")
    
    token = res.json()["access"]["token"]["id"]
    headers = {"x-auth-token": token}

    # 1. 이미지 조회
    imgs = requests.get(f"{r_info['image']}/v2/images", headers=headers).json().get("images", [])
    
    # 2. 사양(Flavor) 조회 및 낮은 사양순 정렬
    flv_res = requests.get(f"{r_info['compute']}/v2/{tenant_id.strip()}/flavors/detail", headers=headers)
    flavors = flv_res.json().get("flavors", [])
    # VCPU 낮은 순 -> RAM 낮은 순으로 정렬
    sorted_flavors = sorted(flavors, key=lambda x: (x.get('vcpus', 0), x.get('ram', 0)))
    
    # 3. 네트워크 조회
    nets = requests.get(f"{r_info['network']}/v2.0/networks", headers=headers).json().get("networks", [])
    
    # 4. 키 페어 목록 조회 (vm1-key 등을 가져옴)
    kp_res = requests.get(f"{r_info['compute']}/v2/{tenant_id.strip()}/os-keypairs", headers=headers)
    keypairs = kp_res.json().get("keypairs", [])

    # [핵심] 5개의 값을 정확히 리턴
    return imgs, sorted_flavors, nets, keypairs, token

def deploy_infrastructure(region, token, data, public_key_content=None):
    r_info = REGION_MAP[region]
    headers = {"x-auth-token": token, "content-type": "application/json"}
    server_name = data['server_name']
    tenant_id = data['tenant_id'].strip()

    # --- 1. 네트워크 인프라 선행 구축 ---
    vpc_res = requests.post(f"{r_info['network']}/v2.0/vpcs", headers=headers, json={"vpc": {"name": f"{server_name}-vpc", "cidrv4": "10.0.0.0/16"}})
    vpc_id = vpc_res.json()["vpc"]["id"]

    nets_res = requests.get(f"{r_info['network']}/v2.0/networks", headers=headers)
    pub_net_id = next(n["id"] for n in nets_res.json()["networks"] if n.get("router:external"))
    
    igw_res = requests.post(f"{r_info['network']}/v2.0/internetgateways", headers=headers, json={"internetgateway": {"name": f"{server_name}-igw", "vpc_id": vpc_id, "external_network_id": pub_net_id}})
    igw_id = igw_res.json()["internetgateway"]["id"]

    rt_res = requests.post(f"{r_info['network']}/v2.0/routingtables", headers=headers, json={"routingtable": {"name": f"{server_name}-rt", "vpc_id": vpc_id}})
    rt_id = rt_res.json()["routingtable"]["id"]
    requests.put(f"{r_info['network']}/v2.0/routingtables/{rt_id}/attach_gateway", headers=headers, json={"gateway_id": igw_id})
    requests.put(f"{r_info['network']}/v2.0/routingtables/{rt_id}", headers=headers, json={"routingtable": {"routes": [{"destination": "0.0.0.0/0", "target_id": igw_id, "target_type": "INTERNET_GATEWAY"}]}})
    requests.put(f"{r_info['network']}/v2.0/routingtables/{rt_id}/set_as_default", headers=headers)

    sub_res = requests.post(f"{r_info['network']}/v2.0/vpcsubnets", headers=headers, json={"vpcsubnet": {"name": f"{server_name}-sub", "vpc_id": vpc_id, "cidr": "10.0.0.0/24"}})
    subnet_id = sub_res.json()["vpcsubnet"]["id"]

    sg_res = requests.post(f"{r_info['network']}/v2.0/security-groups", headers=headers, json={"security_group": {"name": f"{server_name}-sg"}})
    sg_id = sg_res.json()["security_group"]["id"]
    for port in [22, 80]:
        requests.post(f"{r_info['network']}/v2.0/security-group-rules", headers=headers, json={"security_group_rule": {"security_group_id": sg_id, "direction": "ingress", "protocol": "tcp", "port_range_min": port, "port_range_max": port, "remote_ip_prefix": "0.0.0.0/0"}})

# --- 2. SSH 키 페어 결정 로직 ---
    final_key_name = None
    private_key_content = None

    # 케이스 A: 기존 키페어 선택 (selected_key_name이 넘어온 경우)
    if data.get('selected_key_name') and data['selected_key_name'] != "CREATE_NEW":
        final_key_name = data['selected_key_name']
        print(f"📦 기존 키 사용: {final_key_name}")
    
    # 케이스 B: 새 키페어 생성
    else:
        final_key_name = f"key-{server_name}-{int(time.time())}"
        print(f"🆕 새 키 생성: {final_key_name}")
        
        # public_key_content가 있으면 등록, 없으면 서버 자동 생성
        kp_payload = {"keypair": {"name": final_key_name}}
        if public_key_content:
            kp_payload["keypair"]["public_key"] = public_key_content.strip()
            
        reg_res = requests.post(f"{r_info['compute']}/v2/{tenant_id}/os-keypairs", 
                                headers=headers, json=kp_payload)
        
        if reg_res.status_code in [200, 201]:
            # 서버가 생성한 경우에만 private_key가 존재함
            private_key_content = reg_res.json().get("keypair", {}).get("private_key")
        else:
            raise Exception(f"키 등록 실패: {reg_res.text}")
        
    # --- 3. 유저 스크립트 정의 (순서 고정) ---
    user_script = r"""#!/bin/bash
# 0. 시스템 업데이트 및 Nginx 설치
apt-get update -y && apt-get install nginx -y
# 1. sudo 백업 함수를 포함한 전역 설정 파일 생성
cat << 'EOF' > /etc/profile.d/sudo_backup.sh
# sudo 사용하여 텍스트 편집시 자동 백업 함수
sudo() {
    local cmd="$1"
    local args=("${@:2}")
    local target_file=""
    local backup_needed=false

    # 1. 편집기 목록
    local editors=("vi" "vim" "nano" "gedit" "nvim")

    if [[ " ${editors[@]} " =~ " ${cmd} " ]]; then
        target_file="${@: -1}"
        [ -f "$target_file" ] && backup_needed=true

    # 2. sed 대응
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

    # 4. 백업 실행 로직
    if [ "$backup_needed" = true ] && [ -n "$target_file" ]; then
        local backup_dir="/var/tmp/sudo_backups"
        local timestamp=$(date +%Y%m%d_%H%M%S)
        local filename=$(basename "$target_file")
        
        command sudo mkdir -p "$backup_dir"
        command sudo chmod 1777 "$backup_dir" # 모든 유저가 쓰되 본인 것만 지울 수 있게 권한 부여
        
        command sudo cp -p "$target_file" "$backup_dir/${filename}_${timestamp}.bak"
        echo "📂 [Backup] '$target_file' 이(가) 안전하게 백업되었습니다."
        echo "    ㄴ 경로: $backup_dir/${filename}_${timestamp}.bak"
    fi

    # 5. 원래 명령어 실행
    command sudo "$@"
}
EOF

# 2. 실행 권한 부여
chmod +x /etc/profile.d/sudo_backup.sh
"""

# --- 3. 인스턴스 생성 ---
    # (user_data 정의 생략)
    server_payload = {
        "server": {
            "name": server_name,
            "imageRef": data['image_id'],
            "flavorRef": data['flavor_id'],
            "key_name": final_key_name,
            "networks": [{"uuid": vpc_id, "subnet": subnet_id}], # 위에서 생성된 ID들
            "security_groups": [{"name": f"{server_name}-sg"}],
            "user_data": base64.b64encode(user_script.encode()).decode(),
            "block_device_mapping_v2": [{
                "uuid": data['image_id'], "source_type": "image", "destination_type": "volume",
                "boot_index": 0, "volume_size": 50, "delete_on_termination": True
            }]
        }
    }
    
    srv_res = requests.post(f"{r_info['compute']}/v2/{tenant_id}/servers", headers=headers, json=server_payload)
    if srv_res.status_code not in [200, 202]:
        raise Exception(f"인스턴스 생성 실패: {srv_res.text}")
    
    server_id = srv_res.json()["server"]["id"]

    # --- 5. 인스턴스 활성화 대기 및 공인 IP 할당 ---
    while True:
        status_res = requests.get(f"{r_info['compute']}/v2/{tenant_id}/servers/{server_id}", headers=headers).json()
        if status_res["server"]["status"] == "ACTIVE": break
        time.sleep(5)

    fip_res = requests.post(f"{r_info['network']}/v2.0/floatingips", headers=headers, 
                            json={"floatingip": {"floating_network_id": pub_net_id}}).json()
    fip_addr = fip_res["floatingip"]["floating_ip_address"]
    
    ports = requests.get(f"{r_info['network']}/v2.0/ports?device_id={server_id}", headers=headers).json()["ports"]
    if ports:
        requests.put(f"{r_info['network']}/v2.0/floatingips/{fip_res['floatingip']['id']}", 
                     headers=headers, json={"floatingip": {"port_id": ports[0]["id"]}})

    return {
        "server_id": srv_res.json()["server"]["id"],
        "floating_ip": fip_addr,
        "key_name": final_key_name,
        "private_key": private_key_content  # 생성 시에만 반환됨
    }