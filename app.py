from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

# =======CALCULAR FATURA

def calcular_fatura(data_compra_str, dia_fechamento):
    data = datetime.strptime(data_compra_str, "%Y-%m-%d")

    if data.day <= int(dia_fechamento):
        return f"{data.month}/{data.year}"
    else:
        if data.month == 12:
            return f"1/{data.year + 1}"
        else:
            return f"{data.month + 1}/{data.year}"



app = Flask(__name__, static_folder='static')

app.secret_key = 'fluxo_certo_123'
app.permanent_session_lifetime = timedelta(days=7)

def formatar_real(valor):
    valor = valor or 0
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

app.jinja_env.filters['real'] = formatar_real

# ==== LOGIN

@app.route('/', methods=['GET', 'POST'])
def login():    

    if request.method == 'POST':
        usuario = request.form.get('usuario')
        senha = request.form.get('senha')

        conn = sqlite3.connect("banco.db")
        cursor = conn.cursor()

        from werkzeug.security import check_password_hash
        from datetime import datetime

        cursor.execute(
            "SELECT * FROM usuarios WHERE usuario=?",
            (usuario,)
        )

        user = cursor.fetchone()
        conn.close()

        if user:
            senha_banco = user[2]

            if check_password_hash(senha_banco, senha) or senha_banco == senha:

                # 🔐 BLOQUEIO POR VENCIMENTO (ADMIN NÃO BLOQUEIA)
                if not user[3]:

                    vencimento = user[5]

                    if vencimento:
                        hoje = datetime.now().date()
                        data_venc = datetime.strptime(vencimento, "%Y-%m-%d").date()

                        if hoje > data_venc:
                            return render_template(
                                'login.html',
                                erro="Acesso bloqueado. Mensalidade vencida."
                            )

                # 👇 LOGIN NORMAL
                if request.form.get('lembrar'):
                    session.permanent = True
                else:
                    session.permanent = False

                session['logado'] = True
                session['usuario_id'] = user[0]
                session['admin'] = user[3]

                # 🔐 FORÇAR TROCA DE SENHA (EXCETO USUÁRIO TESTE)
                if (user[4] == 1 or user[4] is None) and user[0] != 2:
                    session['trocar_senha'] = True
                    return redirect('/trocar-senha')

                return redirect('/dashboard')

        return render_template('login.html', erro="Usuário ou senha inválidos")

    return render_template('login.html')

# ====== TROCAR SENHA

@app.route('/trocar-senha', methods=['GET', 'POST'])
def trocar_senha():

    if not session.get('logado'):
        return redirect('/')

    if request.method == 'POST':

        nova_senha = request.form.get('senha')

        from werkzeug.security import generate_password_hash

        senha_hash = generate_password_hash(nova_senha)

        conn = sqlite3.connect("banco.db")
        cursor = conn.cursor()

        usuario_id = session.get('usuario_id')

        cursor.execute("""
            UPDATE usuarios
            SET senha = ?, primeiro_acesso = 0
            WHERE id = ?
        """, (senha_hash, usuario_id))

        conn.commit()
        conn.close()

        session['trocar_senha'] = False

        return redirect('/dashboard')

    return render_template('trocar_senha.html')


# ===== ATUALIZAR VENCIMENTO

@app.route('/atualizar-vencimento/<int:id>', methods=['POST'])
def atualizar_vencimento(id):

    if not session.get('admin'):
        return redirect('/dashboard')

    vencimento = request.form.get('vencimento')

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE usuarios SET vencimento=? WHERE id=?",
        (vencimento, id)
    )

    conn.commit()
    conn.close()

    return redirect('/cadastro-admin-987')

# ===== LOGOUT

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# =======CADUSUARIO

@app.route('/cadastro-admin-987')
def cadastro_admin():

    if not session.get('logado'):
        return redirect('/')

    if not session.get('admin'):
        return redirect('/dashboard')

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM usuarios")
    usuarios = cursor.fetchall()

    conn.close()

    return render_template('cadastro_admin.html', usuarios=usuarios)

