from flask import Flask, render_template, request, jsonify
from nhn_api import get_auth_and_resources, deploy_infrastructure

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_resources', methods=['POST'])
def get_resources():
    try:
        data = request.json
        # 5개를 정확히 언패킹 (imgs, flvs, nets, kps, token)
        imgs, flvs, nets, kps, token = get_auth_and_resources(
            data['region'], 
            data['user_id'], 
            data['password'], 
            data['tenant_id']
        )
        
        # 여기서 token을 리턴 데이터에 포함시키면 프론트에서 보관했다가 
        # 나중에 배포(deploy)할 때 다시 보내줄 수 있어 효율적입니다.
        return jsonify({
            "images": imgs, 
            "flavors": flvs, 
            "networks": nets,
            "keypairs": kps,
            "token": token # 흐리게 보이지 않도록 전송 데이터에 포함
        })
    except Exception as e:
        print(f"리소스 조회 중 에러: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/deploy', methods=['POST'])
def deploy():
    try:
        data = request.form.to_dict()
        key_file = request.files.get('key_file')
        key_content = key_file.read().decode('utf-8') if key_file else None

        # 인증 토큰 재발급 (안전한 배포를 위해)
        _, _, _, _, token = get_auth_and_resources(
            data['region'], data['user_id'], data['password'], data['tenant_id']
        )
        
        result = deploy_infrastructure(data['region'], token, data, key_content)
        return jsonify({"status": "success", "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)