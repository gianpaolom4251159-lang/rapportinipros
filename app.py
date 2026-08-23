import os
import sqlite3
import json
from datetime import datetime
from flask import Flask, request, redirect, url_for, render_template_string, flash, send_from_directory, session
from werkzeug.utils import secure_filename

try:
    import pdfplumber
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

app = Flask(__name__)
app.secret_key = 'rapportini_secret_key_pro_v2'

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
LOGO_FOLDER = os.path.join(UPLOAD_FOLDER, 'logo')
PDF_FOLDER = os.path.join(UPLOAD_FOLDER, 'pdf')

os.makedirs(LOGO_FOLDER, exist_ok=True)
os.makedirs(PDF_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['LOGO_FOLDER'] = LOGO_FOLDER
app.config['PDF_FOLDER'] = PDF_FOLDER

DB_FILE = os.path.join(os.path.dirname(__file__), 'database.db')

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Tabella Utenti per Ruoli (Admin / Operatore)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS utenti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            pin TEXT NOT NULL UNIQUE,
            ruolo TEXT NOT NULL -- 'admin' o 'operatore'
        )
    ''')

    # Tabella Prodotti
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS prodotti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codice TEXT UNIQUE NOT NULL,
            nome TEXT NOT NULL,
            descrizione TEXT,
            unita_misura TEXT DEFAULT 'pz',
            quantita_disponibile REAL DEFAULT 0,
            prezzo_unitario REAL DEFAULT 0.0
        )
    ''')
    
    # Tabella Rapportini
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rapportini (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codice_rapportino TEXT NOT NULL,
            data TEXT NOT NULL,
            operatore TEXT NOT NULL,
            cliente TEXT NOT NULL,
            note TEXT,
            prodotti_usati TEXT,
            pdf_filename TEXT,
            pdf_testo_estratto TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Tabella Impostazioni
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS impostazioni (
            chiave TEXT PRIMARY KEY,
            valore TEXT
        )
    ''')

    # Inserimento Utenti Predefiniti se vuoto
    cursor.execute('SELECT COUNT(*) FROM utenti')
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO utenti (nome, pin, ruolo) VALUES ('Amministratore', '9999', 'admin')")
        cursor.execute("INSERT INTO utenti (nome, pin, ruolo) VALUES ('Operatore Base', '1111', 'operatore')")

    # Inserimento Prodotti Base se vuoto
    cursor.execute('SELECT COUNT(*) FROM prodotti')
    if cursor.fetchone()[0] == 0:
        prodotti_base = [
            ('PRD-001', 'Cavo Elettrico 3x2.5mm', 'Cavo bipolare flessibile', 'metri', 100.0, 1.50),
            ('PRD-002', 'Interruttore 16A', 'Modulo per quadro DIN', 'pz', 25.0, 12.00),
            ('PRD-003', 'Tubo PVC 20mm', 'Tubo rigido protettivo', 'metri', 50.0, 0.80)
        ]
        cursor.executemany(
            'INSERT INTO prodotti (codice, nome, descrizione, unita_misura, quantita_disponibile, prezzo_unitario) VALUES (?, ?, ?, ?, ?, ?)',
            prodotti_base
        )

    conn.commit()
    conn.close()

init_db()

def get_logo_path():
    conn = get_db_connection()
    row = conn.execute("SELECT valore FROM impostazioni WHERE chiave = 'logo_filename'").fetchone()
    conn.close()
    if row and row['valore'] and os.path.exists(os.path.join(app.config['LOGO_FOLDER'], row['valore'])):
        return row['valore']
    return None

# --- HTML TEMPLATE UNIFICATO CON LOGIN E RUOLI ---
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gestione Rapportini Pro</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { background-color: #f4f6f9; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .navbar-brand img { max-height: 40px; margin-right: 10px; border-radius: 4px; }
        .card { border-radius: 10px; border: none; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
        .badge-prod { font-size: 0.85em; margin-right: 4px; }
        .header-logo { max-height: 60px; object-fit: contain; }
        @media print { .no-print { display: none !important; } body { background: white; } }
    </style>
</head>
<body>

{% if session.get('user_id') %}
<nav class="navbar navbar-expand-lg navbar-dark bg-dark no-print mb-4 shadow-sm">
    <div class="container-fluid">
        <a class="navbar-brand d-flex align-items-center" href="/">
            {% if logo_filename %}
                <img src="{{ url_for('uploaded_logo', filename=logo_filename) }}" alt="Logo" class="bg-white p-1">
            {% else %}
                <i class="fa-solid fa-clipboard-check text-warning me-2 fa-lg"></i>
            {% endif %}
            <span class="fw-bold">Rapportini Pro</span>
        </a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navMain">
            <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navMain">
            <ul class="navbar-nav me-auto mb-2 mb-lg-0">
                <li class="nav-item">
                    <a class="nav-link {% if page == 'nuovo' %}active fw-bold{% endif %}" href="/rapportino/nuovo"><i class="fa-solid fa-pen-to-square me-1"></i> Modulo Operatore</a>
                </li>
                {% if session.get('ruolo') == 'admin' %}
                <li class="nav-item">
                    <a class="nav-link {% if page == 'home' %}active fw-bold{% endif %}" href="/"><i class="fa-solid fa-list me-1"></i> Pannello Admin (Storico)</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link {% if page == 'prodotti' %}active fw-bold{% endif %}" href="/prodotti"><i class="fa-solid fa-boxes-stacked me-1"></i> Catalogo Prodotti</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link {% if page == 'utenti' %}active fw-bold{% endif %}" href="/utenti"><i class="fa-solid fa-users me-1"></i> Gestione Utenti</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link {% if page == 'impostazioni' %}active fw-bold{% endif %}" href="/impostazioni"><i class="fa-solid fa-sliders me-1"></i> Impostazioni & Logo</a>
                </li>
                {% endif %}
            </ul>
            <div class="d-flex align-items-center text-white me-3">
                <i class="fa-solid fa-user-circle me-1"></i> {{ session.get('nome') }} 
                <span class="badge {% if session.get('ruolo') == 'admin' %}bg-danger{% else %}bg-primary{% endif %} ms-2">{{ session.get('ruolo')|upper }}</span>
            </div>
            <a href="/logout" class="btn btn-outline-light btn-sm"><i class="fa-solid fa-right-from-bracket"></i> Esci</a>
        </div>
    </div>
</nav>
{% endif %}

<div class="container pb-5">

    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for category, message in messages %}
          <div class="alert alert-{{ category }} alert-dismissible fade show no-print" role="alert">
            {{ message }}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
          </div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <!-- SCHERMATA LOGIN -->
    {% if page == 'login' %}
    <div class="row justify-content-center pt-5">
        <div class="col-md-4">
            <div class="card p-4 text-center shadow">
                {% if logo_filename %}
                    <img src="{{ url_for('uploaded_logo', filename=logo_filename) }}" class="header-logo mx-auto mb-3" alt="Logo">
                {% else %}
                    <i class="fa-solid fa-lock fa-3x text-primary mb-3"></i>
                {% endif %}
                <h4 class="mb-3">Accesso Sistema</h4>
                <form action="/login" method="POST">
                    <div class="mb-3">
                        <input type="password" name="pin" class="form-control text-center fs-4" placeholder="Inserisci PIN" required autofocus>
                    </div>
                    <button type="submit" class="btn btn-primary w-100 fw-bold">Entra</button>
                </form>
                <p class="text-muted small mt-3">PIN Predefiniti:<br>Admin: <b>9999</b> | Operatore: <b>1111</b></p>
            </div>
        </div>
    </div>
    {% endif %}

    <!-- ADMIN: HISTORICO RAPPORTINI -->
    {% if page == 'home' %}
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2><i class="fa-solid fa-file-invoice text-primary me-2"></i> Pannello Amministratore</h2>
        <a href="/rapportino/nuovo" class="btn btn-success"><i class="fa-solid fa-plus me-1"></i> Nuovo Rapportino</a>
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
                        <th>Allegato</th>
                        <th class="text-end">Azioni</th>
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
                                <span class="text-muted small">Nessuno</span>
                            {% endif %}
                        </td>
                        <td>
                            {% if r.pdf_filename %}
                                <a href="{{ url_for('uploaded_pdf', filename=r.pdf_filename) }}" target="_blank" class="btn btn-sm btn-outline-danger"><i class="fa-solid fa-file-pdf"></i></a>
                            {% else %}-{% endif %}
                        </td>
                        <td class="text-end">
                            <a href="/rapportino/{{ r.id }}" class="btn btn-sm btn-primary"><i class="fa-solid fa-eye"></i></a>
                            <form action="/rapportino/elimina/{{ r.id }}" method="POST" style="display:inline;" onsubmit="return confirm('Eliminare questo rapportino?');">
                                <button type="submit" class="btn btn-sm btn-outline-danger"><i class="fa-solid fa-trash"></i></button>
                            </form>
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="7" class="text-center py-4 text-muted">Nessun rapportino salvato.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    {% endif %}

    <!-- OPERATORE: COMPILAZIONE -->
    {% if page == 'nuovo' %}
    <div class="row justify-content-center">
        <div class="col-lg-10">
            <div class="card p-4">
                <div class="d-flex justify-content-between align-items-center mb-4 border-bottom pb-3">
                    <h3 class="m-0 text-primary"><i class="fa-solid fa-pen-to-square me-2"></i>Modulo Operatore Intervento</h3>
                    {% if logo_filename %}
                        <img src="{{ url_for('uploaded_logo', filename=logo_filename) }}" class="header-logo" alt="Logo">
                    {% endif %}
                </div>

                <form action="/rapportino/salva" method="POST" enctype="multipart/form-data">
                    <div class="row g-3 mb-3">
                        <div class="col-md-4">
                            <label class="form-label fw-bold">N° Intervento</label>
                            <input type="text" name="codice_rapportino" class="form-control" required value="RAP-{{ current_date_code }}">
                        </div>
                        <div class="col-md-4">
                            <label class="form-label fw-bold">Data Intervento</label>
                            <input type="date" name="data" class="form-control" required value="{{ today_str }}">
                        </div>
                        <div class="col-md-4">
                            <label class="form-label fw-bold">Operatore</label>
                            <input type="text" name="operatore" class="form-control" value="{{ session.get('nome') }}" required>
                        </div>
                    </div>

                    <div class="mb-3">
                        <label class="form-label fw-bold">Cliente / Intestazione</label>
                        <input type="text" name="cliente" class="form-control" placeholder="Es. Nome Cliente / Azienda" required>
                    </div>

                    <div class="mb-4">
                        <label class="form-label fw-bold">Descrizione Lavoro Svolto</label>
                        <textarea name="note" class="form-control" rows="3" placeholder="Dettagli dell'intervento..."></textarea>
                    </div>

                    <div class="card bg-light p-3 mb-4">
                        <h5 class="mb-3 text-dark"><i class="fa-solid fa-boxes-stacked me-2 text-primary"></i>Materiali Utilizzati</h5>
                        <div id="prodotti-container">
                            <div class="row g-2 mb-2 prodotto-row align-items-center">
                                <div class="col-md-7">
                                    <select name="prodotti_ids[]" class="form-select">
                                        <option value="">-- Seleziona Prodotto --</option>
                                        {% for p in prodotti %}
                                            <option value="{{ p.id }}">{{ p.codice }} - {{ p.nome }} (Disp: {{ p.quantita_disponibile }} {{ p.unita_misura }})</option>
                                        {% endfor %}
                                    </select>
                                </div>
                                <div class="col-md-3">
                                    <input type="number" step="0.1" min="0.1" name="prodotti_qty[]" class="form-control" placeholder="Quantità" value="1">
                                </div>
                                <div class="col-md-2 text-end">
                                    <button type="button" class="btn btn-outline-danger" onclick="removeRow(this)"><i class="fa-solid fa-trash"></i></button>
                                </div>
                            </div>
                        </div>
                        <button type="button" class="btn btn-sm btn-outline-primary mt-2" onclick="addProdottoRow()"><i class="fa-solid fa-plus me-1"></i> Aggiungi Articolo</button>
                    </div>

                    <div class="mb-4 border p-3 rounded bg-white">
                        <label class="form-label fw-bold"><i class="fa-solid fa-file-pdf text-danger me-2"></i>Carica Documento PDF (Opzionale)</label>
                        <input type="file" name="pdf_file" class="form-control" accept=".pdf">
                    </div>

                    <div class="d-flex justify-content-end gap-2">
                        <button type="submit" class="btn btn-success px-4"><i class="fa-solid fa-check me-1"></i> Salva Rapportino</button>
                    </div>
                </form>
            </div>
        </div>
    </div>
    <script>
        function addProdottoRow() {
            const container = document.getElementById('prodotti-container');
            const row = container.querySelector('.prodotto-row').cloneNode(true);
            row.querySelector('select').value = '';
            row.querySelector('input').value = '1';
            container.appendChild(row);
        }
        function removeRow(btn) {
            if (document.querySelectorAll('.prodotto-row').length > 1) {
                btn.closest('.prodotto-row').remove();
            }
        }
    </script>
    {% endif %}

    <!-- DETTAGLIO RAPPORTINO -->
    {% if page == 'dettaglio' %}
    <div class="d-flex justify-content-between align-items-center mb-3 no-print">
        <a href="/" class="btn btn-outline-secondary"><i class="fa-solid fa-arrow-left me-1"></i> Indietro</a>
        <button onclick="window.print()" class="btn btn-primary"><i class="fa-solid fa-print me-1"></i> Stampa / PDF</button>
    </div>

    <div class="card p-4">
        <div class="d-flex justify-content-between align-items-center mb-4 border-bottom pb-3">
            <div>
                {% if logo_filename %}
                    <img src="{{ url_for('uploaded_logo', filename=logo_filename) }}" class="header-logo mb-2" alt="Logo">
                {% endif %}
                <h2 class="m-0">Rapportino d'Intervento {{ rapportino.codice_rapportino }}</h2>
            </div>
            <div class="text-end">
                <span class="badge bg-primary fs-6">Data: {{ rapportino.data }}</span>
            </div>
        </div>

        <div class="row mb-4">
            <div class="col-md-6"><div class="p-3 bg-light rounded"><h6>Cliente</h6><h5>{{ rapportino.cliente }}</h5></div></div>
            <div class="col-md-6"><div class="p-3 bg-light rounded"><h6>Operatore</h6><h5>{{ rapportino.operatore }}</h5></div></div>
        </div>

        {% if rapportino.note %}
        <div class="mb-4">
            <h5>Note Intervento</h5>
            <p class="p-3 bg-white border rounded">{{ rapportino.note }}</p>
        </div>
        {% endif %}

        <div class="mb-4">
            <h5>Materiali Utilizzati</h5>
            <table class="table table-bordered">
                <thead class="table-light"><tr><th>Codice</th><th>Prodotto</th><th class="text-center">Quantità</th></tr></thead>
                <tbody>
                    {% for item in prodotti_usati %}
                    <tr>
                        <td><code>{{ item.codice }}</code></td>
                        <td>{{ item.nome }}</td>
                        <td class="text-center fw-bold">{{ item.quantita }} {{ item.unita_misura }}</td>
                    </tr>
                    {% else %}
                    <tr><td colspan="3" class="text-center text-muted">Nessun materiale specificato.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    {% endif %}

    <!-- ADMIN: GESTIONE UTENTI -->
    {% if page == 'utenti' %}
    <div class="row">
        <div class="col-md-4 mb-4">
            <div class="card p-3">
                <h5 class="mb-3">Aggiungi Utente</h5>
                <form action="/utenti/aggiungi" method="POST">
                    <div class="mb-2">
                        <label class="form-label small fw-bold">Nome / Operatore</label>
                        <input type="text" name="nome" class="form-control" required>
                    </div>
                    <div class="mb-2">
                        <label class="form-label small fw-bold">PIN di Accesso</label>
                        <input type="text" name="pin" class="form-control" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label small fw-bold">Ruolo</label>
                        <select name="ruolo" class="form-select">
                            <option value="operatore">Operatore</option>
                            <option value="admin">Amministratore</option>
                        </select>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Salva Utente</button>
                </form>
            </div>
        </div>
        <div class="col-md-8">
            <div class="card p-3">
                <h5 class="mb-3">Utenti Registrati</h5>
                <table class="table table-hover">
                    <thead><tr><th>Nome</th><th>PIN</th><th>Ruolo</th><th>Azione</th></tr></thead>
                    <tbody>
                        {% for u in utenti %}
                        <tr>
                            <td>{{ u.nome }}</td>
                            <td><code>{{ u.pin }}</code></td>
                            <td><span class="badge {% if u.ruolo == 'admin' %}bg-danger{% else %}bg-primary{% endif %}">{{ u.ruolo }}</span></td>
                            <td>
                                <form action="/utenti/elimina/{{ u.id }}" method="POST" style="display:inline;">
                                    <button type="submit" class="btn btn-sm btn-outline-danger"><i class="fa-solid fa-trash"></i></button>
                                </form>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    {% endif %}

    <!-- ADMIN: CATALOGO PRODOTTI -->
    {% if page == 'prodotti' %}
    <div class="row">
        <div class="col-md-4 mb-4">
            <div class="card p-3">
                <h5 class="mb-3">Aggiungi Prodotto</h5>
                <form action="/prodotti/aggiungi" method="POST">
                    <div class="mb-2">
                        <label class="form-label small fw-bold">Codice</label>
                        <input type="text" name="codice" class="form-control" required>
                    </div>
                    <div class="mb-2">
                        <label class="form-label small fw-bold">Nome Prodotto</label>
                        <input type="text" name="nome" class="form-control" required>
                    </div>
                    <div class="row g-2 mb-2">
                        <div class="col-6">
                            <label class="form-label small fw-bold">U.M.</label>
                            <input type="text" name="unita_misura" class="form-control" value="pz">
                        </div>
                        <div class="col-6">
                            <label class="form-label small fw-bold">Giacenza</label>
                            <input type="number" step="0.1" name="quantita_disponibile" class="form-control" value="0">
                        </div>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Salva Prodotto</button>
                </form>
            </div>
        </div>
        <div class="col-md-8">
            <div class="card p-3">
                <h5 class="mb-3">Inventario Magazzino</h5>
                <table class="table table-hover align-middle">
                    <thead><tr><th>Codice</th><th>Nome</th><th>Giacenza</th><th>Azione</th></tr></thead>
                    <tbody>
                        {% for p in prodotti %}
                        <tr>
                            <td><code>{{ p.codice }}</code></td>
                            <td>{{ p.nome }}</td>
                            <td><span class="badge bg-success">{{ p.quantita_disponibile }} {{ p.unita_misura }}</span></td>
                            <td>
                                <form action="/prodotti/elimina/{{ p.id }}" method="POST" style="display:inline;">
                                    <button type="submit" class="btn btn-sm btn-outline-danger"><i class="fa-solid fa-trash"></i></button>
                                </form>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    {% endif %}

    <!-- ADMIN: IMPOSTAZIONI E LOGO -->
    {% if page == 'impostazioni' %}
    <div class="row justify-content-center">
        <div class="col-md-6">
            <div class="card p-4">
                <h4 class="mb-3">Carica Logo Aziendale</h4>
                {% if logo_filename %}
                    <img src="{{ url_for('uploaded_logo', filename=logo_filename) }}" class="img-fluid rounded border p-2 mb-3 bg-white" style="max-height: 100px;">
                {% endif %}
                <form action="/impostazioni/logo" method="POST" enctype="multipart/form-data">
                    <div class="mb-3">
                        <input type="file" name="logo_file" class="form-control" accept="image/*" required>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">Aggiorna Logo</button>
                </form>
            </div>
        </div>
    </div>
    {% endif %}

</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

# --- MIDDLEWARE CONTROL ACCESS ---
def check_auth(role_required=None):
    if not session.get('user_id'):
        return False
    if role_required and session.get('ruolo') != role_required:
        return False
    return True

# --- ROTTE AUTENTICAZIONE ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        pin = request.form.get('pin')
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM utenti WHERE pin = ?', (pin,)).fetchone()
        conn.close()

        if user:
            session['user_id'] = user['id']
            session['nome'] = user['nome']
            session['ruolo'] = user['ruolo']
            flash(f'Benvenuto {user["nome"]}', 'success')
            if user['ruolo'] == 'admin':
                return redirect(url_for('home'))
            return redirect(url_for('nuovo_rapportino'))
        else:
            flash('PIN errato o non registrato.', 'danger')

    return render_template_string(HTML_TEMPLATE, page='login', logo_filename=get_logo_path())

@app.route('/logout')
def logout():
    session.clear()
    flash('Logout effettuato.', 'info')
    return redirect(url_for('login'))

# --- ROTTE AMMINISTRATORE ---
@app.route('/')
def home():
    if not check_auth('admin'):
        if session.get('ruolo') == 'operatore':
            return redirect(url_for('nuovo_rapportino'))
        return redirect(url_for('login'))

    conn = get_db_connection()
    rapportini = conn.execute('SELECT * FROM rapportini ORDER BY id DESC').fetchall()
    
    rapportini_list = []
    for r in rapportini:
        r_dict = dict(r)
        try:
            r_dict['prodotti_usati_parsed'] = json.loads(r_dict['prodotti_usati']) if r_dict['prodotti_usati'] else []
        except:
            r_dict['prodotti_usati_parsed'] = []
        rapportini_list.append(r_dict)
        
    conn.close()
    return render_template_string(HTML_TEMPLATE, page='home', rapportini=rapportini_list, logo_filename=get_logo_path())

@app.route('/utenti')
def gestione_utenti():
    if not check_auth('admin'):
        return redirect(url_for('login'))
    conn = get_db_connection()
    utenti = conn.execute('SELECT * FROM utenti').fetchall()
    conn.close()
    return render_template_string(HTML_TEMPLATE, page='utenti', utenti=utenti, logo_filename=get_logo_path())

@app.route('/utenti/aggiungi', methods=['POST'])
def aggiungi_utente():
    if not check_auth('admin'): return redirect(url_for('login'))
    nome = request.form.get('nome')
    pin = request.form.get('pin')
    ruolo = request.form.get('ruolo')
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO utenti (nome, pin, ruolo) VALUES (?, ?, ?)', (nome, pin, ruolo))
        conn.commit()
        flash('Utente salvato.', 'success')
    except:
        flash('Errore: PIN già utilizzato.', 'danger')
    conn.close()
    return redirect(url_for('gestione_utenti'))

@app.route('/utenti/elimina/<int:user_id>', methods=['POST'])
def elimina_utente(user_id):
    if not check_auth('admin'): return redirect(url_for('login'))
    conn = get_db_connection()
    conn.execute('DELETE FROM utenti WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('gestione_utenti'))

# --- ROTTE RAPPORTINI (OPERATORE / ADMIN) ---
@app.route('/rapportino/nuovo')
def nuovo_rapportino():
    if not check_auth(): return redirect(url_for('login'))
    conn = get_db_connection()
    prodotti = conn.execute('SELECT * FROM prodotti ORDER BY nome ASC').fetchall()
    conn.close()
    
    today_str = datetime.now().strftime('%Y-%m-%d')
    current_date_code = datetime.now().strftime('%Y%m%d-%H%M')
    
    return render_template_string(
        HTML_TEMPLATE, page='nuovo', prodotti=prodotti, today_str=today_str,
        current_date_code=current_date_code, logo_filename=get_logo_path()
    )

@app.route('/rapportino/salva', methods=['POST'])
def salva_rapportino():
    if not check_auth(): return redirect(url_for('login'))
    
    codice_rapportino = request.form.get('codice_rapportino')
    data = request.form.get('data')
    operatore = request.form.get('operatore')
    cliente = request.form.get('cliente')
    note = request.form.get('note', '')

    prodotti_ids = request.form.getlist('prodotti_ids[]')
    prodotti_qty = request.form.getlist('prodotti_qty[]')

    prodotti_usati_list = []
    conn = get_db_connection()

    for p_id, qty in zip(prodotti_ids, prodotti_qty):
        if p_id and qty:
            p_row = conn.execute('SELECT * FROM prodotti WHERE id = ?', (p_id,)).fetchone()
            if p_row:
                qta_num = float(qty)
                prodotti_usati_list.append({
                    'id': p_row['id'], 'codice': p_row['codice'], 'nome': p_row['nome'],
                    'unita_misura': p_row['unita_misura'], 'quantita': qta_num
                })
                nuova_qta = max(0, p_row['quantita_disponibile'] - qta_num)
                conn.execute('UPDATE prodotti SET quantita_disponibile = ? WHERE id = ?', (nuova_qta, p_row['id']))

    pdf_filename = None
    pdf_testo_estratto = None

    if 'pdf_file' in request.files:
        file = request.files['pdf_file']
        if file and file.filename.lower().endswith('.pdf'):
            filename = secure_filename(file.filename)
            save_name = datetime.now().strftime('%Y%m%d_%H%M%S_') + filename
            file_path = os.path.join(app.config['PDF_FOLDER'], save_name)
            file.save(file_path)
            pdf_filename = save_name

            if PDF_SUPPORT:
                try:
                    with pdfplumber.open(file_path) as pdf:
                        testo = "".join([page.extract_text() or "" for page in pdf.pages])
                        pdf_testo_estratto = testo.strip()
                except Exception as e:
                    pdf_testo_estratto = f"Errore: {str(e)}"

    conn.execute('''
        INSERT INTO rapportini (codice_rapportino, data, operatore, cliente, note, prodotti_usati, pdf_filename, pdf_testo_estratto)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (codice_rapportino, data, operatore, cliente, note, json.dumps(prodotti_usati_list), pdf_filename, pdf_testo_estratto))
    
    conn.commit()
    conn.close()

    flash('Rapportino inserito con successo!', 'success')
    return redirect(url_for('home') if session.get('ruolo') == 'admin' else url_for('nuovo_rapportino'))