# ========================
# BANCO
# ========================
def init_db():
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    # LIVRO CAIXA
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lancamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT,
            descricao TEXT,
            valor REAL,
            tipo TEXT,
            pago INTEGER DEFAULT 0
        )
    ''')

    # CARTÃO
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cartao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_compra TEXT,
            valor_total REAL,
            parcelas INTEGER,
            descricao TEXT,
            nome_cartao TEXT
        )
    ''')

    # PARCELAS
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cartao_parcelas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_cartao INTEGER,
            data_parcela TEXT,
            valor REAL,
            num_parcela INTEGER,
            paga INTEGER DEFAULT 0,
            usuario_id INTEGER
        )
    ''')

    # CARTÕES
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cartoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_cartao TEXT,
            limite REAL
        )
    ''')

    # 💥 METAS (AGORA NO LUGAR CERTO)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            valor_total REAL,
            valor_atual REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT UNIQUE,
            senha TEXT
        )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS aplicacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data TEXT,
        aplicacao TEXT,
        valor_aplicacao REAL,
        valor_rendimento REAL,
        valor_resgate REAL
        )
    ''')

    conn.commit()
    conn.close()
init_db()

# ========================
# HOME
# ========================
@app.route('/dashboard')
def dashboard():

    if not session.get('logado'):
        return redirect('/')
    
    if session.get('trocar_senha'):
        return redirect('/trocar-senha')

    usuario_id = session.get('usuario_id')

    import sqlite3
    from datetime import datetime
    from collections import defaultdict

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    # 🔥 INVESTIMENTOS
    cursor.execute(
        "SELECT * FROM aplicacoes WHERE usuario_id = ?",
        (usuario_id,)
    )
    investimentos = cursor.fetchall()

    total_aplicado = sum(
        (i[3] or 0) + (i[4] or 0) - (i[5] or 0)
        for i in investimentos
    )

    # 🔥 LIVRO CAIXA
    cursor.execute(
        "SELECT * FROM lancamentos WHERE usuario_id = ?",
        (usuario_id,)
    )
    dados = cursor.fetchall()

    receitas_mes = 0
    despesas_mes = 0
    receitas_ano = 0
    despesas_ano = 0

    mes_atual = datetime.now().strftime("%Y-%m")
    ano_atual = datetime.now().strftime("%Y")

    for d in dados:
        data = d[1]
        valor = d[3] or 0
        tipo = d[4]

        if data.startswith(mes_atual):
            if tipo == "Receita":
                receitas_mes += valor
            elif tipo == "Despesa":
                despesas_mes += valor

        if data.startswith(ano_atual):
            if tipo == "Receita":
                receitas_ano += valor
            elif tipo == "Despesa":
                despesas_ano += valor

    saldo_mes = receitas_mes - despesas_mes
    saldo_ano = receitas_ano - despesas_ano

    conn.close()

    return render_template(
        'dashboard.html',
        receitas_mes=receitas_mes,
        despesas_mes=despesas_mes,
        saldo_mes=saldo_mes,
        receitas_ano=receitas_ano,
        despesas_ano=despesas_ano,
        saldo_ano=saldo_ano,
        total_aplicado=total_aplicado
    )

    # ========================
    # ALERTAS
    # ========================

    alerta_gasto = None

    if receitas_mes > 0 and despesas_mes > (receitas_mes * 0.75):
        alerta_gasto = "⚠️ Você gastou mais de 75% da sua receita no mês"

    alerta_meta = None

    if total_meta > 0:
        progresso_meta = (total_investido / total_meta) * 100

        if progresso_meta < 50:
            alerta_meta = "⚠️ Sua meta está abaixo do esperado"

    return render_template(
        'dashboard.html',
        receitas_mes=receitas_mes,
        despesas_mes=despesas_mes,
        saldo_mes=saldo_mes,
        receitas_ano=receitas_ano,
        despesas_ano=despesas_ano,
        saldo_ano=saldo_ano,
        total_aplicado=total_aplicado,
        labels=labels,
        receitas_lista=receitas_lista,
        despesas_lista=despesas_lista,
        saldo_acumulado_lista=saldo_acumulado_lista,
        labels_invest=labels_invest,
        aplicacao_lista=aplicacao_lista,
        rendimento_lista=rendimento_lista,
        resgate_lista=resgate_lista,
        saldo_mes_lista=saldo_mes_lista,
        saldo_acumulado_invest_lista=saldo_acumulado_invest_lista,
        alerta_gasto=alerta_gasto,
        alerta_meta=alerta_meta
    )
    
# ====== CAD USUARIOS

from werkzeug.security import generate_password_hash

@app.route('/salvar-usuario', methods=['POST'])
def salvar_usuario():

    if not session.get('logado'):
        return redirect('/')

    # 🔒 só admin pode salvar
    if not session.get('admin'):
        return redirect('/dashboard')

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario = request.form['usuario']
    senha = request.form['senha']

    from werkzeug.security import generate_password_hash
    senha_hash = generate_password_hash(senha)

    try:
        cursor.execute("""
            INSERT INTO usuarios (usuario, senha)
            VALUES (?, ?)
        """, (usuario, senha_hash))

        conn.commit()

    except:
        conn.close()
        return render_template('cadastro.html', erro="Usuário já existe")

    conn.close()

    return redirect('/')


# ====== RESETAR SENHA (ADMIN)

@app.route('/resetar-senha/<int:id>')
def resetar_senha(id):

    if not session.get('logado'):
        return redirect('/')

    # 🔒 só admin pode
    if not session.get('admin'):
        return redirect('/dashboard')

    from werkzeug.security import generate_password_hash
    import sqlite3

    # 🔑 senha temporária
    senha_temp = "123456"

    senha_hash = generate_password_hash(senha_temp)

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE usuarios
        SET senha = ?, primeiro_acesso = 1
        WHERE id = ?
    """, (senha_hash, id))

    conn.commit()
    conn.close()

    return redirect('/cadastro-admin-987')

# ======================
# LIVRO CAIXA
# ======================
@app.route('/livrocaixa')
def livrocaixa():

    if not session.get('logado'):
        return redirect('/')
    if session.get('trocar_senha'):
        return redirect('/trocar-senha')

    import sqlite3
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()
    tipo = request.args.get('tipo')
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')

    from datetime import datetime

    mes_atual = datetime.now().strftime("%Y-%m")

    usuario_id = session.get('usuario_id')

    query = "SELECT * FROM lancamentos WHERE usuario_id = ?"
    params = [usuario_id]

    if not tipo and not data_inicio and not data_fim:
        query += " AND data LIKE ?"
        params.append(f"{mes_atual}%")

    if tipo:
        query += " AND tipo = ?"
        params.append(tipo)

    if data_inicio:
        query += " AND data >= ?"
        params.append(data_inicio)

    if data_fim:
        query += " AND data <= ?"
        params.append(data_fim)

    query += " ORDER BY data DESC"

    cursor.execute(query, params)
    dados = cursor.fetchall()

    receitas = sum(item[3] for item in dados if item[4] == 'Receita')
    despesas = sum(item[3] for item in dados if item[4] == 'Despesa')
    total = receitas - despesas

    conn.close()

    return render_template(
        'livrocaixa.html',
        dados=dados,
        total=total,
        receitas=receitas,
        despesas=despesas
    )

# ========================
# ADD LIVRO CAIXA
# ========================
@app.route('/add', methods=['POST'])
def add():
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')  # 🔥 NOVO

    pago = 1 if request.form.get('pago') == '1' else 0

    categoria = request.form.get("categoria")

    cursor.execute('''
        INSERT INTO lancamentos (data, descricao, valor, tipo, pago, usuario_id, categoria)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        request.form['data'],
        request.form['descricao'],
        float(request.form['valor']),
        request.form['tipo'],
        pago,
        usuario_id,
        categoria
    ))

    conn.commit()
    conn.close()

    return redirect('/livrocaixa')

