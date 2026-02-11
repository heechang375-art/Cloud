import json
from flask import Flask, render_template, request, Response, jsonify
# 사용자님의 검증된 함수를 직접 가져옵니다.
from nhn_api import get_auth_and_resources, deploy_infrastructure

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_resources', methods=['POST'])
def get_resources():
    d = request.json
    try:
        # nhn_api.py 내부에서 config.py의 'instance-infrastructure'를 참조하므로 
        # 더이상 NameResolutionError가 발생하지 않습니다.
        imgs, flavors, vpcs, subnets, kps, token, pub_id = get_auth_and_resources(
            d['region'], d['user_id'], d['password'], d['tenant_id']
        )
        
        return jsonify({
            "status": "success",
            "vpcs": [{"id": v['id'], "name": v['name'], "cidrv4": v.get('cidrv4', 'N/A')} for v in vpcs],
            "subnets": [{"id": s['id'], "name": s['name'], "vpc_id": s.get('vpc_id')} for s in subnets], # vpc_id 필수!
            "images": [{"id": i['id'], "name": i['name']} for i in imgs],
            "flavors": [{"id": f['id'], "name": f['name'], "vcpus": f['vcpus'], "ram": f['ram']} for f in flavors],
            "keypairs": kps,
            "pub_id": pub_id
        })
    except Exception as e:
        # 에러 발생 시 상세 내용을 브라우저에 전달
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/deploy', methods=['POST'])
def deploy():
    data = request.form.to_dict()
    def generate():
        try:
            _, _, _, _, _, token, _ = get_auth_and_resources(
                data['region'], data['user_id'], data['password'], data['tenant_id']
            )
            for step in deploy_infrastructure(data['region'], token, data):
                if isinstance(step, dict):
                    if step.get('final'):
                        # 최종 성공 결과
                        yield f"data: {json.dumps({'type': 'result', 'payload': step})}\n\n"
                    elif step.get('type') == 'vpc_duplicate':
                        # VPC 중복 이벤트
                        yield f"data: {json.dumps({'type': 'vpc_duplicate', 'payload': step})}\n\n"
                else:
                    # 일반 진행 메시지
                    yield f"data: {json.dumps({'type': 'progress', 'msg': str(step)})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'msg': str(e)})}\n\n"
    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    # 로컬 포트 5000 유지
    app.run(port=5000, debug=True)