@app.route('/rapportino/<int:rapportino_id>')
def dettaglio_rapportino(rapportino_id):
    if not check_auth(): return redirect(url_for('login'))
    conn = get_db_connection()
    r = conn.execute('SELECT * FROM rapportini WHERE id = ?', (rapportino_id,)).fetchone()
    conn.close()

    if not r: return redirect(url_for('home'))

    prodotti_usati = json.loads(r['prodotti_usati']) if r['prodotti_usati'] else []

    return render_template_string(
        HTML_TEMPLATE, page='dettaglio', rapportino=r,
        prodotti_usati=prodotti_usati, logo_filename=get_logo_path()
    )

@app.route('/rapportino/elimina/<int:rapportino_id>', methods=['POST'])
def elimina_rapportino(rapportino_id):
    if not check_auth('admin'): return redirect(url_for('login'))
    conn = get_db_connection()
    conn.execute('DELETE FROM rapportini WHERE id = ?', (rapportino_id,))
    conn.commit()
    conn.close()
    flash('Rapportino eliminato.', 'info')
    return redirect(url_for('home'))

# --- ROTTE INVENTARIO E IMPOSTAZIONI ---
@app.route('/prodotti')
def catalogo_prodotti():
    if not check_auth('admin'): return redirect(url_for('login'))
    conn = get_db_connection()
    prodotti = conn.execute('SELECT * FROM prodotti ORDER BY nome ASC').fetchall()
    conn.close()
    return render_template_string(HTML_TEMPLATE, page='prodotti', prodotti=prodotti, logo_filename=get_logo_path())