# ============EDITAR livro caixa

@app.route('/editar/<int:id>')
def editar(id):
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')

    cursor.execute("""
        SELECT * FROM lancamentos 
        WHERE id = ? AND usuario_id = ?
    """, (id, usuario_id))
    dado = cursor.fetchone()

    conn.close()

    return render_template('edit.html', dado=dado)

# ===== SALVAR EDIÇÃO LIVRO CAIXA
@app.route('/atualizar/<int:id>', methods=['POST'])
def atualizar_lancamento(id):
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')  # 🔥 NOVO

    pago = 1 if request.form.get('pago') == '1' else 0

    cursor.execute("""
        UPDATE lancamentos
        SET data = ?, descricao = ?, valor = ?, tipo = ?, pago = ?
        WHERE id = ? AND usuario_id = ?
    """, (
        request.form['data'],
        request.form['descricao'],
        float(request.form['valor']),
        request.form['tipo'],
        pago,
        id,
        usuario_id
    ))

    conn.commit()
    conn.close()

    return redirect('/livrocaixa')
  
# ============EDITAR CARTAO
@app.route('/edit_cartao/<int:id>')
def edit_cartao(id):
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')

    cursor.execute("""
        SELECT * FROM cartao 
        WHERE id = ? AND usuario_id = ?
    """, (id, usuario_id))
    dado = cursor.fetchone()

    cursor.execute("""
        SELECT nome_cartao 
        FROM cartoes 
        WHERE usuario_id = ?
    """, (usuario_id,))
    cartoes = cursor.fetchall()

    conn.close()

    if not dado:
        return redirect('/cartao')

    return render_template('edit_cartao.html', dado=dado, cartoes=cartoes)

