import os
import sqlite3
import json
from datetime import datetime
from flask import Flask, request, redirect, url_for, render_template_string, flash, send_from_directory
from werkzeug.utils import secure_filename

# Tentativo di importare pdfplumber per la lettura dei file PDF
try:
    import pdfplumber
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

app = Flask(__name__)
app.secret_key = 'rapportini_secret_key_change_me'

# Configurazione cartelle upload
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
LOGO_FOLDER = os.path.join(UPLOAD_FOLDER, 'logo')
PDF_FOLDER = os.path.join(UPLOAD_FOLDER, 'pdf')

os.makedirs(LOGO_FOLDER, exist_ok=True)
os.makedirs(PDF_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['LOGO_FOLDER'] = LOGO_FOLDER
app.config['PDF_FOLDER'] = PDF_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max

DB_FILE = os.path.join(os.path.dirname(__file__), 'database.db')

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Tabella prodotti (catalogo per la selezione dell'operatore)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS prodotti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codice TEXT UNIQUE,
            nome TEXT NOT NULL,
            descrizione TEXT,
            unita_misura TEXT DEFAULT 'pz'
        )
    ''')
    
    # Tabella rapportini
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rapportini (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codice_rapportino TEXT NOT NULL,
            data TEXT NOT NULL,
            operatore TEXT NOT NULL,
            cliente TEXT NOT NULL,
            note TEXT,
            prodotti_usati TEXT, -- JSON con id, nome, quantita
            pdf_filename TEXT,
            pdf_testo_estratto TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Tabella impostazioni (per memorizzare il percorso del logo)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS impostazioni (
            chiave TEXT PRIMARY KEY,
            valore TEXT
        )
    ''')
    
    # Inserimento prodotti di esempio se la tabella è vuota
    cursor.execute('SELECT COUNT(*) FROM prodotti')
    if cursor.fetchone()[0] == 0:
        prodotti_base = [
            ('PRD-001', 'Cavo Elettrico 3x2.5mm', 'Cavo bipolare con terra', 'metri'),
            ('PRD-002', 'Interruttore Magnetotermico 16A', 'Modulo per quadro elettrico', 'pz'),
            ('PRD-003', 'Tubazione PVC 20mm', 'Tubo rigido protettivo', 'metri'),
            ('PRD-004', 'Faretto LED 10W', 'Luce calda da incasso', 'pz'),
            ('PRD-005', 'Morsetti a Leva 3 ingressi', 'Connettori rapidi', 'confezione')
        ]
        cursor.executemany(
            'INSERT INTO prodotti (codice, nome, descrizione, unita_misura) VALUES (?, ?, ?, ?)',
            prodotti_base
        )

    conn.commit()
    conn.close()

# Inizializza il DB all'avvio
init_db()

def get_logo_path():
    conn = get_db_connection()
    row = conn.execute("SELECT valore FROM impostazioni WHERE chiave = 'logo_filename'").fetchone()
    conn.close()
    if row and row['valore'] and os.path.exists(os.path.join(app.config['LOGO_FOLDER'], row['valore'])):
        return row['valore']
    return None