@app.route('/prodotti/aggiungi', methods=['POST'])
def aggiungi_prodotto():
    if not check_auth('admin'): return redirect(url_for('login'))
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO prodotti (codice, nome, unita_misura, quantita_disponibile) VALUES (?, ?, ?, ?)',
                     (request.form['codice'], request.form['nome'], request.form.get('unita_misura', 'pz'), float(request.form.get('quantita_disponibile', 0))))
        conn.commit()
    except:
        flash('Codice già presente.', 'danger')
    conn.close()
    return redirect(url_for('catalogo_prodotti'))

@app.route('/prodotti/elimina/<int:prodotto_id>', methods=['POST'])
def elimina_prodotto(prodotto_id):
    if not check_auth('admin'): return redirect(url_for('login'))
    conn = get_db_connection()
    conn.execute('DELETE FROM prodotti WHERE id = ?', (prodotto_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('catalogo_prodotti'))

@app.route('/impostazioni')
def impostazioni():
    if not check_auth('admin'): return redirect(url_for('login'))
    return render_template_string(HTML_TEMPLATE, page='impostazioni', logo_filename=get_logo_path())

@app.route('/impostazioni/logo', methods=['POST'])
def salva_logo():
    if not check_auth('admin'): return redirect(url_for('login'))
    if 'logo_file' in request.files:
        file = request.files['logo_file']
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['LOGO_FOLDER'], filename))
            conn = get_db_connection()
            conn.execute("INSERT INTO impostazioni (chiave, valore) VALUES ('logo_filename', ?) ON CONFLICT(chiave) DO UPDATE SET valore=excluded.valore", (filename,))
            conn.commit()
            conn.close()
            flash('Logo aggiornato!', 'success')
    return redirect(url_for('impostazioni'))

@app.route('/uploads/logo/<filename>')
def uploaded_logo(filename):
    return send_from_directory(app.config['LOGO_FOLDER'], filename)

@app.route('/uploads/pdf/<filename>')
def uploaded_pdf(filename):
    return send_from_directory(app.config['PDF_FOLDER'], filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