# ========================
# CARTÃO LISTAR
# ========================
@app.route('/cartao')
def cartao():

    if not session.get('logado'):
        return redirect('/')
    if session.get('trocar_senha'):
        return redirect('/trocar-senha')
    
    usuario_id = session.get('usuario_id')

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    # ========================
    # FILTROS (IGUAL LIVRO CAIXA)
    # ========================
    mes = request.args.get('mes')
    ano = request.args.get('ano')

    from datetime import datetime

    mes_atual = datetime.now().month
    ano_atual = datetime.now().year

    filtro_mes = int(mes) if mes else mes_atual
    filtro_ano = int(ano) if ano else ano_atual

    # ========================
    # DADOS PRINCIPAIS
    # ========================
    cursor.execute(
        "SELECT * FROM cartao WHERE usuario_id = ? ORDER BY data_compra DESC",
        (usuario_id,)
    )
    dados = cursor.fetchall()

    # CARTÕES
    cursor.execute(
        "SELECT * FROM cartoes WHERE usuario_id = ?",
        (usuario_id,)
    )
    cartoes = cursor.fetchall()

    total_compras = sum(item[2] for item in dados)

    # ========================
    # TOTAL PAGO
    # ========================
    cursor.execute("""
        SELECT SUM(valor)
        FROM cartao_parcelas
        WHERE paga = 1 AND usuario_id = ?
    """, (usuario_id,))
    total_pago = cursor.fetchone()[0] or 0

    # ========================
    # LIMITE TOTAL
    # ========================
    cursor.execute("""
        SELECT SUM(limite) 
        FROM cartoes
        WHERE usuario_id = ?
    """, (usuario_id,))
    limite_total = cursor.fetchone()[0] or 0

    # ========================
    # GASTOS POR CARTÃO (continua igual por enquanto)
    # ========================
    cursor.execute("""
        SELECT nome_cartao, SUM(valor_total)
        FROM cartao
        WHERE usuario_id = ?
        GROUP BY nome_cartao
    """, (usuario_id,))
    gastos = cursor.fetchall()

    # ========================
    # FATURA CORRETA (BASEADA EM PARCELAS)
    # ========================
    cursor.execute("""
        SELECT c.nome_cartao, cp.data_parcela, cp.valor
        FROM cartao_parcelas cp
        JOIN cartao c ON c.id = cp.id_cartao
        WHERE cp.usuario_id = ?
    """, (usuario_id,))

    dados_fatura = cursor.fetchall()

    fatura_por_cartao = {}

    for nome, data_parcela, valor in dados_fatura:

        if not data_parcela:
            continue

        try:
            data = datetime.strptime(data_parcela, "%Y-%m-%d")
        except:
            continue

        if data.month == filtro_mes and data.year == filtro_ano:
            fatura_por_cartao[nome] = fatura_por_cartao.get(nome, 0) + valor

    # ========================
    # GASTOS DICT
    # ========================
    gastos_dict = {g[0]: g[1] for g in gastos}

    # ========================
    # LIMITE
    # ========================
    limite_liberado = limite_total - total_compras + total_pago

    conn.close()

    return render_template(
        'cartao.html',
        dados=dados,
        cartoes=cartoes,
        gastos_dict=gastos_dict,
        total_compras=total_compras,
        total_parcelado=0,
        total_mes=0,
        fatura={},
        limite_total=limite_total,
        limite_liberado=limite_liberado,
        total_pago=total_pago,
        fatura_por_cartao=fatura_por_cartao
    )

