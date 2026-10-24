import json
import re
from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
CORS(app)

# String de ligação ao Neon PostgreSQL
DATABASE_URL = "postgresql://neondb_owner:npg_RoaYEzH5kj4Q@ep-curly-dew-b5n5cb5c-pooler.c-7.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

def get_db():
    return psycopg2.connect(DATABASE_URL)

# ==========================================================
# 🏢 EMPRESAS & AUTENTICAÇÃO
# ==========================================================
@app.route('/api/companies', methods=['GET'])
def list_companies():
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, name, code FROM companies ORDER BY id ASC")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(rows), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    company_id = data.get('company_id')
    username = data.get('username', '').strip().lower()
    password = data.get('password', '').strip()

    if not company_id:
        return jsonify({"erro": "Selecione uma empresa válida."}), 400

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT u.id, u.username, u.name, u.role, u.company_id, c.name as company_name 
            FROM users u
            JOIN companies c ON c.id = u.company_id
            WHERE LOWER(u.username) = %s AND u.password = %s AND u.company_id = %s
        """, (username, password, int(company_id)))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user:
            return jsonify({"status": "ok", "user": user}), 200
        return jsonify({"erro": "Credenciais inválidas para a empresa selecionada."}), 401
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

# ==========================================================
# 🛰️ TELEMETRIA & MONITORAMENTO DE FROTA EM TEMPO REAL
# ==========================================================
@app.route('/api/telemetry', methods=['POST'])
def update_telemetry():
    data = request.get_json() or {}
    cid = data.get('company_id')
    fleet = str(data.get('fleet', '')).strip()
    uname = data.get('username', 'motorista')
    name = data.get('name', '')
    role = data.get('role', 'navegador')
    lat = data.get('latitude')
    lng = data.get('longitude')
    heading = data.get('heading', 0)
    speed = data.get('speed_kmh', 0)

    # Garante a identificação da frota mesmo se não informada explicitamente
    if not fleet:
        m = re.search(r'(\d{3,5})', str(name))
        fleet = m.group(1) if m else str(data.get('user_id', '1000'))

    if not cid or lat is None or lng is None:
        return jsonify({"erro": "Dados de localização incompletos"}), 400

    try:
        conn = get_db()
        cur = conn.cursor()
        sql = """
            INSERT INTO user_locations (company_id, fleet, username, name, role, latitude, longitude, heading, speed_kmh, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (company_id, fleet) DO UPDATE SET
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                heading = EXCLUDED.heading,
                speed_kmh = EXCLUDED.speed_kmh,
                name = EXCLUDED.name,
                updated_at = CURRENT_TIMESTAMP;
        """
        cur.execute(sql, (cid, fleet, uname, name, role, lat, lng, heading, speed))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "ok", "fleet": fleet}), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/api/telemetry/active', methods=['GET'])
def get_active_users():
    cid = request.args.get('company_id')
    if not cid:
        return jsonify([]), 200
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, company_id, fleet, username, name, role, latitude, longitude, heading, speed_kmh,
                   EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - updated_at)) as seconds_ago
            FROM user_locations
            WHERE company_id = %s AND updated_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
            ORDER BY updated_at DESC
        """, (int(cid),))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify(rows), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

# ==========================================================
# 🛣️ ROTAS (CRUD POR EMPRESA)
# ==========================================================
@app.route('/api/routes', methods=['GET'])
def list_routes():
    cid = request.args.get('company_id')
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        if cid:
            cursor.execute("SELECT id, company_id, name, distance_meters, waypoints, created_at FROM routes WHERE company_id = %s ORDER BY id DESC", (int(cid),))
        else:
            cursor.execute("SELECT id, company_id, name, distance_meters, waypoints, created_at FROM routes ORDER BY id DESC")
        rows = cursor.fetchall()
        
        routes = []
        for r in rows:
            wp_data = r['waypoints']
            if isinstance(wp_data, str):
                wp_data = json.loads(wp_data)
            routes.append({
                "id": str(r['id']),
                "company_id": r['company_id'],
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
    cid = data.get('company_id')
    name = data.get('name', 'Nova Rota')
    dist = float(data.get('distance_meters', 0))
    waypoints = json.dumps(data.get('waypoints', []))

    if not cid:
        return jsonify({"erro": "ID da empresa obrigatório"}), 400

    try:
        conn = get_db()
        cursor = conn.cursor()
        sql = "INSERT INTO routes (company_id, name, distance_meters, waypoints) VALUES (%s, %s, %s, %s) RETURNING id"
        cursor.execute(sql, (cid, name, dist, waypoints))
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

# ==========================================================
# 🛑 CERCAS VIRTUAIS (CRUD POR EMPRESA)
# ==========================================================
@app.route('/api/fences', methods=['GET'])
def list_fences():
    cid = request.args.get('company_id')
    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        if cid:
            cursor.execute("SELECT id, company_id, name, speed_limit_kmh, points, created_at FROM fences WHERE company_id = %s ORDER BY id DESC", (int(cid),))
        else:
            cursor.execute("SELECT id, company_id, name, speed_limit_kmh, points, created_at FROM fences ORDER BY id DESC")
        rows = cursor.fetchall()
        fences = []
        for r in rows:
            pts_data = r['points']
            if isinstance(pts_data, str):
                pts_data = json.loads(pts_data)
            fences.append({
                "id": str(r['id']),
                "company_id": r['company_id'],
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
    cid = data.get('company_id')
    name = data.get('name', 'Área Restrita')
    speed = int(data.get('speed_limit_kmh', 30))
    points = json.dumps(data.get('points', []))

    if not cid:
        return jsonify({"erro": "ID da empresa obrigatório"}), 400

    try:
        conn = get_db()
        cursor = conn.cursor()
        sql = "INSERT INTO fences (company_id, name, speed_limit_kmh, points) VALUES (%s, %s, %s, %s) RETURNING id"
        cursor.execute(sql, (cid, name, speed, points))
        new_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"id": str(new_id)}), 201
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/api/fences/<fence_id>', methods=['PUT'])
def update_fence(fence_id):
    data = request.get_json() or {}
    name = data.get('name', 'Área Restrita')
    speed = int(data.get('speed_limit_kmh', 30))
    points = json.dumps(data.get('points', []))

    try:
        conn = get_db()
        cursor = conn.cursor()
        sql = "UPDATE fences SET name = %s, speed_limit_kmh = %s, points = %s WHERE id = %s"
        cursor.execute(sql, (name, speed, points, int(fence_id)))
        conn.commit()
        updated = cursor.rowcount
        cursor.close()
        conn.close()
        if updated == 0:
            return jsonify({"erro": "Cerca não encontrada"}), 404
        return jsonify({"mensagem": "Cerca atualizada!"}), 200
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