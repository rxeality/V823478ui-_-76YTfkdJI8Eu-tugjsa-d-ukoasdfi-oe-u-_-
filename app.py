import os
import requests
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

# SECURITY: Get the Password from Cloud Settings
API_KEY = os.environ.get("MY_SECRET_KEY", "default_insecure_key")

# RATE LIMITING: Prevent Spam
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["100 per minute"],
    storage_uri="memory://"
)

# ROBLOX APIs
ROBLOX_GAMES_API = "https://games.roblox.com/v1/games/{}/servers/Public?sortOrder=Asc&limit=100"
THUMBNAIL_BATCH_API = "https://thumbnails.roblox.com/v1/batch"
HEADSHOT_API = "https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={}&size=150x150&format=Png&isCircular=false"

def verify_api_key(req):
    key = req.headers.get("X-API-KEY")
    return key == API_KEY

def get_target_headshot(user_id):
    try:
        response = requests.get(HEADSHOT_API.format(user_id))
        if response.status_code != 200: return None
        data = response.json()
        if 'data' in data and len(data['data']) > 0:
            return data['data'][0]['imageUrl']
    except:
        return None
    return None

@app.route('/find-user', methods=['POST'])
@limiter.limit("5 per second") 
def find_user():
    # 1. SECURITY CHECK
    if not verify_api_key(request):
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    user_id = data.get('userId')
    place_id = data.get('placeId')

    if not user_id or not place_id:
        return jsonify({"error": "Missing Data"}), 400

    # 2. Get Target Face
    target_face = get_target_headshot(user_id)
    if not target_face:
        return jsonify({"error": "Target thumbnail not found"}), 404

    # 3. Scan Servers (Limit to 5 pages for speed)
    next_cursor = ""
    pages_scanned = 0 

    while pages_scanned < 5: 
        url = ROBLOX_GAMES_API.format(place_id)
        if next_cursor:
            url += f"&cursor={next_cursor}"

        try:
            resp = requests.get(url)
            server_data = resp.json()
        except:
            break

        if 'data' not in server_data:
            break

        servers = server_data['data']
        batch_requests = []
        token_map = {} 

        for server in servers:
            for token in server.get('playerTokens', []):
                req_id = f"{server['id']}_{token[:5]}"
                batch_requests.append({
                    "requestId": req_id,
                    "type": "AvatarHeadShot",
                    "targetId": 0,
                    "token": token,
                    "size": "150x150",
                    "format": "Png",
                    "isCircular": False
                })
                token_map[req_id] = server['id']

        if batch_requests:
            try:
                thumb_resp = requests.post(THUMBNAIL_BATCH_API, json=batch_requests)
                thumb_data = thumb_resp.json().get('data', [])

                for result in thumb_data:
                    if result.get('imageUrl') == target_face:
                        return jsonify({
                            "success": True, 
                            "jobId": token_map.get(result['requestId'])
                        })
            except Exception as e:
                print(f"Batch Error: {e}")

        next_cursor = server_data.get('nextPageCursor')
        if not next_cursor:
            break
        pages_scanned += 1

    return jsonify({"success": False, "error": "User not found in scanned servers"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
