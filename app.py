from flask import Flask, request, jsonify, render_template
import sqlite3
import requests as req
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
scheduler = BackgroundScheduler() 

def ping_all_monitors():
    conn = sqlite3.connect('pingwatch.db')
    cursor = conn.cursor()
    cursor.execute('SELECT url FROM monitors')
    urls = cursor.fetchall()
    conn.close()
    for (url,) in urls:
        ping_url(url)
    print(f"Pinged {len(urls)} monitors at {datetime.now()}")

def init_db():
    conn = sqlite3.connect('pingwatch.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS monitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            status TEXT NOT NULL,
            response_time REAL,
            checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def ping_url(url):
    conn = sqlite3.connect('pingwatch.db')
    cursor = conn.cursor()
    try:
        start = datetime.now()
        response = req.get(url, timeout=10)
        response_time = (datetime.now() - start).total_seconds() * 1000
        status = 'up' if response.status_code < 400 else 'down'
    except:
        response_time = None
        status = 'down'

    cursor.execute(
        'INSERT INTO pings (url, status, response_time) VALUES (?, ?, ?)',
        (url, status, response_time)
    )

    if status == 'down':
        cursor.execute('''
            SELECT id FROM incidents 
            WHERE url = ? AND resolved_at IS NULL
        ''', (url,))
        if not cursor.fetchone():
            cursor.execute(
                'INSERT INTO incidents (url) VALUES (?)', (url,)
            )
    else:
        cursor.execute('''
            UPDATE incidents SET resolved_at = ?
            WHERE url = ? AND resolved_at IS NULL
        ''', (datetime.now(), url))

    conn.commit()
    conn.close()
    return status, response_time

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/add-monitor', methods=['POST'])
def add_monitor():
    data = request.get_json()
    url = data['url']
    name = data['name']

    conn = sqlite3.connect('pingwatch.db')
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT INTO monitors (url, name) VALUES (?, ?)',
            (url, name)
        )
        conn.commit()
        conn.close()
        status, response_time = ping_url(url)
        return jsonify({
            'message': f'{name} added successfully!',
            'initial_status': status,
            'response_time': response_time
        })
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'This URL is already being monitored!'}), 400
    
@app.route('/monitors')
def get_monitors():
    conn = sqlite3.connect('pingwatch.db')
    cursor = conn.cursor()
    cursor.execute('SELECT url, name FROM monitors')
    monitors = cursor.fetchall()
    
    result = []
    for url, name in monitors:
        cursor.execute('''
            SELECT status, response_time, checked_at 
            FROM pings WHERE url = ? 
            ORDER BY checked_at DESC LIMIT 1
        ''', (url,))
        latest_ping = cursor.fetchone()

        cursor.execute('''
            SELECT COUNT(*) FROM pings 
            WHERE url = ? AND status = 'up'
        ''', (url,))
        up_count = cursor.fetchone()[0]

        cursor.execute('''
            SELECT COUNT(*) FROM pings WHERE url = ?
        ''', (url,))
        total_count = cursor.fetchone()[0]

        uptime = round((up_count / total_count) * 100, 2) if total_count > 0 else 0

        cursor.execute('''
            SELECT response_time FROM pings 
            WHERE url = ? AND response_time IS NOT NULL
            ORDER BY checked_at DESC LIMIT 10
        ''', (url,))
        response_times = [r[0] for r in cursor.fetchall()]

        result.append({
            'name': name,
            'url': url,
            'status': latest_ping[0] if latest_ping else 'unknown',
            'response_time': latest_ping[1] if latest_ping else None,
            'uptime': uptime,
            'response_times': response_times,
            'last_checked': latest_ping[2] if latest_ping else None
        })

    conn.close()
    return jsonify(result)

@app.route('/delete-monitor', methods=['DELETE'])
def delete_monitor():
    data = request.get_json()
    url = data['url']
    conn = sqlite3.connect('pingwatch.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM monitors WHERE url = ?', (url,))
    cursor.execute('DELETE FROM pings WHERE url = ?', (url,))
    cursor.execute('DELETE FROM incidents WHERE url = ?', (url,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/incidents')
def get_incidents():
    conn = sqlite3.connect('pingwatch.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT url, started_at, resolved_at 
        FROM incidents 
        ORDER BY started_at DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    return jsonify([{
        'url': r[0],
        'started_at': r[1],
        'resolved_at': r[2]
    } for r in rows])

@app.route('/incidents-page')
def incidents_page():
    return render_template('incidents.html')

@app.route('/ping-now', methods=['POST'])
def ping_now():
    data = request.get_json()
    url = data['url']
    status, response_time = ping_url(url)
    return jsonify({
        'status': status,
        'response_time': round(response_time, 2) if response_time else None
    })

if __name__ == '__main__':
    init_db()
    scheduler.add_job(ping_all_monitors, 'interval', minutes=5)
    scheduler.start()
    app.run(debug=True, use_reloader=False)