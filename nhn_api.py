import requests
import base64
import time
from config import REGION_MAP

def get_auth_and_resources(region, user_id, password, tenant_id):
    r_info = REGION_MAP[region]
    auth_url = f"{r_info['auth']}/tokens"
    payload = {"auth": {"tenantId": tenant_id.strip(), "passwordCredentials": {"username": user_id.strip(), "password": password.strip()}}}
    res = requests.post(auth_url, json=payload)
    if res.status_code != 200: raise Exception(f"인증 실패: {res.text}")
    token = res.json()["access"]["token"]["id"]
    headers = {"x-auth-token": token}
    imgs = requests.get(f"{r_info['image']}/v2/images?status=active", headers=headers).json().get("images", [])
    flv_res = requests.get(f"{r_info['compute']}/v2/{tenant_id.strip()}/flavors/detail", headers=headers)
    flavors = sorted([f for f in flv_res.json().get("flavors", []) if 'c1m1' not in f['name']], key=lambda x: (x['vcpus'], x['ram']))
    
    # Public Network ID를 먼저 구함 (필터링 전 전체 VPC 목록에서)
    all_vpcs = requests.get(f"{r_info['network']}/v2.0/vpcs", headers=headers).json().get("vpcs", [])
    pub_id = next((v['id'] for v in all_vpcs if v.get('router:external')), "")
    
    # 사용자가 선택할 VPC 목록 (Public 제외)
    vpcs = [v for v in all_vpcs if "Public" not in v['name']]
    
    subnets = requests.get(f"{r_info['network']}/v2.0/vpcsubnets", headers=headers).json().get("vpcsubnets", [])
    kps = requests.get(f"{r_info['compute']}/v2/{tenant_id.strip()}/os-keypairs", headers=headers).json().get("keypairs", [])
    return imgs, flavors, vpcs, subnets, kps, token, pub_id

def check_resource_exists(region, token, resource_type, target_val, vpc_id=None):
    r_info = REGION_MAP[region]
    headers = {"x-auth-token": token}
    if resource_type == "subnet":
        res = requests.get(f"{r_info['network']}/v2.0/vpcsubnets?vpc_id={vpc_id}", headers=headers)
        match = next((i for i in res.json().get("vpcsubnets", []) if i['cidr'] == target_val), None)
    elif resource_type == "sg":
        res = requests.get(f"{r_info['network']}/v2.0/security-groups", headers=headers)
        match = next((i for i in res.json().get("security_groups", []) if i['name'] == target_val), None)
    elif resource_type == "vpc":
        res = requests.get(f"{r_info['network']}/v2.0/vpcs", headers=headers)
        # Public VPC 제외하고 이름으로 검색
        match = next((i for i in res.json().get("vpcs", []) if i['name'] == target_val and "Public" not in i['name']), None)
    else:
        return None
    return match['id'] if match else None

