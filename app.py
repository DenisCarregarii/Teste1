import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
CORS(app)

DATABASE_URL = "postgresql://neondb_owner:npg_RoaYEzH5kj4Q@ep-curly-dew-b5n5cb5c-pooler.c-7.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

def get_db():
    return psycopg2.connect(DATABASE_URL)

# ==========================================
# AUTENTICAÇÃO & USUÁRIOS
# ==========================================
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, username, name, role FROM users WHERE username = %s AND password = %s", (username, password))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user:
            return jsonify({"status": "ok", "user": user}), 200
        return jsonify({"erro": "Usuário ou senha inválidos"}), 401
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

# ==========================================
# MONITORAMENTO & TELEMETRIA GPS EM TEMPO REAL
# ==========================================
@app.route('/api/telemetry', methods=['POST'])
def update_telemetry():
    data = request.get_json() or {}
    uid = data.get('user_id')
    uname = data.get('username')
    name = data.get('name')
    role = data.get('role', 'navegador')
    lat = data.get('latitude')
    lng = data.get('longitude')
    heading = data.get('heading', 0)
    speed = data.get('speed_kmh', 0)

    if not uid or lat is None or lng is None:
        return jsonify({"erro": "Dados incompletos"}), 400

    try:
        conn = get_db()
        cur = conn.cursor()
        sql = """
            INSERT INTO user_locations (user_id, username, name, role, latitude, longitude, heading, speed_kmh, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id) DO UPDATE SET
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                heading = EXCLUDED.heading,
                speed_kmh = EXCLUDED.speed_kmh,
                updated_at = CURRENT_TIMESTAMP;
        """
        cur.execute(sql, (uid, uname, name, role, lat, lng, heading, speed))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/api/telemetry/active', methods=['GET'])
def get_active_users():
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Retorna quem enviou coordenadas nos últimos 15 minutos
        cur.execute("""
            SELECT user_id, username, name, role, latitude, longitude, heading, speed_kmh,
                   EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - updated_at)) as seconds_ago
            FROM user_locations
            WHERE updated_at >= CURRENT_TIMESTAMP - INTERVAL '15 minutes'
            ORDER BY updated_at DESC
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(rows), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

# ==========================================
# ROTAS (CRUD)
# ==========================================
@app.route('/api/routes', methods=['GET'])
def list_routes():
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, name, distance_meters, waypoints, created_at FROM routes ORDER BY id DESC")
        rows = cursor.fetchall()
        routes = []
        for r in rows:
            wp_data = r['waypoints']
            if isinstance(wp_data, str):
                wp_data = json.loads(wp_data)
            routes.append({
                "id": str(r['id']),
                "name": r['name'],
                "distance_meters": float(r['distance_meters']) if r['distance_meters'] is not None else 0,
                "waypoints": wp_data or [],
                "created_at": str(r['created_at'])
            })
        cursor.close()
        conn.close()
        return jsonify(routes), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/api/routes', methods=['POST'])
def create_route():
    data = request.get_json() or {}
    name = data.get('name', 'Nova Rota')
    dist = float(data.get('distance_meters', 0))
    waypoints = json.dumps(data.get('waypoints', []))
    try:
        conn = get_db()
        cursor = conn.cursor()
        sql = "INSERT INTO routes (name, distance_meters, waypoints) VALUES (%s, %s, %s) RETURNING id"
        cursor.execute(sql, (name, dist, waypoints))
        new_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"id": str(new_id), "name": name}), 201
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/api/routes/<route_id>', methods=['PUT'])
def update_route(route_id):
    data = request.get_json() or {}
    name = data.get('name')
    dist = float(data.get('distance_meters', 0))
    waypoints = json.dumps(data.get('waypoints', []))
    try:
        conn = get_db()
        cursor = conn.cursor()
        sql = "UPDATE routes SET name = %s, distance_meters = %s, waypoints = %s WHERE id = %s"
        cursor.execute(sql, (name, dist, waypoints, int(route_id)))
        conn.commit()
        updated = cursor.rowcount
        cursor.close()
        conn.close()
        if updated == 0:
            return jsonify({"erro": "Rota não encontrada"}), 404
        return jsonify({"mensagem": "Rota atualizada com sucesso!"}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/api/routes/<route_id>', methods=['DELETE'])
def delete_route(route_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM routes WHERE id = %s", (int(route_id),))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"mensagem": "Rota excluída!"}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

# ==========================================
# CERCAS (CRUD)
# ==========================================
@app.route('/api/fences', methods=['GET'])
def list_fences():
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id, name, speed_limit_kmh, points, created_at FROM fences ORDER BY id DESC")
        rows = cursor.fetchall()
        fences = []
        for r in rows:
            pts_data = r['points']
            if isinstance(pts_data, str):
                pts_data = json.loads(pts_data)
            fences.append({
                "id": str(r['id']),
                "name": r['name'],
                "speed_limit_kmh": int(r['speed_limit_kmh']) if r['speed_limit_kmh'] is not None else 30,
                "points": pts_data or [],
                "created_at": str(r['created_at'])
            })
        cursor.close()
        conn.close()
        return jsonify(fences), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/api/fences', methods=['POST'])
def create_fence():
    data = request.get_json() or {}
    name = data.get('name', 'Restrição')
    speed = int(data.get('speed_limit_kmh', 30))
    points = json.dumps(data.get('points', []))
    try:
        conn = get_db()
        cursor = conn.cursor()
        sql = "INSERT INTO fences (name, speed_limit_kmh, points) VALUES (%s, %s, %s) RETURNING id"
        cursor.execute(sql, (name, speed, points))
        new_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"id": str(new_id)}), 201
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/api/fences/<fence_id>', methods=['DELETE'])
def delete_fence(fence_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM fences WHERE id = %s", (int(fence_id),))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"mensagem": "Cerca excluída!"}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

if __name__ == '__main__':
    app.run(port=5000, debug=True)