# --- TEMPLATE HTML UNIFICATO ---
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gestione Rapportini Interventi</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { background-color: #f4f6f9; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .navbar-brand img { max-height: 45px; margin-right: 12px; }
        .card { border-radius: 10px; border: none; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
        .badge-prod { font-size: 0.9em; margin-right: 4px; }
        .header-logo { max-height: 60px; object-fit: contain; }
        .print-header { display: none; }
        @media print {
            .no-print { display: none !important; }
            .print-header { display: flex !important; }
            body { background: white; }
            .card { box-shadow: none; border: 1px solid #ddd; }
        }
    </style>
</head>
<body>

<nav class="navbar navbar-expand-lg navbar-dark bg-dark no-print mb-4 shadow-sm">
    <div class="container-fluid">
        <a class="navbar-brand d-flex align-items-center" href="/">
            {% if logo_filename %}
                <img src="{{ url_for('uploaded_logo', filename=logo_filename) }}" alt="Logo" class="bg-white p-1 rounded">
            {% else %}
                <i class="fa-solid fa-clipboard-list fa-lg text-warning me-2"></i>
            {% endif %}
            <span>Gestione Rapportini</span>
        </a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navMain">
            <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navMain">
            <ul class="navbar-nav me-auto mb-2 mb-lg-0">
                <li class="nav-item">
                    <a class="nav-link {% if page == 'home' %}active fw-bold{% endif %}" href="/"><i class="fa-solid fa-list me-1"></i> Elenco Rapportini</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link {% if page == 'nuovo' %}active fw-bold{% endif %}" href="/rapportino/nuovo"><i class="fa-solid fa-plus-circle me-1"></i> Nuovo Rapportino (Operatore)</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link {% if page == 'prodotti' %}active fw-bold{% endif %}" href="/prodotti"><i class="fa-solid fa-boxes-stacked me-1"></i> Catalogo Prodotti</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link {% if page == 'impostazioni' %}active fw-bold{% endif %}" href="/impostazioni"><i class="fa-solid fa-gear me-1"></i> Impostazioni & Logo</a>
                </li>
            </ul>
        </div>
    </div>
</nav>

<div class="container pb-5">

    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for category, message in messages %}
          <div class="alert alert-{{ category }} alert-dismissible fade show no-print" role="alert">
            {{ message }}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
          </div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <!-- ELENCO RAPPORTINI -->
    {% if page == 'home' %}
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2><i class="fa-solid fa-file-invoice text-primary me-2"></i> Rapportini Intervento</h2>
        <a href="/rapportino/nuovo" class="btn btn-success"><i class="fa-solid fa-plus me-1"></i> Compila Rapportino</a>
    </div>

    <div class="card p-3">
        <div class="table-responsive">
            <table class="table table-hover align-middle">
                <thead class="table-light">
                    <tr>
                        <th>N° Doc</th>
                        <th>Data</th>
                        <th>Cliente</th>
                        <th>Operatore</th>
                        <th>Prodotti Utilizzati</th>
                        <th>PDF Allegato</th>
                        <th class="text-end">Azione</th>
                    </tr>
                </thead>
                <tbody>
                    {% for r in rapportini %}
                    <tr>
                        <td><strong>{{ r.codice_rapportino }}</strong></td>
                        <td>{{ r.data }}</td>
                        <td>{{ r.cliente }}</td>
                        <td><span class="badge bg-secondary">{{ r.operatore }}</span></td>
                        <td>
                            {% if r.prodotti_usati_parsed %}
                                {% for prod in r.prodotti_usati_parsed %}
                                    <span class="badge bg-info text-dark badge-prod">{{ prod.nome }} (x{{ prod.quantita }})</span>
                                {% endfor %}
                            {% else %}
                                <span class="text-muted small">Nessun prodotto</span>
                            {% endif %}
                        </td>
                        <td>
                            {% if r.pdf_filename %}
                                <a href="{{ url_for('uploaded_pdf', filename=r.pdf_filename) }}" target="_blank" class="btn btn-sm btn-outline-danger">
                                    <i class="fa-solid fa-file-pdf me-1"></i> Apri PDF
                                </a>
                            {% else %}
                                <span class="text-muted small">-</span>
                            {% endif %}
                        </td>
                        <td class="text-end">
                            <a href="/rapportino/{{ r.id }}" class="btn btn-sm btn-primary"><i class="fa-solid fa-eye"></i> Dettaglio</a>
                        </td>
                    </tr>
                    {% else %}
                    <tr>
                        <td colspan="7" class="text-center py-4 text-muted">
                            <i class="fa-regular fa-folder-open fa-2x mb-2 d-block"></i>
                            Nessun rapportino salvato nel database.
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    {% endif %}

    <!-- FORM OPERATORE: NUOVO RAPPORTINO -->
    {% if page == 'nuovo' %}
    <div class="row justify-content-center">
        <div class="col-lg-10">
            <div class="card p-4">
                <div class="d-flex justify-content-between align-items-center mb-4 border-bottom pb-3">
                    <h3 class="m-0 text-primary"><i class="fa-solid fa-pen-to-square me-2"></i>Modulo Operatore - Rapportino Intervento</h3>
                    {% if logo_filename %}
                        <img src="{{ url_for('uploaded_logo', filename=logo_filename) }}" class="header-logo" alt="Logo Aziendale">
                    {% endif %}
                </div>

                <form action="/rapportino/salva" method="POST" enctype="multipart/form-data">
                    <div class="row g-3 mb-3">
                        <div class="col-md-4">
                            <label class="form-label fw-bold">Codice Rapportino / N° Intervento</label>
                            <input type="text" name="codice_rapportino" class="form-control" required value="RAP-{{ current_date_code }}">
                        </div>
                        <div class="col-md-4">
                            <label class="form-label fw-bold">Data Intervento</label>
                            <input type="date" name="data" class="form-control" required value="{{ today_str }}">
                        </div>
                        <div class="col-md-4">
                            <label class="form-label fw-bold">Nome Operatore / Tecnico</label>
                            <input type="text" name="operatore" class="form-control" placeholder="Es. Mario Rossi" required>
                        </div>
                    </div>

                    <div class="mb-3">
                        <label class="form-label fw-bold">Cliente / Ragione Sociale</label>
                        <input type="text" name="cliente" class="form-control" placeholder="Es. Mario Bianchi S.r.l." required>
                    </div>

                    <div class="mb-4">
                        <label class="form-label fw-bold">Note & Descrizione Attività Svolta</label>
                        <textarea name="note" class="form-control" rows="3" placeholder="Descrivi l'intervento effettuato..."></textarea>
                    </div>

                    <!-- SELEZIONE PRODOTTI UTILIZZATI -->
                    <div class="card bg-light p-3 mb-4">
                        <h5 class="mb-3 text-dark"><i class="fa-solid fa-boxes-stacked me-2 text-primary"></i>Prodotti e Materiali Utilizzati</h5>
                        <p class="text-muted small">Seleziona i prodotti impiegati durante l'intervento e specifica la quantità.</p>
                        
                        <div id="prodotti-container">
                            <div class="row g-2 mb-2 prodotto-row align-items-center">
                                <div class="col-md-7">
                                    <select name="prodotti_ids[]" class="form-select">
                                        <option value="">-- Seleziona Prodotto --</option>
                                        {% for p in prodotti %}
                                            <option value="{{ p.id }}">{{ p.codice }} - {{ p.nome }} ({{ p.unita_misura }})</option>
                                        {% endfor %}
                                    </select>
                                </div>
                                <div class="col-md-3">
                                    <input type="number" step="0.1" min="0.1" name="prodotti_qty[]" class="form-control" placeholder="Qtà" value="1">
                                </div>
                                <div class="col-md-2 text-end">
                                    <button type="button" class="btn btn-outline-danger btn-remove-row" onclick="removeRow(this)"><i class="fa-solid fa-trash"></i></button>
                                </div>
                            </div>
                        </div>

                        <div class="mt-2">
                            <button type="button" class="btn btn-sm btn-outline-primary" onclick="addProdottoRow()"><i class="fa-solid fa-plus me-1"></i> Aggiungi un altro prodotto</button>
                        </div>
                    </div>

                    <!-- CARICAMENTO PDF (OPZIONALE) -->
                    <div class="mb-4 border p-3 rounded bg-white">
                        <label class="form-label fw-bold"><i class="fa-solid fa-file-pdf text-danger me-2"></i>Allegato PDF / Scansione Rapportino (Opzionale)</label>
                        <input type="file" name="pdf_file" class="form-control" accept=".pdf">
                        <div class="form-text">Il sistema estrarrà automaticamente il testo contenuto nel PDF per scopi di archiviazione.</div>
                    </div>

                    <div class="d-flex justify-content-end gap-2">
                        <a href="/" class="btn btn-secondary">Annulla</a>
                        <button type="submit" class="btn btn-success px-4"><i class="fa-solid fa-check me-1"></i> Salva Rapportino</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <script>
        function addProdottoRow() {
            const container = document.getElementById('prodotti-container');
            const firstRow = container.querySelector('.prodotto-row');
            const newRow = firstRow.cloneNode(true);
            newRow.querySelector('select').value = '';
            newRow.querySelector('input').value = '1';
            container.appendChild(newRow);
        }

        function removeRow(btn) {
            const rows = document.querySelectorAll('.prodotto-row');
            if (rows.length > 1) {
                btn.closest('.prodotto-row').remove();
            } else {
                alert('Deve essere presente almeno una riga di selezione.');
            }
        }
    </script>
    {% endif %}

    <!-- DETTAGLIO RAPPORTINO -->
    {% if page == 'dettaglio' %}
    <div class="d-flex justify-content-between align-items-center mb-3 no-print">
        <a href="/" class="btn btn-outline-secondary"><i class="fa-solid fa-arrow-left me-1"></i> Torna all'elenco</a>
        <button onclick="window.print()" class="btn btn-primary"><i class="fa-solid fa-print me-1"></i> Stampa / Salva PDF</button>
    </div>

    <div class="card p-4">
        <div class="d-flex justify-content-between align-items-center mb-4 border-bottom pb-3">
            <div>
                {% if logo_filename %}
                    <img src="{{ url_for('uploaded_logo', filename=logo_filename) }}" class="header-logo mb-2" alt="Logo Azienda">
                {% endif %}
                <h2 class="m-0 text-dark">Rapportino d'Intervento {{ rapportino.codice_rapportino }}</h2>
            </div>
            <div class="text-end">
                <span class="badge bg-primary fs-6 mb-1 d-block">Data: {{ rapportino.data }}</span>
                <span class="text-muted">ID Sistema: #{{ rapportino.id }}</span>
            </div>
        </div>

        <div class="row mb-4">
            <div class="col-md-6">
                <div class="p-3 bg-light rounded">
                    <h6 class="text-uppercase text-muted fw-bold">Dettagli Cliente</h6>
                    <h5 class="mb-1">{{ rapportino.cliente }}</h5>
                </div>
            </div>
            <div class="col-md-6">
                <div class="p-3 bg-light rounded">
                    <h6 class="text-uppercase text-muted fw-bold">Tecnico / Operatore</h6>
                    <h5 class="mb-1"><i class="fa-solid fa-user-gear me-2"></i>{{ rapportino.operatore }}</h5>
                </div>
            </div>
        </div>

        {% if rapportino.note %}
        <div class="mb-4">
            <h5 class="border-bottom pb-2">Note & Attività Svolta</h5>
            <p class="p-3 bg-white border rounded">{{ rapportino.note }}</p>
        </div>
        {% endif %}

        <div class="mb-4">
            <h5 class="border-bottom pb-2">Materiali / Prodotti Utilizzati</h5>
            <table class="table table-bordered align-middle">
                <thead class="table-light">
                    <tr>
                        <th>Codice</th>
                        <th>Descrizione Prodotto</th>
                        <th class="text-center">Quantità</th>
                        <th class="text-center">U.M.</th>
                    </tr>
                </thead>
                <tbody>
                    {% if prodotti_usati %}
                        {% for item in prodotti_usati %}
                        <tr>
                            <td><code>{{ item.codice }}</code></td>
                            <td>{{ item.nome }}</td>
                            <td class="text-center fw-bold">{{ item.quantita }}</td>
                            <td class="text-center">{{ item.unita_misura }}</td>
                        </tr>
                        {% endfor %}
                    {% else %}
                        <tr>
                            <td colspan="4" class="text-center text-muted">Nessun prodotto o materiale registrato per questo intervento.</td>
                        </tr>
                    {% endif %}
                </tbody>
            </table>
        </div>

        {% if rapportino.pdf_filename %}
        <div class="mb-4 no-print">
            <h5 class="border-bottom pb-2"><i class="fa-solid fa-paperclip me-2 text-danger"></i>Documento PDF Allegato</h5>
            <div class="d-flex align-items-center justify-content-between p-3 border rounded bg-light">
                <div>
                    <i class="fa-solid fa-file-pdf fa-2x text-danger me-2"></i>
                    <span>{{ rapportino.pdf_filename }}</span>
                </div>
                <a href="{{ url_for('uploaded_pdf', filename=rapportino.pdf_filename) }}" target="_blank" class="btn btn-outline-danger btn-sm">
                    <i class="fa-solid fa-external-link me-1"></i> Visualizza PDF
                </a>
            </div>
            {% if rapportino.pdf_testo_estratto %}
            <div class="mt-3">
                <h6>Testo estratto dal PDF:</h6>
                <pre class="bg-dark text-light p-3 rounded" style="max-height: 200px; overflow-y: auto;">{{ rapportino.pdf_testo_estratto }}</pre>
            </div>
            {% endif %}
        </div>
        {% endif %}
    </div>
    {% endif %}

    <!-- GESTIONE PRODOTTI -->
    {% if page == 'prodotti' %}
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2><i class="fa-solid fa-boxes-stacked text-primary me-2"></i> Catalogo Prodotti e Materiali</h2>
    </div>

    <div class="row">
        <div class="col-md-4 mb-4">
            <div class="card p-3">
                <h5 class="card-title mb-3">Aggiungi Nuovo Prodotto</h5>
                <form action="/prodotti/aggiungi" method="POST">
                    <div class="mb-2">
                        <label class="form-label small fw-bold">Codice Prodotto</label>
                        <input type="text" name="codice" class="form-control" placeholder="Es. PRD-010" required>
                    </div>
                    <div class="mb-2">
                        <label class="form-label small fw-bold">Nome / Titolo</label>
                        <input type="text" name="nome" class="form-control" placeholder="Es. Valvola sferica" required>
                    </div>
                    <div class="mb-2">
                        <label class="form-label small fw-bold">Unità di Misura</label>
                        <input type="text" name="unita_misura" class="form-control" placeholder="Es. pz, metri, kg" value="pz">
                    </div>
                    <div class="mb-3">
                        <label class="form-label small fw-bold">Descrizione</label>
                        <textarea name="descrizione" class="form-control" rows="2"></textarea>
                    </div>
                    <button type="submit" class="btn btn-primary w-100"><i class="fa-solid fa-plus me-1"></i> Salva Prodotto</button>
                </form>
            </div>
        </div>

        <div class="col-md-8">
            <div class="card p-3">
                <h5 class="card-title mb-3">Elenco Prodotti Selezionabili</h5>
                <div class="table-responsive">
                    <table class="table table-hover align-middle">
                        <thead class="table-light">
                            <tr>
                                <th>Codice</th>
                                <th>Nome Prodotto</th>
                                <th>U.M.</th>
                                <th>Descrizione</th>
                                <th class="text-end">Azione</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for p in prodotti %}
                            <tr>
                                <td><code>{{ p.codice }}</code></td>
                                <td><strong>{{ p.nome }}</strong></td>
                                <td><span class="badge bg-light text-dark border">{{ p.unita_misura }}</span></td>
                                <td><small class="text-muted">{{ p.descrizione or '-' }}</small></td>
                                <td class="text-end">
                                    <form action="/prodotti/elimina/{{ p.id }}" method="POST" style="display:inline;" onsubmit="return confirm('Eliminare questo prodotto dal catalogo?');">
                                        <button type="submit" class="btn btn-sm btn-outline-danger"><i class="fa-solid fa-trash"></i></button>
                                    </form>
                                </td>
                            </tr>
                            {% else %}
                            <tr>
                                <td colspan="5" class="text-center py-3 text-muted">Nessun prodotto presente nel catalogo.</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    {% endif %}

    <!-- IMPOSTAZIONI E LOGO -->
    {% if page == 'impostazioni' %}
    <div class="row justify-content-center">
        <div class="col-md-8">
            <div class="card p-4">
                <h3 class="mb-4 border-bottom pb-2"><i class="fa-solid fa-gear me-2 text-primary"></i>Impostazioni & Logo Aziendale</h3>
                
                <div class="mb-4 text-center p-3 border rounded bg-light">
                    <h6 class="text-uppercase text-muted mb-3">Logo Attuale dell'Azienda</h6>
                    {% if logo_filename %}
                        <img src="{{ url_for('uploaded_logo', filename=logo_filename) }}" style="max-height: 120px;" class="img-fluid rounded border p-2 bg-white mb-2" alt="Logo">
                        <p class="text-success small"><i class="fa-solid fa-circle-check me-1"></i> Logo attivo e visibile nei rapportini</p>
                    {% else %}
                        <div class="py-4 text-muted">
                            <i class="fa-solid fa-image fa-3x mb-2 d-block"></i>
                            Nessun logo aziendale caricato.
                        </div>
                    {% endif %}
                </div>

                <form action="/impostazioni/logo" method="POST" enctype="multipart/form-data">
                    <div class="mb-3">
                        <label class="form-label fw-bold">Carica Nuovo Logo Aziendale (PNG, JPG, SVG)</label>
                        <input type="file" name="logo_file" class="form-control" accept="image/*" required>
                    </div>
                    <button type="submit" class="btn btn-primary"><i class="fa-solid fa-upload me-1"></i> Aggiorna Logo</button>
                </form>
            </div>
        </div>
    </div>
    {% endif %}

</div>

<script href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

# --- ROTTE FLASK ---

@app.route('/')
def home():
    conn = get_db_connection()
    rapportini = conn.execute('SELECT * FROM rapportini ORDER BY id DESC').fetchall()
    
    # Processa il campo prodotti_usati JSON per ciascun rapportino
    rapportini_list = []
    for r in rapportini:
        r_dict = dict(r)
        if r_dict['prodotti_usati']:
            try:
                r_dict['prodotti_usati_parsed'] = json.loads(r_dict['prodotti_usati'])
            except:
                r_dict['prodotti_usati_parsed'] = []
        else:
            r_dict['prodotti_usati_parsed'] = []
        rapportini_list.append(r_dict)
        
    conn.close()
    return render_template_string(
        HTML_TEMPLATE,
        page='home',
        rapportini=rapportini_list,
        logo_filename=get_logo_path()
    )

@app.route('/rapportino/nuovo')
def nuovo_rapportino():
    conn = get_db_connection()
    prodotti = conn.execute('SELECT * FROM prodotti ORDER BY nome ASC').fetchall()
    conn.close()
    
    today_str = datetime.now().strftime('%Y-%m-%d')
    current_date_code = datetime.now().strftime('%Y%m%d-%H%M')
    
    return render_template_string(
        HTML_TEMPLATE,
        page='nuovo',
        prodotti=prodotti,
        today_str=today_str,
        current_date_code=current_date_code,
        logo_filename=get_logo_path()
    )

@app.route('/rapportino/salva', methods=['POST'])
def salva_rapportino():
    codice_rapportino = request.form.get('codice_rapportino')
    data = request.form.get('data')
    operatore = request.form.get('operatore')
    cliente = request.form.get('cliente')
    note = request.form.get('note', '')

    # Lettura dei prodotti selezionati
    prodotti_ids = request.form.getlist('prodotti_ids[]')
    prodotti_qty = request.form.getlist('prodotti_qty[]')

    prodotti_usati_list = []
    conn = get_db_connection()

    for p_id, qty in zip(prodotti_ids, prodotti_qty):
        if p_id and qty:
            p_row = conn.execute('SELECT * FROM prodotti WHERE id = ?', (p_id,)).fetchone()
            if p_row:
                prodotti_usati_list.append({
                    'id': p_row['id'],
                    'codice': p_row['codice'],
                    'nome': p_row['nome'],
                    'unita_misura': p_row['unita_misura'],
                    'quantita': float(qty)
                })

    prodotti_usati_json = json.dumps(prodotti_usati_list)

    # Gestione file PDF allegato
    pdf_filename = None
    pdf_testo_estratto = None

    if 'pdf_file' in request.files:
        file = request.files['pdf_file']
        if file and file.filename.lower().endswith('.pdf'):
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
            save_name = timestamp + filename
            file_path = os.path.join(app.config['PDF_FOLDER'], save_name)
            file.save(file_path)
            pdf_filename = save_name

            # Estrazione testo PDF via pdfplumber se disponibile
            if PDF_SUPPORT:
                try:
                    with pdfplumber.open(file_path) as pdf:
                        testo = ""
                        for page in pdf.pages:
                            text_page = page.extract_text()
                            if text_page:
                                testo += text_page + "\n"
                        pdf_testo_estratto = testo.strip()
                except Exception as e:
                    pdf_testo_estratto = f"Errore lettura PDF: {str(e)}"

    # Inserimento nel database
    conn.execute('''
        INSERT INTO rapportini (codice_rapportino, data, operatore, cliente, note, prodotti_usati, pdf_filename, pdf_testo_estratto)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (codice_rapportino, data, operatore, cliente, note, prodotti_usati_json, pdf_filename, pdf_testo_estratto))
    
    conn.commit()
    conn.close()

    flash('Rapportino registrato con successo!', 'success')
    return redirect(url_for('home'))

@app.route('/rapportino/<int:rapportino_id>')
def dettaglio_rapportino(rapportino_id):
    conn = get_db_connection()
    r = conn.execute('SELECT * FROM rapportini WHERE id = ?', (rapportino_id,)).fetchone()
    conn.close()

    if not r:
        flash('Rapportino non trovato.', 'danger')
        return redirect(url_for('home'))

    prodotti_usati = []
    if r['prodotti_usati']:
        try:
            prodotti_usati = json.loads(r['prodotti_usati'])
        except:
            prodotti_usati = []

    return render_template_string(
        HTML_TEMPLATE,
        page='dettaglio',
        rapportino=r,
        prodotti_usati=prodotti_usati,
        logo_filename=get_logo_path()
    )

@app.route('/prodotti')
def catalogo_prodotti():
    conn = get_db_connection()
    prodotti = conn.execute('SELECT * FROM prodotti ORDER BY nome ASC').fetchall()
    conn.close()
    return render_template_string(
        HTML_TEMPLATE,
        page='prodotti',
        prodotti=prodotti,
        logo_filename=get_logo_path()
    )

@app.route('/prodotti/aggiungi', methods=['POST'])
def aggiungi_prodotto():
    codice = request.form.get('codice')
    nome = request.form.get('nome')
    unita_misura = request.form.get('unita_misura', 'pz')
    descrizione = request.form.get('descrizione', '')

    if codice and nome:
        conn = get_db_connection()
        try:
            conn.execute(
                'INSERT INTO prodotti (codice, nome, unita_misura, descrizione) VALUES (?, ?, ?, ?)',
                (codice, nome, unita_misura, descrizione)
            )
            conn.commit()
            flash('Prodotto aggiunto al catalogo con successo!', 'success')
        except sqlite3.IntegrityError:
            flash('Errore: Codice prodotto già esistente nel catalogo.', 'danger')
        finally:
            conn.close()

    return redirect(url_for('catalogo_prodotti'))

@app.route('/prodotti/elimina/<int:prodotto_id>', methods=['POST'])
def elimina_prodotto(prodotto_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM prodotti WHERE id = ?', (prodotto_id,))
    conn.commit()
    conn.close()
    flash('Prodotto eliminato dal catalogo.', 'info')
    return redirect(url_for('catalogo_prodotti'))

@app.route('/impostazioni')
def impostazioni():
    return render_template_string(
        HTML_TEMPLATE,
        page='impostazioni',
        logo_filename=get_logo_path()
    )

@app.route('/impostazioni/logo', methods=['POST'])
def salva_logo():
    if 'logo_file' in request.files:
        file = request.files['logo_file']
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            save_path = os.path.join(app.config['LOGO_FOLDER'], filename)
            file.save(save_path)

            conn = get_db_connection()
            conn.execute('''
                INSERT INTO impostazioni (chiave, valore) VALUES ('logo_filename', ?)
                ON CONFLICT(chiave) DO UPDATE SET valore=excluded.valore
            ''', (filename,))
            conn.commit()
            conn.close()
            flash('Logo aziendale aggiornato con successo!', 'success')

    return redirect(url_for('impostazioni'))

# Servizio file statici (Logo e PDF allegati)
@app.route('/uploads/logo/<filename>')
def uploaded_logo(filename):
    return send_from_directory(app.config['LOGO_FOLDER'], filename)

@app.route('/uploads/pdf/<filename>')
def uploaded_pdf(filename):
    return send_from_directory(app.config['PDF_FOLDER'], filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
