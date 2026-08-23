import os
import sqlite3
import json
from typing import List, Dict, Any
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
import pdfplumber

app = Flask(__name__)

# Cartelle per Upload PDF e Loghi
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
LOGOS_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads', 'logos')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(LOGOS_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['LOGOS_FOLDER'] = LOGOS_FOLDER

class ApplicationDatabase:
    def __init__(self, db_path: str = "gestione_magazzino.db"):
        self.db_path = db_path
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Gestione Documenti PDF
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pdf_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    filepath TEXT UNIQUE NOT NULL,
                    doc_type TEXT DEFAULT 'DDT',
                    doc_number TEXT,
                    doc_date TEXT,
                    file_size_bytes INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Tabella Prodotti Selezionabili dagli Operatori
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS prodotti (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codice TEXT UNIQUE NOT NULL,
                    nome TEXT NOT NULL,
                    descrizione TEXT
                )
            """)
            # Tabella Rapportini Operatore (con supporto prodotti usati e Logo)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rapportini (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operatore TEXT NOT NULL,
                    cantiere TEXT NOT NULL,
                    data TEXT NOT NULL,
                    ore REAL NOT NULL,
                    note TEXT,
                    prodotti_utilizzati TEXT, -- Salvati in formato JSON
                    logo_path TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    # --- METODI PDF ---
    def salva_documento_pdf(self, filepath: str, doc_number: str, doc_date: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            filename = os.path.basename(filepath)
            file_size = os.path.getsize(filepath) if os.path.exists(filepath) else 0

            cursor.execute("""
                INSERT INTO pdf_documents (filename, filepath, doc_type, doc_number, doc_date, file_size_bytes)
                VALUES (?, ?, 'DDT', ?, ?, ?)
            """, (filename, filepath, doc_number, doc_date, file_size))
            conn.commit()
            return cursor.lastrowid

    def get_pdf_documents((self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM pdf_documents ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    # --- METODI PRODOTTI E RAPPORTINI ---
    def get_prodotti(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM prodotti ORDER BY nome ASC")
            return [dict(row) for row in cursor.fetchall()]

    def salva_rapportino(self, operatore: str, cantiere: str, data: str, ore: float, note: str, prodotti: list, logo_path: str) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            prodotti_json = json.dumps(prodotti)
            cursor.execute("""
                INSERT INTO rapportini (operatore, cantiere, data, ore, note, prodotti_utilizzati, logo_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (operatore, cantiere, data, ore, note, prodotti_json, logo_path))
            conn.commit()
            return cursor.lastrowid

db = ApplicationDatabase()

# --- ROTTE API ---

@app.route('/')
def index():
    return render_template('index.html')

# Endpoint caricamento PDF DDT
@app.route('/api/upload-ddt', methods=['POST'])
def upload_ddt():
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "Nessun file selezionato"}), 400

    file = request.files['file']
    doc_number = request.form.get('doc_number', 'DDT-AUTOGEN')
    doc_date = request.form.get('doc_date', '')

    if file.filename == '' or not file.filename.lower().endswith('.pdf'):
        return jsonify({"success": False, "error": "Seleziona un file PDF valido"}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    try:
        doc_id = db.salva_documento_pdf(filepath, doc_number, doc_date)
        return jsonify({
            "success": True,
            "message": "File PDF registrato nel database con successo!",
            "doc_id": doc_id
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# Endpoint lista prodotti (per la selezione da parte dell'operatore nel rapportino)
@app.route('/api/prodotti', methods=['GET'])
def get_prodotti():
    return jsonify(db.get_prodotti())

# Endpoint invio Rapportino Operatore (con prodotti e logo)
@app.route('/api/rapportino', methods=['POST'])
def salva_rapportino():
    operatore = request.form.get('operatore', '')
    cantiere = request.form.get('cantiere', '')
    data = request.form.get('data', '')
    ore = request.form.get('ore', 0.0)
    note = request.form.get('note', '')
    
    # Riceve la lista ID o codici dei prodotti selezionati
    prodotti_raw = request.form.get('prodotti', '[]')
    try:
        prodotti = json.loads(prodotti_raw)
    except json.JSONDecodeError:
        prodotti = []

    # Gestione Upload del Logo
    logo_path = ""
    if 'logo' in request.files:
        logo_file = request.files['logo']
        if logo_file.filename != '':
            logo_filename = secure_filename(logo_file.filename)
            logo_path = os.path.join('static', 'uploads', 'logos', logo_filename)
            logo_file.save(os.path.join(app.root_path, logo_path))

    if not operatore or not cantiere:
        return jsonify({"success": False, "error": "Compilare i campi obbligatori (Operatore e Cantiere)"}), 400

    try:
        rap_id = db.salva_rapportino(
            operatore=operatore,
            cantiere=cantiere,
            data=data,
            ore=float(ore),
            note=note,
            prodotti=prodotti,
            logo_path=logo_path
        )
        return jsonify({
            "success": True,
            "message": "Rapportino salvato con successo!",
            "rapportino_id": rap_id
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
