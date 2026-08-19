import os
import sqlite3
from typing import List, Dict, Any
from flask import Flask, render_template, request, jsonify
import pdfplumber

app = Flask(__name__)
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

class PDFDatabase:
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
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pdf_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    filepath TEXT UNIQUE NOT NULL,
                    doc_type TEXT DEFAULT 'DDT',
                    doc_number TEXT,
                    doc_date TEXT,
                    total_pages INTEGER DEFAULT 0,
                    file_size_bytes INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS inventario (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codice_articolo TEXT UNIQUE NOT NULL,
                    descrizione TEXT,
                    quantita_disponibile REAL DEFAULT 0,
                    unita_misura TEXT DEFAULT 'PZ',
                    ultimo_aggiornamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ddt_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    codice_articolo TEXT NOT NULL,
                    descrizione TEXT,
                    quantita REAL NOT NULL,
                    FOREIGN KEY (document_id) REFERENCES pdf_documents (id) ON DELETE CASCADE,
                    FOREIGN KEY (codice_articolo) REFERENCES inventario (codice_articolo)
                )
            """)
            conn.commit()

    def registra_carico_ddt(self, filepath: str, doc_number: str, doc_date: str, articoli: List[Dict[str, Any]]) -> int:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            filename = os.path.basename(filepath)
            file_size = os.path.getsize(filepath) if os.path.exists(filepath) else 0

            cursor.execute("""
                INSERT INTO pdf_documents (filename, filepath, doc_type, doc_number, doc_date, file_size_bytes)
                VALUES (?, ?, 'DDT', ?, ?, ?)
            """, (filename, filepath, doc_number, doc_date, file_size))
            doc_id = cursor.lastrowid

            for art in articoli:
                codice = art['codice']
                descrizione = art.get('descrizione', '')
                quantita = float(art['quantita'])

                cursor.execute("""
                    INSERT INTO ddt_items (document_id, codice_articolo, descrizione, quantita)
                    VALUES (?, ?, ?, ?)
                """, (doc_id, codice, descrizione, quantita))

                cursor.execute("""
                    INSERT INTO inventario (codice_articolo, descrizione, quantita_disponibile)
                    VALUES (?, ?, ?)
                    ON CONFLICT(codice_articolo) DO UPDATE SET
                        quantita_disponibile = quantita_disponibile + excluded.quantita_disponibile,
                        descrizione = CASE WHEN excluded.descrizione != '' THEN excluded.descrizione ELSE inventario.descrizione END,
                        ultimo_aggiornamento = CURRENT_TIMESTAMP
                """, (codice, descrizione, quantita))

            conn.commit()
            return doc_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def get_inventario(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM inventario ORDER BY codice_articolo ASC")
            return [dict(row) for row in cursor.fetchall()]

db = PDFDatabase()

def estrai_articoli_da_pdf(filepath: str) -> List[Dict[str, Any]]:
    articoli = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split('\n'):
                parti = line.split()
                if len(parti) >= 3 and parti[0].startswith("ART-"):
                    try:
                        quantita = float(parti[-1])
                        codice = parti[0]
                        descrizione = " ".join(parti[1:-1])
                        articoli.append({
                            "codice": codice,
                            "descrizione": descrizione,
                            "quantita": quantita
                        })
                    except ValueError:
                        continue
    return articoli

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/upload-ddt', methods=['POST'])
def upload_ddt():
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "Nessun file selezionato"}), 400

    file = request.files['file']
    doc_number = request.form.get('doc_number', 'DDT-AUTOGEN')
    doc_date = request.form.get('doc_date', '')

    if file.filename == '':
        return jsonify({"success": False, "error": "Nome file non valido"}), 400

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(filepath)

    articoli = estrai_articoli_da_pdf(filepath)
    
    if not articoli:
        return jsonify({
            "success": False, 
            "error": "Nessun articolo valido trovato nel PDF (i codici devono iniziare con 'ART-')."
        }), 400

    try:
        doc_id = db.registra_carico_ddt(filepath, doc_number, doc_date, articoli)
        return jsonify({
            "success": True,
            "message": "DDT caricato e inventario aggiornato con successo!",
            "doc_id": doc_id,
            "articoli_caricati": len(articoli)
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/inventario', methods=['GET'])
def get_inventario():
    return jsonify(db.get_inventario())

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)