# ========================
# CARTÃO ADD
# ========================
@app.route('/add_cartao', methods=['POST'])
def add_cartao():
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')

    data = request.form['data_compra']
    valor_total = float(request.form['valor_total']) if request.form['valor_total'] else 0
    parcelas = int(request.form['parcelas']) if request.form['parcelas'] else 0
    descricao = request.form['descricao']
    cartao = request.form['nome_cartao']

    # 🔥 BUSCAR DIA DE FECHAMENTO DO CARTÃO
    cursor.execute("""
        SELECT dia_fechamento_fatura 
        FROM cartoes 
        WHERE nome_cartao = ? AND usuario_id = ?
    """, (cartao, usuario_id))

    resultado = cursor.fetchone()

    dia_fechamento = resultado[0] if resultado else 1  # segurança

    # 🔥 CALCULAR FATURA
    fatura = calcular_fatura(data, dia_fechamento)

    cursor.execute("""
        INSERT INTO cartao 
        (data_compra, valor_total, parcelas, descricao, nome_cartao, usuario_id, fatura)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (data, valor_total, parcelas, descricao, cartao, usuario_id, fatura))

    # 🔥 pega id da compra
    compra_id = cursor.lastrowid

    # 🔥 criar parcelas (SEMPRE, até para 1x)

    from datetime import datetime
    from dateutil.relativedelta import relativedelta

    # buscar fechamento do cartão
    cursor.execute("""
        SELECT dia_fechamento_fatura 
        FROM cartoes 
        WHERE nome_cartao = ? AND usuario_id = ?
    """, (cartao, usuario_id))

    resultado = cursor.fetchone()
    dia_fechamento = int(resultado[0]) if resultado else 10

    data_base = datetime.strptime(data, "%Y-%m-%d")

    # regra do fechamento
    if data_base.day <= dia_fechamento:
        inicio = data_base + relativedelta(months=1)
    else:
        inicio = data_base + relativedelta(months=2)

    parcelas = int(parcelas) if parcelas else 1
    valor_parcela = float(valor_total) / parcelas

    for i in range(parcelas):
        data_parcela = inicio + relativedelta(months=i)

        cursor.execute("""
            INSERT INTO cartao_parcelas 
            (id_cartao, data_parcela, valor, num_parcela, paga, usuario_id)
            VALUES (?, ?, ?, ?, 0, ?)
        """, (
            compra_id,
            data_parcela.strftime("%Y-%m-%d"),
            valor_parcela,
            i + 1,
            usuario_id
        ))

    # 🔥 salva tudo
    conn.commit()
    conn.close()

    return redirect('/cartao')

# ========================
# PARCELAS - ABRIR
# ========================
@app.route('/parcelas/<int:id>')
def parcelas(id):
    import sqlite3
    from datetime import datetime

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')

    # 🔒 compra protegida
    cursor.execute("""
        SELECT * FROM cartao 
        WHERE id = ? AND usuario_id = ?
    """, (id, usuario_id))
    compra = cursor.fetchone()

    if not compra:
        conn.close()
        return redirect('/cartao')

    # 🔒 parcelas protegidas
    cursor.execute("""
        SELECT id, data_parcela, valor, num_parcela, paga
        FROM cartao_parcelas
        WHERE id_cartao = ? AND usuario_id = ?
        ORDER BY num_parcela
    """, (id, usuario_id))
    
    parcelas = cursor.fetchall()

    # totais
    total_pago = sum(p[2] for p in parcelas if p[4] == 1)
    total_pendente = sum(p[2] for p in parcelas if p[4] == 0)
    total_compra = total_pago + total_pendente

    # fatura por mês
    fatura = {}
    for p in parcelas:
        data = p[1]
        mes = data[:7]
        valor = float(p[2])

        if mes not in fatura:
            fatura[mes] = 0

        fatura[mes] += valor

    # fatura atual
    mes_atual = datetime.now().strftime("%Y-%m")
    fatura_atual = fatura.get(mes_atual, 0)

    mes_atual_num = int(mes_atual.split("-")[1])
    ano_atual = mes_atual.split("-")[0]

    meses = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
             "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]

    mes_nome = meses[mes_atual_num - 1]

    from collections import defaultdict

    faturas = defaultdict(float)

    for p in parcelas:
        data = datetime.strptime(p[1], "%Y-%m-%d")
        chave = f"{data.month:02d}/{data.year}"
        faturas[chave] += p[2]

    faturas = dict(sorted(faturas.items()))

    conn.close()

    return render_template(
        'parcelas.html',
        compra=compra,
        parcelas=parcelas,
        total_pago=total_pago,
        total_pendente=total_pendente,
        total_compra=total_compra,
        fatura=fatura,
        fatura_atual=fatura_atual,
        mes_nome=mes_nome,
        ano_atual=ano_atual,
        faturas=faturas
    )

@app.route('/add_parcela/<int:id>', methods=['POST'])
def add_parcela(id):
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')  # 🔥 NOVO

    data = request.form['data']
    valor = float(request.form['valor'])
    num = int(request.form['num'])
    paga = 1 if request.form.get('paga') == 'Sim' else 0

    cursor.execute("""
        INSERT INTO cartao_parcelas 
        (id_cartao, data_parcela, valor, num_parcela, paga, usuario_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (id, data, valor, num, paga, usuario_id))

    conn.commit()
    conn.close()

    return redirect(f'/parcelas/{id}')
    return redirect(f'/parcelas/{id}')

# ===============MARCAR PCL PAGA
@app.route('/pagar_parcela/<int:id>/<int:id_cartao>')
def pagar_parcela(id, id_cartao):
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')  # 🔥 NOVO

    cursor.execute("""
        UPDATE cartao_parcelas
        SET paga = 1
        WHERE id = ? AND usuario_id = ?
    """, (id, usuario_id))

    conn.commit()
    conn.close()

    return redirect(f'/parcelas/{id_cartao}')

# =============== DESFAZER PAGAMENTO
@app.route('/desfazer_parcela/<int:id>/<int:id_cartao>')
def desfazer_parcela(id, id_cartao):
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')  # 🔥 NOVO

    cursor.execute("""
        UPDATE cartao_parcelas
        SET paga = 0
        WHERE id = ? AND usuario_id = ?
    """, (id, usuario_id))

    conn.commit()
    conn.close()

    return redirect(f'/parcelas/{id_cartao}')

# ================EXLUIR PARCELA

@app.route('/excluir_parcela/<int:id>/<int:id_cartao>')
def excluir_parcela(id, id_cartao):
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')  # 🔥 NOVO

    cursor.execute("""
        DELETE FROM cartao_parcelas
        WHERE id = ? AND usuario_id = ?
    """, (id, usuario_id))

    conn.commit()
    conn.close()

    return redirect(f'/parcelas/{id_cartao}')


# ======= ROTA PARA CADASTRAR CARTOES
@app.route('/registrar_cartoes')
def registrar_cartoes():
    if not session.get('logado'):
        return redirect('/')
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')  # 🔥 NOVO

    cursor.execute("""
        SELECT * FROM cartoes
        WHERE usuario_id = ?
    """, (usuario_id,))
    cartoes = cursor.fetchall()

    conn.close()

    return render_template('registrar_cartoes.html', cartoes=cartoes)

# ====== SALVAR CARTAO CADASTRADO

@app.route('/salvar-cartao', methods=['POST'])
def salvar_cartao():
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')  # 🔥 NOVO

    nome = request.form['nome_cartao']
    limite = float(request.form['limite'])
    fechamento = request.form['fechamento']

    cursor.execute("""
        INSERT INTO cartoes (nome_cartao, limite, usuario_id, dia_fechamento_fatura)
        VALUES (?, ?, ?, ?)
    """, (nome, limite, usuario_id, fechamento))

    conn.commit()
    conn.close()

    return redirect('/cartao')

# ====== EXCLUIR CARTAO

@app.route('/excluir-cartao/<int:id>')
def excluir_cartao(id):
    import sqlite3
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')  # 🔥 NOVO

    cursor.execute("""
        DELETE FROM cartoes
        WHERE id = ? AND usuario_id = ?
    """, (id, usuario_id))

    conn.commit()
    conn.close()

    return redirect('/cartao')

# ========================
# EDITAR CARTÃO
# ========================
@app.route('/editar_cartao/<int:id>')
def editar_cartao(id):

    if not session.get('logado'):
        return redirect('/')

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')

    cursor.execute("""
        SELECT * FROM cartoes
        WHERE id = ? AND usuario_id = ?
    """, (id, usuario_id))

    cartao = cursor.fetchone()

    conn.close()

    if not cartao:
        return redirect('/cartao')

    return render_template('editar_cartao.html', cartao=cartao)


# ========================
# SALVAR EDIÇÃO DO CARTÃO
# ========================
@app.route('/atualizar_cartao_config/<int:id>', methods=['POST'])
def atualizar_cartao_config(id):

    if not session.get('logado'):
        return redirect('/')

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')

    nome = request.form.get('nome_cartao')
    limite = float(request.form.get('limite'))
    fechamento = int(request.form.get('fechamento'))

    cursor.execute("""
        UPDATE cartoes
        SET nome_cartao = ?, limite = ?, dia_fechamento_fatura = ?
        WHERE id = ? AND usuario_id = ?
    """, (nome, limite, fechamento, id, usuario_id))

    conn.commit()
    conn.close()

    return redirect('/cartao')


# ======ATUALIZAR CARTÃO

@app.route('/atualizar_cartao/<int:id>', methods=['POST'])
def atualizar_cartao(id):
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')  # 🔥 NOVO

    cursor.execute("""
        UPDATE cartao
        SET data_compra = ?, valor_total = ?, parcelas = ?, descricao = ?, nome_cartao = ?
        WHERE id = ? AND usuario_id = ?
    """, (
        request.form['data_compra'],
        float(request.form['valor_total']),
        int(request.form['parcelas']),
        request.form['descricao'],
        request.form['nome_cartao'],
        id,
        usuario_id
    ))

    conn.commit()
    conn.close()

    return redirect('/cartao')

# =======EXCLUIR COMPRA CARTAO
@app.route('/delete_cartao/<int:id>', methods=['POST'])
def delete_cartao(id):
    import sqlite3    

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')

    # 🔥 1. apagar parcelas vinculadas
    cursor.execute("""
        DELETE FROM cartao_parcelas
        WHERE id_cartao = ? AND usuario_id = ?
    """, (id, usuario_id))

    # 🔥 2. apagar a compra
    cursor.execute("""
        DELETE FROM cartao
        WHERE id = ? AND usuario_id = ?
    """, (id, usuario_id))

    conn.commit()
    conn.close()

    return redirect('/cartao')

#=======CORRIGIR CARTOES
@app.route('/corrigir-cartoes')
def corrigir_cartoes():
    import sqlite3
    
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')  # 🔥 NOVO

    cursor.execute("""
        UPDATE cartao
        SET nome_cartao = 'Caixa Visa Gold'
        WHERE nome_cartao IS NULL AND usuario_id = ?
    """, (usuario_id,))

    conn.commit()
    conn.close()

    return "Cartões corrigidos!"

@app.route("/investimento")
def investimento():
    if not session.get('logado'):
        return redirect('/')
    if session.get('trocar_senha'):
        return redirect('/trocar-senha')

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')

    cursor.execute("""
        SELECT data, descricao, valor
        FROM lancamentos
        WHERE usuario_id = ?
        AND categoria = 'investimento'
        ORDER BY data DESC
    """, (usuario_id,))

    investimentos = cursor.fetchall()

    total_aplicado = sum(i[2] or 0 for i in investimentos)

    conn.close()

    return render_template(
        "investimento.html",
        investimentos=investimentos,
        total_aplicado=total_aplicado,
        total_rendimento=0,
        total_resgate=0,
        saldo=total_aplicado
    )

# ==========DASHBOARD_SIMPLES

@app.route('/dashboard_simples')
def dashboard_simples():
    if not session.get('logado'):
        return redirect('/')
    
    from datetime import datetime

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')

    # ========================
    # 🔥 INVESTIMENTOS
    # ========================
    cursor.execute(
        "SELECT * FROM aplicacoes WHERE usuario_id = ?",
        (usuario_id,)
    )
    investimentos = cursor.fetchall()

    total_aplicado = sum(i[3] or 0 for i in investimentos)

    # ========================
    # 🔥 LIVRO CAIXA
    # ========================
    cursor.execute(
        "SELECT * FROM lancamentos WHERE usuario_id = ?",
        (usuario_id,)
    )
    dados = cursor.fetchall()

    # mês atual
    mes_atual = datetime.now().strftime("%Y-%m")

    receitas_mes = 0
    despesas_mes = 0

    for d in dados:
        data = d[1]
        valor = d[3]
        tipo = d[4]

        if data.startswith(mes_atual):
            if tipo == "Receita":
                receitas_mes += valor
            elif tipo == "Despesa":
                despesas_mes += valor

    saldo_mes = receitas_mes - despesas_mes

    conn.close()

    return render_template(
        "dashboard.html",
        total_aplicado=total_aplicado,
        receitas_mes=receitas_mes,
        despesas_mes=despesas_mes,
        saldo_mes=saldo_mes
    )

# ==============EXCLUIR LANÇAMENTO

@app.route('/excluir-lancamento/<int:id>', methods=['POST'])
def excluir_lancamento(id):
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')

    cursor.execute("""
        DELETE FROM lancamentos
        WHERE id = ? AND usuario_id = ?
    """, (id, usuario_id))

    conn.commit()
    conn.close()

    return redirect('/livrocaixa')


# ======= ROTA META

@app.route("/meta")
def meta():
    if not session.get('logado'):
        return redirect('/')
    if session.get('trocar_senha'):
        return redirect('/trocar-senha')

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')

    # 🔥 BUSCAR METAS
    cursor.execute(
        "SELECT * FROM metas WHERE usuario_id = ?",
        (usuario_id,)
    )
    metas = cursor.fetchall()

    # 🔥 TOTAL DAS METAS (objetivo)
    total_meta = sum(m[2] or 0 for m in metas)

    # =========================
    # 🔥 INVESTIMENTOS
    # =========================
    cursor.execute("""
        SELECT valor, tipo
        FROM lancamentos
        WHERE usuario_id = ?
        AND categoria = 'investimento'
    """, (usuario_id,))

    dados_inv = cursor.fetchall()

    total_investido = 0

    for valor, tipo in dados_inv:
        if tipo == "Despesa":
            total_investido += valor or 0
        elif tipo == "Receita":
            total_investido -= valor or 0

    # =========================
    # 🔥 META (DINHEIRO GUARDADO)
    # =========================
    cursor.execute("""
        SELECT valor, tipo
        FROM lancamentos
        WHERE usuario_id = ?
        AND categoria = 'meta'
    """, (usuario_id,))

    dados_meta = cursor.fetchall()

    total_guardado_meta = 0

    for valor, tipo in dados_meta:
        if tipo == "Despesa":
            total_guardado_meta += valor or 0
        elif tipo == "Receita":
            total_guardado_meta -= valor or 0

    # =========================
    # 🔥 TOTAL GERAL (META + INVESTIMENTO)
    # =========================
    total_geral = total_investido + total_guardado_meta

    # 🔥 FALTA
    falta = total_meta - total_geral

    conn.close()

    return render_template(
        "meta.html",
        metas=metas,
        total_meta=total_meta,
        total_investido=total_geral,  # 👈 agora inclui tudo
        total_investimentos=total_investido,      # 👈 NOVO
        total_guardado_meta=total_guardado_meta,  # 👈 NOVO
        falta=falta
    )


# ====== SALVAR META

@app.route('/salvar-meta', methods=['POST'])
def salvar_meta():
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')

    nome = request.form.get('nome')
    data_meta = request.form.get('data_meta')
    valor_total = request.form.get('valor_total')
    valor_atual = request.form.get('valor_atual') or None

    cursor.execute("""
        INSERT INTO metas (nome, valor_total, valor_atual, data_meta, usuario_id)
        VALUES (?, ?, ?, ?, ?)
    """, (nome, valor_total, valor_atual, data_meta, usuario_id))

    conn.commit()
    conn.close()

    return redirect('/meta')


# ====== EXCLUIR META

@app.route('/excluir-meta/<int:id>')
def excluir_meta(id):
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')

    cursor.execute("""
        DELETE FROM metas 
        WHERE id = ? AND usuario_id = ?
    """, (id, usuario_id))

    conn.commit()
    conn.close()

    return redirect('/meta')

# ======== ADD VALOR META

@app.route('/adicionar-valor-meta', methods=['POST'])
def adicionar_valor_meta():
    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    usuario_id = session.get('usuario_id')  # 🔥 NOVO

    id_meta = request.form.get('id')
    valor = float(request.form.get('valor') or 0)

    # 🔍 buscar valor atual e total (PROTEGIDO)
    cursor.execute("""
        SELECT valor_atual, valor_total 
        FROM metas 
        WHERE id = ? AND usuario_id = ?
    """, (id_meta, usuario_id))

    resultado = cursor.fetchone()

    # 🔒 segurança extra
    if not resultado:
        conn.close()
        return redirect('/meta')

    atual = resultado[0] or 0
    total = resultado[1] or 0

    novo_valor = atual + valor

    # 🔒 trava no limite
    if novo_valor > total:
        novo_valor = total

    # 🔥 update protegido
    cursor.execute("""
        UPDATE metas
        SET valor_atual = ?
        WHERE id = ? AND usuario_id = ?
    """, (novo_valor, id_meta, usuario_id))

    conn.commit()
    conn.close()

    return redirect('/meta')
    return redirect('/meta')

# ========== importar excel

@app.route('/import_excel', methods=['POST'])
def import_excel():
    import sqlite3
    import openpyxl

    usuario_id = session.get('usuario_id')  # 🔥 ESSENCIAL

    arquivo = request.files.get('arquivo')
    origem = request.form.get("origem")

    if not arquivo:
        return "Nenhum arquivo enviado"

    wb = openpyxl.load_workbook(arquivo)
    planilha = wb.active

    conn = sqlite3.connect("banco.db")
    cursor = conn.cursor()

    for linha in planilha.iter_rows(min_row=2, values_only=True):
        try:
            # 🔥 LIVRO CAIXA
            if origem == "livrocaixa":
                data = linha[0]
                descricao = linha[1]
                valor = linha[2]
                tipo = linha[3]
                pago = linha[4] if len(linha) > 4 else 0

                cursor.execute('''
                    INSERT INTO lancamentos 
                    (data, descricao, valor, tipo, pago, usuario_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    str(data),
                    descricao,
                    float(valor),
                    tipo,
                    int(pago) if pago else 0,
                    usuario_id
                ))

            # 🔥 CARTÃO
            elif origem == "cartao":
                data = linha[0]
                valor = linha[1]
                parcelas = linha[2]
                descricao = linha[3]
                nome_cartao = linha[4]

                cursor.execute('''
                    INSERT INTO cartao 
                    (data_compra, valor_total, parcelas, descricao, nome_cartao, usuario_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    str(data),
                    float(valor),
                    int(parcelas),
                    descricao,
                    nome_cartao,
                    usuario_id
                ))

        except Exception as e:
            print("Erro:", linha, e)

    conn.commit()
    conn.close()

    from flask import redirect, url_for

    return redirect(url_for(origem, sucesso=1))

# ====== AJUDA

@app.route('/ajuda')
def ajuda():
    return render_template('ajuda.html')

# ====== IMPORTAR
@app.route('/importar')
def importar():
    return render_template('importarBD.html')



# ========================
# RUN
# ========================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)