def deploy_infrastructure(region, token, data):
    r_info = REGION_MAP[region]
    headers = {"x-auth-token": token, "content-type": "application/json"}
    
    # undefined 방지를 위한 기본값 처리
    server_name = data.get('server_name', 'srv-instance')
    tenant_id = data.get('tenant_id', '').strip()
    pub_net_id = data.get('pub_id')
    mode = data.get('mode', 'm_auto')
    
    h = {"vpc": None, "igw": None, "rt": None, "sub": None, "sg": None, "srv": None, "kp": None, "fip": None}
    private_key = None

    try:
        # 1. 키페어 생성 로직 (복구 완료)
        yield "키페어 설정 확인 중..."
        key_name = data.get('selected_key_name')
        if key_name == "new":
            key_name = f"k_{int(time.time()) % 1000000}"
            kp_res = requests.post(f"{r_info['compute']}/v2/{tenant_id}/os-keypairs", 
                                   headers=headers, json={"keypair": {"name": key_name}}).json()
            if "keypair" not in kp_res: raise Exception(f"키페어 생성 실패: {kp_res}")
            private_key = kp_res["keypair"]["private_key"]
            h["kp"] = key_name
            yield f"새 키페어 생성 완료: {key_name}"
        else:
            yield f"기존 키페어 사용: {key_name}"

        # 2. VPC 및 네트워크 구성
        if mode == 'm_new':
            yield "신규 VPC 생성 준비 중..."
            vpc_cidr = data.get('vpc_cidr', '10.0.0.0/16')
            vpc_name = f"{server_name}-vpc"
            
            # VPC 중복 체크
            existing_vpc_id = check_resource_exists(region, token, "vpc", vpc_name)
            
            if existing_vpc_id:
                # 사용자 선택 확인
                user_choice = data.get('vpc_duplicate_action')
                
                if user_choice == 'use_existing':
                    vpc_id = existing_vpc_id
                    yield f"기존 VPC 재사용: {vpc_name}"
                    # 기존 VPC 사용 시 IGW, RT도 재사용 (새로 만들지 않음)
                    mode = 'm_auto'  # 기존 VPC 모드로 전환
                elif user_choice == 'create_new':
                    # 타임스탬프 추가하여 새 이름 생성
                    vpc_name = f"{server_name}-vpc-{int(time.time()) % 100000}"
                    yield f"새 VPC 생성: {vpc_name}"
                else:
                    # 사용자에게 선택 요청 필요
                    yield {"type": "vpc_duplicate", "vpc_name": vpc_name, "need_user_input": True}
                    raise Exception("VPC 중복: 사용자 선택 필요")
            
            # 신규 VPC 생성 (중복 아니거나 create_new 선택)
            if mode == 'm_new':
                yield f"신규 VPC 및 인터넷 게이트웨이 생성 중: {vpc_name}"
                vpc_res = requests.post(f"{r_info['network']}/v2.0/vpcs", headers=headers, 
                                       json={"vpc": {"name": vpc_name, "cidrv4": vpc_cidr}}).json()
                if "vpc" not in vpc_res:
                    raise Exception(f"VPC 생성 실패: {vpc_res.get('NeutronError', {}).get('message', vpc_res)}")
                vpc_id = vpc_res["vpc"]["id"]; h["vpc"] = vpc_id
                yield f"VPC 생성 완료: {vpc_cidr}"
                
                igw_res = requests.post(f"{r_info['network']}/v2.0/internetgateways", headers=headers, 
                                       json={"internetgateway": {"name": f"{server_name}-igw", "vpc_id": vpc_id, "external_network_id": pub_net_id}}).json()
                if "internetgateway" not in igw_res:
                    raise Exception(f"인터넷 게이트웨이 생성 실패: {igw_res}")
                h["igw"] = igw_res["internetgateway"]["id"]
                
                rt_res = requests.post(f"{r_info['network']}/v2.0/routingtables", headers=headers, 
                                      json={"routingtable": {"name": f"{server_name}-rt", "vpc_id": vpc_id}}).json()
                if "routingtable" not in rt_res:
                    raise Exception(f"라우팅 테이블 생성 실패: {rt_res}")
                h["rt"] = rt_res["routingtable"]["id"]
                
                requests.put(f"{r_info['network']}/v2.0/routingtables/{h['rt']}/attach_gateway", headers=headers, json={"gateway_id": h["igw"]})
                requests.put(f"{r_info['network']}/v2.0/routingtables/{h['rt']}", headers=headers, 
                             json={"routingtable": {"routes": [{"destination": "0.0.0.0/0", "target_id": h["igw"], "target_type": "INTERNET_GATEWAY"}]}})
                yield "라우팅 설정 완료"
        else:
            vpc_id = data.get('selected_vpc_id')
            if not vpc_id: raise Exception("사용할 VPC가 선택되지 않았습니다 (undefined).")
            yield "기존 VPC 네트워크 사용 중..."

        # 3. 서브넷 구성 (중복 체크)
        subnet_cidr = data.get('subnet_cidr', '10.0.1.0/24')
        existing_sub = check_resource_exists(region, token, "subnet", subnet_cidr, vpc_id)
        if existing_sub:
            subnet_id = existing_sub
            yield f"기존 서브넷 발견: {subnet_cidr} 재사용"
        else:
            yield f"신규 서브넷 생성 중: {subnet_cidr}"
            sub_res = requests.post(f"{r_info['network']}/v2.0/vpcsubnets", headers=headers, 
                                   json={"vpcsubnet": {"name": f"{server_name}-sub", "vpc_id": vpc_id, "cidr": subnet_cidr}}).json()
            if "vpcsubnet" not in sub_res:
                error_msg = sub_res.get('NeutronError', {}).get('message', str(sub_res))
                raise Exception(f"서브넷 생성 실패: {error_msg}. VPC CIDR 범위를 확인하세요.")
            subnet_id = sub_res["vpcsubnet"]["id"]; h["sub"] = subnet_id
            yield f"서브넷 생성 완료: {subnet_cidr}"

        # 4. 보안 그룹 (중복 체크)
        sg_name = f"{server_name}-sg"
        existing_sg = check_resource_exists(region, token, "sg", sg_name)
        if existing_sg:
            sg_id = existing_sg
            yield "기존 보안 그룹 재사용"
        else:
            yield "보안 그룹 및 정책(22, 80) 생성 중..."
            sg_res = requests.post(f"{r_info['network']}/v2.0/security-groups", headers=headers, json={"security_group": {"name": sg_name}}).json()
            sg_id = sg_res["security_group"]["id"]; h["sg"] = sg_id
            for port in [22, 80]:
                requests.post(f"{r_info['network']}/v2.0/security-group-rules", headers=headers, 
                             json={"security_group_rule": {"security_group_id": sg_id, "direction": "ingress", "protocol": "tcp", "port_range_min": port, "port_range_max": port}})

        # 5. 사용자 스크립트 (Nginx + sudo 백업)
        yield "사용자 정의 스크립트 주입 중..."
        user_script = r"""#!/bin/bash
wait_for_lock() { while fuser /var/lib/dpkg/lock >/dev/null 2>&1 || fuser /var/lib/apt/lists/lock >/dev/null 2>&1 ; do sleep 2; done; }
if [ -x "$(command -v apt-get)" ]; then export DEBIAN_FRONTEND=noninteractive; wait_for_lock; apt-get update -y && apt-get install nginx -y
elif [ -x "$(command -v dnf)" ]; then dnf install -y nginx && systemctl enable --now nginx
elif [ -x "$(command -v yum)" ]; then yum install -y epel-release && yum install -y nginx && systemctl enable --now nginx; fi
cat << 'EOF' > /etc/profile.d/sudo_backup.sh
sudo() {
    local cmd="$1"; local args=("${@:2}"); local target_file=""; local backup_needed=false
    if [[ " vi vim nano sed " =~ " ${cmd} " ]]; then
        if [[ "$cmd" == "sed" ]]; then target_file=$(echo "${args[@]}" | awk '{for(i=1;i<=NF;i++) if(!($i ~ /^-/) && $i != "-i") {print $i; exit}}')
        else target_file="${@: -1}"; fi
        [ -f "$target_file" ] && backup_needed=true
    fi
    if [ "$backup_needed" = true ]; then
        local b_dir="/var/tmp/sudo_backups"; command sudo mkdir -p "$b_dir" && command sudo chmod 1777 "$b_dir"
        command sudo cp -p "$target_file" "$b_dir/$(basename "$target_file")_$(date +%Y%m%d_%H%M%S).bak"
    fi
    command sudo "$@"
}
EOF
chmod +x /etc/profile.d/sudo_backup.sh
"""
        # 6. 인스턴스 생성
        yield "인스턴스 생성 요청..."
        server_payload = {
            "server": {
                "name": server_name, "imageRef": data['image_id'], "flavorRef": data['flavor_id'], "key_name": key_name,
                "networks": [{"uuid": vpc_id, "subnet": subnet_id}], "security_groups": [{"name": sg_name}],
                "user_data": base64.b64encode(user_script.encode()).decode(),
                "block_device_mapping_v2": [{
                    "uuid": data['image_id'], "source_type": "image", "destination_type": "volume",
                    "boot_index": 0, "volume_size": int(data.get('volume_size', 50)), "delete_on_termination": True
                }]
            }
        }
        srv_res = requests.post(f"{r_info['compute']}/v2/{tenant_id}/servers", headers=headers, json=server_payload).json()
        if "server" not in srv_res: raise Exception(f"인스턴스 생성 실패: {srv_res}")
        h["srv"] = srv_res["server"]["id"]

        # 7. 활성화 대기 (무한루프 방지)
        start_t = time.time()
        while True:
            elapsed = int(time.time() - start_t)
            yield f"인스턴스 활성화 대기 중... ({elapsed}초)"
            st = requests.get(f"{r_info['compute']}/v2/{tenant_id}/servers/{h['srv']}", headers=headers).json()
            if st["server"]["status"] == "ACTIVE": break
            if st["server"]["status"] == "ERROR": raise Exception("인스턴스 상태가 ERROR입니다.")
            if elapsed > 600: raise Exception("인스턴스 생성 타임아웃")
            time.sleep(5)

        # 8. Floating IP
        yield "공인 IP 할당 및 연결 중..."
        fip_res = requests.post(f"{r_info['network']}/v2.0/floatingips", headers=headers, json={"floatingip": {"floating_network_id": pub_net_id}}).json()
        h["fip"] = fip_res['floatingip']['id']
        
        # 포트 조회 재시도 (포트가 나타날 때까지)
        port_id = None
        for i in range(5):
            yield f"네트워크 인터페이스 확인 중... ({i+1}/5)"
            p_data = requests.get(f"{r_info['network']}/v2.0/ports?device_id={h['srv']}", headers=headers).json()
            if p_data.get("ports"):
                port_id = p_data["ports"][0]["id"]; break
            time.sleep(3)
        
        if not port_id: raise Exception("포트를 찾을 수 없습니다.")
        requests.put(f"{r_info['network']}/v2.0/floatingips/{h['fip']}", headers=headers, json={"floatingip": {"port_id": port_id}})

        yield {"final": True, "floating_ip": fip_res['floatingip']['floating_ip_address'], "key_name": key_name, "private_key": private_key}

    except Exception as e:
        yield f"에러 발생! 리소스 정리 중: {str(e)}"
        # 롤백 로직 (역순 제거)
        if h["fip"]: requests.delete(f"{r_info['network']}/v2.0/floatingips/{h['fip']}", headers=headers)
        if h["srv"]: requests.delete(f"{r_info['compute']}/v2/{tenant_id}/servers/{h['srv']}", headers=headers); time.sleep(3)
        if h["sg"]: requests.delete(f"{r_info['network']}/v2.0/security-groups/{h['sg']}", headers=headers)
        if h["sub"]: requests.delete(f"{r_info['network']}/v2.0/vpcsubnets/{h['sub']}", headers=headers)
        if h["igw"] and h["rt"]:
            requests.put(f"{r_info['network']}/v2.0/routingtables/{h['rt']}/detach_gateway", headers=headers, json={"gateway_id": h["igw"]})
            requests.delete(f"{r_info['network']}/v2.0/internetgateways/{h['igw']}", headers=headers)
        if h["rt"]: requests.delete(f"{r_info['network']}/v2.0/routingtables/{h['rt']}", headers=headers)
        if h["vpc"] and mode == 'm_new': requests.delete(f"{r_info['network']}/v2.0/vpcs/{h['vpc']}", headers=headers)
        if h["kp"]: requests.delete(f"{r_info['compute']}/v2/{tenant_id}/os-keypairs/{h['kp']}", headers=headers)
        raise e