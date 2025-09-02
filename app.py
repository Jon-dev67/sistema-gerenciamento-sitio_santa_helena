import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
import requests
import urllib.parse
import json
import os
from io import BytesIO
from datetime import date, datetime, timedelta
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.express as px

# ===============================
# CONFIGURAÇÕES INICIAIS
# ===============================
st.set_page_config(page_title="🌱 Gerenciador Integrado de Produção", layout="wide")
plt.style.use("dark_background")
sns.set_theme(style="darkgrid")

# Constantes
DB_NAME = "dados_sitio.db"
CONFIG_FILE = "config.json"
API_KEY = "eef20bca4e6fb1ff14a81a3171de5cec"
CIDADE_PADRAO = "Londrina"

TIPOS_INSUMOS = [
    "Adubo Orgânico", "Adubo Químico", "Defensivo Agrícola", 
    "Semente", "Muda", "Fertilizante Foliar", 
    "Corretivo de Solo", "Insumo para Irrigação", "Outros"
]

UNIDADES = ["kg", "g", "L", "mL", "unidade", "saco", "caixa", "pacote"]
ESTUFAS = [f"Estufa {i}" for i in range(1, 31)]
CAMPOS = [f"Campo {i}" for i in range(1, 31)]
AREAS_PRODUCAO = ESTUFAS + CAMPOS

# ===============================
# BANCO DE DADOS
# ===============================
def criar_tabelas():
    """Cria todas as tabelas necessárias no banco de dados"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    tabelas = [
        """
        CREATE TABLE IF NOT EXISTS producao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT, area TEXT, cultura TEXT, caixas INTEGER,
            caixas_segunda INTEGER, temperatura REAL, umidade REAL,
            chuva REAL, observacao TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS insumos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT, area TEXT,
            cultura TEXT, tipo TEXT, quantidade REAL, unidade TEXT,
            custo_unitario REAL, custo_total REAL, fornecedor TEXT,
            lote TEXT, observacoes TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS custos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT, tipo TEXT,
            descricao TEXT, valor REAL, area TEXT, observacoes TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS fenologia_especies (
            id INTEGER PRIMARY KEY AUTOINCREMENT, especie TEXT UNIQUE,
            estagios TEXT
        )
        """
    ]
    
    for tabela in tabelas:
        cursor.execute(tabela)
    
    conn.commit()
    conn.close()

def inserir_tabela(nome_tabela, df):
    """Insere dados em uma tabela do banco"""
    conn = sqlite3.connect(DB_NAME)
    
    if nome_tabela == "producao":
        df = normalizar_colunas(df)
    
    df.to_sql(nome_tabela, conn, if_exists="append", index=False)
    conn.close()

def carregar_tabela(nome_tabela):
    """Carrega dados de uma tabela do banco"""
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql(f"SELECT * FROM {nome_tabela}", conn)
    conn.close()
    return df

def excluir_linha(nome_tabela, row_id):
    """Exclui uma linha específica do banco"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM {nome_tabela} WHERE id=?", (row_id,))
    conn.commit()
    conn.close()

def carregar_fenologia_especies():
    """Carrega os estágios fenológicos por espécie"""
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql("SELECT * FROM fenologia_especies", conn)
    conn.close()
    
    fenologia_dict = {}
    for _, row in df.iterrows():
        try:
            fenologia_dict[row['especie']] = json.loads(row['estagios'])
        except:
            fenologia_dict[row['especie']] = []
    
    return fenologia_dict

def salvar_fenologia_especie(especie, estagios):
    """Salva estágios fenológicos de uma espécie"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM fenologia_especies WHERE especie = ?", (especie,))
    existe = cursor.fetchone()
    
    if existe:
        cursor.execute("UPDATE fenologia_especies SET estagios = ? WHERE especie = ?", 
                      (json.dumps(estagios), especie))
    else:
        cursor.execute("INSERT INTO fenologia_especies (especie, estagios) VALUES (?, ?)", 
                      (especie, json.dumps(estagios)))
    
    conn.commit()
    conn.close()

# ===============================
# CONFIGURAÇÕES
# ===============================
def carregar_config():
    """Carrega as configurações do sistema"""
    if not os.path.exists(CONFIG_FILE):
        cfg = {
            "cidade": CIDADE_PADRAO,
            "fenologia_padrao": {
                "estagios": [
                    {"nome": "Germinação/Vegetativo", "dias": "0-30", "adubo": 2, "agua": 1.5},
                    {"nome": "Floração", "dias": "31-60", "adubo": 4, "agua": 2.0},
                    {"nome": "Frutificação", "dias": "61-90", "adubo": 3, "agua": 2.5},
                    {"nome": "Maturação", "dias": "91-120", "adubo": 1, "agua": 1.0}
                ]
            },
            "alerta_pct_segunda": 25.0,
            "alerta_prod_baixo_pct": 30.0,
            "preco_medio_caixa": 30.0,
            "custo_medio_insumos": {
                "Adubo Orgânico": 2.5, "Adubo Químico": 4.0, "Defensivo Agrícola": 35.0,
                "Semente": 0.5, "Muda": 1.2, "Fertilizante Foliar": 15.0, "Corretivo de Solo": 1.8
            }
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
        return cfg
    
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def salvar_config(cfg):
    """Salva as configurações do sistema"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)

# ===============================
# FUNÇÕES UTILITÁRIAS
# ===============================
def normalizar_colunas(df):
    """Normaliza os nomes das colunas do DataFrame"""
    df = df.copy()
    col_map = {
        "Estufa": "area", "Área": "area", "Produção": "caixas", 
        "Primeira": "caixas", "Segunda": "caixas_segunda", 
        "Qtd": "caixas", "Quantidade": "caixas", "Data": "data",
        "Observação": "observacao", "Observacoes": "observacao", "Obs": "observacao"
    }
    df.rename(columns={c: col_map.get(c, c) for c in df.columns}, inplace=True)
    
    if "data" in df.columns: 
        df["data"] = pd.to_datetime(df["data"], errors="coerce").dt.strftime('%Y-%m-%d')
    
    for col in ["caixas", "caixas_segunda", "temperatura", "umidade", "chuva", "observacao"]:
        if col not in df.columns: 
            df[col] = 0 if col != "observacao" else ""
    
    for col in ["area", "cultura"]:
        if col not in df.columns: 
            df[col] = ""
    
    return df

def buscar_clima(cidade):
    """Busca dados climáticos da API"""
    try:
        city_encoded = urllib.parse.quote(cidade)
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city_encoded}&appid={API_KEY}&units=metric&lang=pt_br"
        r = requests.get(url, timeout=10)
        data = r.json()
        
        if r.status_code != 200: 
            return None, None
        
        atual = {
            "temp": float(data["main"]["temp"]),
            "umidade": float(data["main"]["humidity"]),
            "chuva": float(data.get("rain", {}).get("1h", 0) or 0.0)
        }
        
        # Previsão
        url_forecast = f"https://api.openweathermap.org/data/2.5/forecast?q={city_encoded}&appid={API_KEY}&units=metric&lang=pt_br"
        forecast = requests.get(url_forecast).json()
        previsao = []
        
        if forecast.get("cod") == "200":
            for item in forecast["list"]:
                previsao.append({
                    "Data": item["dt_txt"], "Temp Real (°C)": item["main"]["temp"],
                    "Temp Média (°C)": (item["main"]["temp_min"] + item["main"]["temp_max"]) / 2,
                    "Temp Min (°C)": item["main"]["temp_min"], "Temp Max (°C)": item["main"]["temp_max"],
                    "Umidade (%)": item["main"]["humidity"]
                })
                
        return atual, pd.DataFrame(previsao)
    except:
        return None, None

def calcular_estagio_fenologico(data_plantio, especie=None):
    """Calcula o estágio fenológico com base na data de plantio"""
    if not data_plantio:
        return "Não especificado"
        
    try:
        dias = (datetime.now() - datetime.strptime(data_plantio, "%Y-%m-%d")).days
        estagios = config["fenologia_padrao"]["estagios"]
        
        if especie and especie in fenologia_especies:
            estagios = fenologia_especies[especie]
        
        for estagio in estagios:
            dias_range = estagio["dias"].split("-")
            if len(dias_range) == 2 and dias >= int(dias_range[0]) and dias <= int(dias_range[1]):
                return estagio["nome"]
                
        return "Colheita concluída"
    except:
        return "Data inválida"

def recomendar_adubacao(estagio, especie=None):
    """Retorna recomendação de adubação baseada no estágio fenológico"""
    estagios = config["fenologia_padrao"]["estagios"]
    if especie and especie in fenologia_especies:
        estagios = fenologia_especies[especie]
    
    for e in estagios:
        if e["nome"] == estagio:
            return f"Recomendado: {e['adubo']}kg/ha de adubo e {e['agua']}L/planta de água"
    
    return "Sem recomendação específica"

# ===============================
# DADOS AGRONÔMICOS
# ===============================
DADOS_AGRONOMICOS = {
    "Tomate": {
        "densidade_plantio": 15000, "espacamento": "50x30 cm", "producao_esperada": 2.5,
        "ciclo_dias": 90, "temp_ideal": [18, 28], "umidade_ideal": [60, 80], "ph_ideal": [5.5, 6.8],
        "adubacao_base": {"N": 120, "P": 80, "K": 150},
        "pragas_comuns": ["tuta-absoluta", "mosca-branca", "ácaros"],
        "doencas_comuns": ["requeima", "murcha-bacteriana", "oidio"]
    },
    "Pepino Japonês": {
        "densidade_plantio": 18000, "espacamento": "80x40 cm", "producao_esperada": 3.2,
        "ciclo_dias": 65, "temp_ideal": [20, 30], "umidade_ideal": [65, 80], "ph_ideal": [5.5, 6.5],
        "adubacao_base": {"N": 110, "P": 60, "K": 140},
        "pragas_comuns": ["mosca-branca", "ácaros", "vaquinha"],
        "doencas_comuns": ["oidio", "antracnose", "viruses"]
    },
    "Pepino Caipira": {
        "densidade_plantio": 15000, "espacamento": "100x50 cm", "producao_esperada": 2.8,
        "ciclo_dias": 70, "temp_ideal": [18, 28], "umidade_ideal": [60, 75], "ph_ideal": [5.8, 6.8],
        "adubacao_base": {"N": 100, "P": 50, "K": 120},
        "pragas_comuns": ["vaquinha", "broca", "ácaros"],
        "doencas_comuns": ["oidio", "mancha-angular", "viruses"]
    },
    "Abóbora Itália": {
        "densidade_plantio": 8000, "espacamento": "200x100 cm", "producao_esperada": 4.5,
        "ciclo_dias": 85, "temp_ideal": [20, 30], "umidade_ideal": [60, 75], "ph_ideal": [6.0, 7.0],
        "adubacao_base": {"N": 80, "P": 50, "K": 100},
        "pragas_comuns": ["vaquinha", "broca", "pulgão"],
        "doencas_comuns": ["oidio", "antracnose", "murcha"]
    },
    "Abóbora Menina": {
        "densidade_plantio": 6000, "espacamento": "250x120 cm", "producao_esperada": 6.0,
        "ciclo_dias": 95, "temp_ideal": [22, 32], "umidade_ideal": [65, 80], "ph_ideal": [6.0, 7.2],
        "adubacao_base": {"N": 70, "P": 45, "K": 90},
        "pragas_comuns": ["vaquinha", "broca", "pulgão"],
        "doencas_comuns": ["oidio", "antracnose", "murcha-bacteriana"]
    }
}

# ===============================
# FUNÇÕES DE RECOMENDAÇÃO
# ===============================
def calcular_producao_esperada(cultura, area_m2):
    """Calcula a produção esperada baseada em dados técnicos"""
    if cultura not in DADOS_AGRONOMICOS:
        return None
    
    dados = DADOS_AGRONOMICOS[cultura]
    plantas = (area_m2 * dados['densidade_plantio']) / 10000
    producao_kg = plantas * dados['producao_esperada']
    
    return {
        'plantas_estimadas': int(plantas),
        'producao_kg': round(producao_kg, 2),
        'producao_caixas': round(producao_kg / 20, 1),
        'ciclo_dias': dados['ciclo_dias']
    }

def gerar_recomendacoes_clima(cultura, dados_clima):
    """Gera recomendações baseadas nas condições climáticas"""
    if cultura not in DADOS_AGRONOMICOS:
        return []
    
    dados = DADOS_AGRONOMICOS[cultura]
    recomendacoes = []
    
    temp = dados_clima.get('temperatura', 25)
    if temp < dados['temp_ideal'][0]:
        recomendacoes.append(f"🌡️ Temperatura baixa ({temp}°C) - considerar aquecimento ou cobertura")
    elif temp > dados['temp_ideal'][1]:
        recomendacoes.append(f"🌡️ Temperatura alta ({temp}°C) - aumentar ventilação/sombreamento")
    
    umidade = dados_clima.get('umidade', 70)
    if umidade < dados['umidade_ideal'][0]:
        recomendacoes.append(f"💧 Umidade baixa ({umidade}%) - aumentar irrigação")
    elif umidade > dados['umidade_ideal'][1]:
        recomendacoes.append(f"💧 Umidade alta ({umidade}%) - risco de doenças, melhorar ventilação")
    
    return recomendacoes

def recomendar_adubacao_especifica(cultura, area_m2, estagio_fenologico):
    """Recomenda adubação específica baseada na cultura e estágio"""
    if cultura not in DADOS_AGRONOMICOS:
        return None
    
    dados = DADOS_AGRONOMICOS[cultura]
    area_ha = area_m2 / 10000
    
    fator_estagio = {
        "Germinação/Vegetativo": 0.6, "Floração": 1.0,
        "Frutificação": 0.8, "Maturação": 0.4
    }.get(estagio_fenologico, 1.0)
    
    recomendacao = {}
    for nutriente, quantidade in dados['adubacao_base'].items():
        recomendacao[nutriente] = round(quantidade * area_ha * fator_estagio, 2)
    
    return recomendacao

def verificar_alertas_sanitarios(cultura, dados_clima):
    """Verifica condições propícias para pragas e doenças"""
    if cultura not in DADOS_AGRONOMICOS:
        return []
    
    dados = DADOS_AGRONOMICOS[cultura]
    alertas = []
    
    if dados_clima.get('umidade', 70) > 80:
        alertas.append(f"⚠️ Condições favoráveis para doenças fúngicas em {cultura}")
        alertas.append(f"   Doenças comuns: {', '.join(dados['doencas_comuns'][:2])}")
    
    if dados_clima.get('temperatura', 25) > 28 and dados_clima.get('umidade', 70) > 70:
        alertas.append(f"⚠️ Condições ideais para pragas em {cultura}")
        alertas.append(f"   Pragas comuns: {', '.join(dados['pragas_comuns'][:2])}")
    
    return alertas

def calcular_otimizacao_espaco(estufa_area, cultura):
    """Calcula otimização de espaço para a cultura"""
    if cultura not in DADOS_AGRONOMICOS:
        return None
    
    dados = DADOS_AGRONOMICOS[cultura]
    plantas_possiveis = (estufa_area * dados['densidade_plantio']) / 10000
    
    return {
        'cultura': cultura, 'area_estufa_m2': estufa_area,
        'plantas_recomendadas': int(plantas_possiveis),
        'producao_estimada_kg': round(plantas_possiveis * dados['producao_esperada'], 2),
        'espacamento_recomendado': dados['espacamento'],
        'rendimento_por_m2': round((plantas_possiveis * dados['producao_esperada']) / estufa_area, 3)
    }

# ===============================
# MÓDULO AGRONÔMICO
# ===============================
def mostrar_modulo_agronomico():
    """Interface do módulo agronômico"""
    st.title("🌿 Recomendações Agronômicas Inteligentes")
    
    tab1, tab2, tab3, tab4 = st.tabs(["Calculadora de Produção", "Recomendações de Manejo", 
                                    "Alertas Sanitários", "Otimização de Espaço"])
    
    with tab1:
        st.header("📊 Calculadora de Produção Esperada")
        col1, col2 = st.columns(2)
        
        with col1:
            cultura = st.selectbox("Selecione a cultura:", list(DADOS_AGRONOMICOS.keys()))
            area_m2 = st.number_input("Área disponível (m²):", min_value=1.0, value=100.0)
        
        with col2:
            if cultura:
                dados = DADOS_AGRONOMICOS[cultura]
                st.info(f"""**Dados Técnicos da {cultura}:**
                - Densidade: {dados['densidade_plantio']} plantas/ha
                - Espaçamento: {dados['espacamento']}
                - Ciclo: {dados['ciclo_dias']} dias
                - Produção esperada: {dados['producao_esperada']} kg/planta""")
        
        if st.button("Calcular Produção Esperada"):
            resultado = calcular_producao_esperada(cultura, area_m2)
            if resultado:
                st.success(f"""**Resultado para {cultura} em {area_m2}m²:**
                - 👨‍🌾 Plantas estimadas: {resultado['plantas_estimadas']}
                - 📦 Produção estimada: {resultado['producao_kg']} kg ({resultado['producao_caixas']} caixas)
                - ⏰ Ciclo: {resultado['ciclo_dias']} dias""")
    
    with tab2:
        st.header("🌡️ Recomendações de Manejo")
        cultura = st.selectbox("Cultura para análise:", list(DADOS_AGRONOMICOS.keys()), key="cultura_manejo")
        
        col1, col2 = st.columns(2)
        with col1:
            temperatura = st.slider("Temperatura atual (°C):", 0.0, 40.0, 25.0)
            estagio = st.selectbox("Estágio fenológico:", ["Germinação/Vegetativo", "Floração", "Frutificação", "Maturação"])
        
        with col2:
            umidade = st.slider("Umidade relativa (%):", 0.0, 100.0, 70.0)
            area = st.number_input("Área (m²):", min_value=1.0, value=100.0, key="area_manejo")
        
        if st.button("Gerar Recomendações"):
            rec_clima = gerar_recomendacoes_clima(cultura, {'temperatura': temperatura, 'umidade': umidade})
            if rec_clima:
                st.info("**Recomendações Climáticas:**")
                for rec in rec_clima:
                    st.write(f"- {rec}")
            
            adubacao = recomendar_adubacao_especifica(cultura, area, estagio)
            if adubacao:
                st.success("**Recomendação de Adubação:**")
                st.write(f"- Nitrogênio (N): {adubacao['N']} kg/ha")
                st.write(f"- Fósforo (P): {adubacao['P']} kg/ha")
                st.write(f"- Potássio (K): {adubacao['K']} kg/ha")
    
    with tab3:
        st.header("⚠️ Alertas Sanitários")
        cultura = st.selectbox("Cultura para monitoramento:", list(DADOS_AGRONOMICOS.keys()), key="cultura_alerta")
        
        col1, col2 = st.columns(2)
        with col1:
            temp = st.slider("Temperatura (°C):", 0.0, 40.0, 25.0, key="temp_alerta")
        with col2:
            umid = st.slider("Umidade (%):", 0.0, 100.0, 70.0, key="umid_alerta")
        
        if st.button("Verificar Alertas"):
            alertas = verificar_alertas_sanitarios(cultura, {'temperatura': temp, 'umidade': umid})
            if alertas:
                st.error("**Alertas Sanitários:**")
                for alerta in alertas:
                    st.write(f"- {alerta}")
            else:
                st.success("✅ Condições dentro dos parâmetros normais")
    
    with tab4:
        st.header("📐 Otimização de Espaço")
        cultura = st.selectbox("Cultura para otimização:", list(DADOS_AGRONOMICOS.keys()), key="cultura_otimizacao")
        area_estufa = st.number_input("Área da estufa (m²):", min_value=1.0, value=200.0)
        
        if st.button("Calcular Otimização"):
            resultado = calcular_otimizacao_espaco(area_estufa, cultura)
            if resultado:
                st.success(f"""**Otimização para {cultura}:**
                - 🏭 Área disponível: {resultado['area_estufa_m2']} m²
                - 👨‍🌾 Plantas recomendadas: {resultado['plantas_recomendadas']}
                - 📦 Produção estimada: {resultado['producao_estimada_kg']} kg
                - 📏 Espaçamento: {resultado['espacamento_recomendado']}
                - 📊 Rendimento: {resultado['rendimento_por_m2']} kg/m²""")

def adicionar_recomendacoes_dashboard():
    """Adiciona cards de recomendação ao dashboard principal"""
    df_prod = carregar_tabela("producao")
    
    if not df_prod.empty:
        st.subheader("🌿 Recomendações Agronômicas")
        ultimo_registro = df_prod.iloc[-1]
        cultura = ultimo_registro['cultura']
        
        if cultura and cultura.strip() and cultura in DADOS_AGRONOMICOS:
            dados_clima = {
                'temperatura': ultimo_registro['temperatura'],
                'umidade': ultimo_registro['umidade']
            }
            
            recomendacoes = gerar_recomendacoes_clima(cultura, dados_clima)
            alertas = verificar_alertas_sanitarios(cultura, dados_clima)
            
            col1, col2 = st.columns(2)
            
            with col1:
                if recomendacoes:
                    st.info("**Recomendações Atuais:**")
                    for rec in recomendacoes[:3]:
                        st.write(f"- {rec}")
                else:
                    st.success("✅ Condições climáticas dentro do ideal")
            
            with col2:
                if alertas:
                    st.error("**Alertas Sanitários:**")
                    for alerta in alertas[:2]:
                        st.write(f"- {alerta}")
                else:
                    st.success("✅ Sem alertas sanitários")
        else:
            st.info("ℹ️ Selecione uma cultura válida para ver recomendações")

# ===============================
# PÁGINAS PRINCIPAIS
# ===============================
def pagina_dashboard():
    """Página principal do dashboard"""
    st.title("🌱 Dashboard de Produção")
    
    df_prod = carregar_tabela("producao")
    df_ins = carregar_tabela("insumos")
    
    # KPIs principais
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        total_caixas = df_prod["caixas"].sum() if not df_prod.empty else 0
        st.metric("📦 Caixas 1ª Qualidade", f"{total_caixas:.0f}")
    
    with col2:
        total_segunda = df_prod["caixas_segunda"].sum() if not df_prod.empty else 0
        st.metric("🔄 Caixas 2ª Qualidade", f"{total_segunda:.0f}")
    
    with col3:
        total_insumos = df_ins["custo_total"].sum() if not df_ins.empty else 0
        st.metric("💰 Custo Insumos", f"R$ {total_insumos:,.2f}")
    
    with col4:
        receita_estimada = total_caixas * config.get("preco_medio_caixa", 30)
        lucro_estimado = receita_estimada - total_insumos if receita_estimada else 0
        st.metric("💵 Lucro Estimado", f"R$ {lucro_estimado:,.2f}")
    
    # Alertas
    st.subheader("⚠️ Alertas e Recomendações")
    
    if not df_prod.empty:
        df_prod["pct_segunda"] = np.where(
            (df_prod["caixas"] + df_prod["caixas_segunda"]) > 0,
            df_prod["caixas_segunda"] / (df_prod["caixas"] + df_prod["caixas_segunda"]) * 100, 0
        )
        
        alta_segunda = df_prod[df_prod["pct_segunda"] > config.get("alerta_pct_segunda", 25)]
        if not alta_segunda.empty:
            st.warning(f"Alto percentual de 2ª qualidade ({alta_segunda['pct_segunda'].mean():.1f}%)")
        
        ultimo_clima = df_prod.iloc[-1]
        if ultimo_clima is not None and ultimo_clima["umidade"] > 85:
            st.error("Alerta: Umidade muito alta, risco de doenças fúngicas!")
        if ultimo_clima is not None and ultimo_clima["temperatura"] < 10:
            st.error("Alerta: Temperatura muito baixa, risco de danos às plantas!")
    
    # Gráficos resumos
    st.subheader("📊 Visão Geral")
    
    if not df_prod.empty:
        col1, col2 = st.columns(2)
        
        with col1:
            if "area" in df_prod.columns:
                prod_area = df_prod.groupby("area")[["caixas", "caixas_segunda"]].sum().reset_index()
                if not prod_area.empty:
                    fig = px.bar(prod_area, x="area", y=["caixas", "caixas_segunda"], 
                                title="Produção por Área", barmode="group")
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("ℹ️ Dados de área não disponíveis para análise")
        
        with col2:
            if "data" in df_prod.columns:
                df_prod["data"] = pd.to_datetime(df_prod["data"])
                prod_temporal = df_prod.groupby("data")[["caixas", "caixas_segunda"]].sum().reset_index()
                if not prod_temporal.empty:
                    fig = px.line(prod_temporal, x="data", y=["caixas", "caixas_segunda"], 
                                 title="Evolução da Produção", markers=True)
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("ℹ️ Dados de data não disponíveis para análise")
    
    if not df_ins.empty:
        col1, col2 = st.columns(2)
        
        with col1:
            custos_tipo = df_ins.groupby("tipo")["custo_total"].sum().reset_index()
            if not custos_tipo.empty:
                fig = px.pie(custos_tipo, values="custo_total", names="tipo", 
                            title="Distribuição de Custos por Tipo")
                st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            custos_cultura = df_ins.groupby("cultura")["custo_total"].sum().reset_index()
            if not custos_cultura.empty:
                fig = px.bar(custos_cultura, x="cultura", y="custo_total", 
                            title="Custos por Cultura")
                st.plotly_chart(fig, use_container_width=True)

    adicionar_recomendacoes_dashboard()

def pagina_cadastro_producao():
    """Página de cadastro de produção"""
    st.title("📝 Cadastro de Produção")
    df = carregar_tabela("producao")
    cidade = st.sidebar.text_input("🌍 Cidade para clima", value=config.get("cidade", CIDADE_PADRAO))

    with st.form("form_cadastro_producao", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1: 
            data_val = st.date_input("Data", value=date.today())
            area = st.selectbox("Área/Estufa", options=AREAS_PRODUCAO)
        with col2: 
            cultura = st.text_input("Cultura")
            caixas = st.number_input("Caixas (1ª)", min_value=0, step=1)
        with col3: 
            caixas2 = st.number_input("Caixas (2ª)", min_value=0, step=1)
            observacao = st.text_input("Observações")
        
        st.markdown("#### Clima")
        clima_atual, previsao = buscar_clima(cidade)
        
        if clima_atual: 
            temperatura, umidade, chuva = clima_atual["temp"], clima_atual["umidade"], clima_atual["chuva"]
            st.info(f"🌡️ {temperatura:.1f}°C | 💧 {umidade:.0f}% | 🌧️ {chuva:.1f}mm (atual)")
        else: 
            c1, c2, c3 = st.columns(3)
            with c1: temperatura = st.number_input("Temperatura (°C)", value=25.0)
            with c2: umidade = st.number_input("Umidade (%)", value=65.0)
            with c3: chuva = st.number_input("Chuva (mm)", value=0.0)

        enviado = st.form_submit_button("Salvar Registro ✅")
        if enviado:
            novo = pd.DataFrame([{
                "data": str(data_val), "area": area, "cultura": cultura.strip(),
                "caixas": int(caixas), "caixas_segunda": int(caixas2),
                "temperatura": float(temperatura), "umidade": float(umidade),
                "chuva": float(chuva), "observacao": observacao
            }])
            inserir_tabela("producao", novo)
            st.success("Registro salvo com sucesso!")

    if not df.empty:
        st.markdown("### 📋 Registros recentes")
        st.dataframe(df.sort_values("data", ascending=False).head(15), use_container_width=True)
        
        st.markdown("### 🗑️ Excluir Registros")
        col1, col2 = st.columns([3, 1])
        with col1:
            ids = st.multiselect("Selecione ID(s) para excluir", df["id"].tolist())
        with col2:
            if st.button("Excluir selecionados", type="secondary"):
                if ids:
                    for i in ids: 
                        excluir_linha("producao", i)
                    st.success("✅ Linhas excluídas!")
                    st.rerun()
                else:
                    st.warning("Selecione pelo menos um ID para excluir")

    st.subheader("📂 Importar Excel")
    uploaded_file = st.file_uploader("Envie planilha Excel (Produção)", type=["xlsx"])
    if uploaded_file:
        df_excel = pd.read_excel(uploaded_file)
        df_excel = normalizar_colunas(df_excel)
        inserir_tabela("producao", df_excel)
        st.success("✅ Dados importados do Excel!")
        st.rerun()

def pagina_cadastro_insumos():
    """Página de cadastro de insumos"""
    st.title("📦 Cadastro de Insumos")
    df_ins = carregar_tabela("insumos")
    
    with st.form("form_insumos", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            data_i = st.date_input("Data", value=date.today())
            area_i = st.selectbox("Área/Estufa", options=AREAS_PRODUCAO)
            cultura_i = st.text_input("Cultura (opcional)")
            tipo_i = st.selectbox("Tipo de Insumo", TIPOS_INSUMOS)
            fornecedor_i = st.text_input("Fornecedor (opcional)")
            
        with col2:
            qtd_i = st.number_input("Quantidade", min_value=0.0, step=0.1)
            un_i = st.selectbox("Unidade", UNIDADES)
            custo_unit_i = st.number_input("Custo Unitário (R$)", min_value=0.0, step=0.01)
            custo_total_i = st.number_input("Custo Total (R$)", min_value=0.0, step=0.01, 
                                          value=0.0, help="Se não preenchido, será calculado automaticamente")
            lote_i = st.text_input("Nº Lote (opcional)")
            
        observacoes_i = st.text_area("Observações")
        
        if custo_unit_i > 0 and qtd_i > 0 and custo_total_i == 0:
            custo_total_i = custo_unit_i * qtd_i
            st.info(f"Custo total calculado: R$ {custo_total_i:.2f}")
            
        enviado_i = st.form_submit_button("Salvar Insumo ✅")
        if enviado_i:
            novo = pd.DataFrame([{
                "data": str(data_i), "area": area_i, "cultura": cultura_i,
                "tipo": tipo_i, "quantidade": qtd_i, "unidade": un_i,
                "custo_unitario": custo_unit_i, "custo_total": custo_total_i if custo_total_i > 0 else custo_unit_i * qtd_i,
                "fornecedor": fornecedor_i, "lote": lote_i, "observacoes": observacoes_i
            }])
            inserir_tabela("insumos", novo)
            st.success("Insumo salvo com sucesso!")

    if not df_ins.empty:
        st.subheader("📋 Histórico de Insumos")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            filtro_tipo = st.multiselect("Filtrar por tipo", options=df_ins["tipo"].unique())
        with col2:
            filtro_area = st.multiselect("Filtrar por área", options=df_ins["area"].unique())
        with col3:
            filtro_cultura = st.multiselect("Filtrar por cultura", options=df_ins["cultura"].unique())
        
        df_filtrado = df_ins.copy()
        if filtro_tipo: df_filtrado = df_filtrado[df_filtrado["tipo"].isin(filtro_tipo)]
        if filtro_area: df_filtrado = df_filtrado[df_filtrado["area"].isin(filtro_area)]
        if filtro_cultura: df_filtrado = df_filtrado[df_filtrado["cultura"].isin(filtro_cultura)]
            
        st.dataframe(df_filtrado.sort_values("data", ascending=False).head(20), use_container_width=True)
        
        st.subheader("📊 Estatísticas de Custos")
        if not df_filtrado.empty:
            total_custo = df_filtrado["custo_total"].sum()
            media_custo = df_filtrado["custo_total"].mean()
            st.write(f"**Total gasto:** R$ {total_custo:,.2f} | **Média por registro:** R$ {media_custo:,.2f}")
            
            df_filtrado["data"] = pd.to_datetime(df_filtrado["data"])
            custos_mensais = df_filtrado.groupby(df_filtrado["data"].dt.to_period("M"))["custo_total"].sum().reset_index()
            custos_mensais["data"] = custos_mensais["data"].astype(str)
            
            fig = px.bar(custos_mensais, x="data", y="custo_total", 
                        title="Evolução Mensal de Custos com Insumos")
            st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("### 🗑️ Excluir Insumos")
        col1, col2 = st.columns([3, 1])
        with col1:
            ids_insumos = st.multiselect("Selecione ID(s) de insumos para excluir", df_ins["id"].tolist())
        with col2:
            if st.button("Excluir insumos selecionados", type="secondary"):
                if ids_insumos:
                    for i in ids_insumos: 
                        excluir_linha("insumos", i)
                    st.success("✅ Insumos excluídos!")
                    st.rerun()
                else:
                    st.warning("Selecione pelo menos um ID para excluir")

    st.subheader("📂 Importar Excel (Insumos)")
    uploaded_file = st.file_uploader("Envie planilha Excel (Insumos)", type=["xlsx"], key="insumos_upload")
    if uploaded_file:
        df_excel = pd.read_excel(uploaded_file)
        df_excel.rename(columns=lambda x: x.lower(), inplace=True)
        inserir_tabela("insumos", df_excel)
        st.success("✅ Dados de insumos importados do Excel!")
        st.rerun()

def pagina_analise():
    """Página de análise de dados"""
    st.title("📊 Análise Avançada de Produção e Custos")
    
    df_prod = carregar_tabela("producao")
    df_ins = carregar_tabela("insumos")
    
    if df_prod.empty and df_ins.empty:
        st.warning("📭 Nenhum dado disponível para análise. Cadastre dados de produção e insumos primeiro.")
        st.stop()
    
    st.sidebar.subheader("🔍 Filtros de Análise")
    
    # Período temporal
    if not df_prod.empty:
        datas_disponiveis = pd.to_datetime(df_prod['data']).sort_values()
        min_date, max_date = datas_disponiveis.min(), datas_disponiveis.max()
    else:
        min_date, max_date = date.today() - timedelta(days=365), date.today()
    
    date_range = st.sidebar.date_input("📅 Período de análise", value=(min_date, max_date),
                                      min_value=min_date, max_value=max_date)
    
    start_date, end_date = date_range if len(date_range) == 2 else (min_date, max_date)
    
    # Filtros adicionais
    col1, col2 = st.sidebar.columns(2)
    
    with col1:
        areas_selecionadas = st.multiselect("🏭 Áreas", options=df_prod['area'].unique(), default=df_prod['area'].unique()) if not df_prod.empty else []
        tipos_selecionados = st.multiselect("📦 Tipos de Insumos", options=df_ins['tipo'].unique(), default=df_ins['tipo'].unique()) if not df_ins.empty else []
    
    with col2:
        culturas_selecionadas = st.multiselect("🌱 Culturas", options=df_prod['cultura'].unique(), default=df_prod['cultura'].unique()) if not df_prod.empty else []
    
    # Aplicar filtros
    if not df_prod.empty:
        df_prod['data'] = pd.to_datetime(df_prod['data'])
        df_prod_filtrado = df_prod[(df_prod['data'] >= pd.to_datetime(start_date)) & 
                                  (df_prod['data'] <= pd.to_datetime(end_date))]
        if areas_selecionadas: df_prod_filtrado = df_prod_filtrado[df_prod_filtrado['area'].isin(areas_selecionadas)]
        if culturas_selecionadas: df_prod_filtrado = df_prod_filtrado[df_prod_filtrado['cultura'].isin(culturas_selecionadas)]
    else:
        df_prod_filtrado = pd.DataFrame()
    
    if not df_ins.empty:
        df_ins['data'] = pd.to_datetime(df_ins['data'])
        df_ins_filtrado = df_ins[(df_ins['data'] >= pd.to_datetime(start_date)) & 
                                (df_ins['data'] <= pd.to_datetime(end_date))]
        if tipos_selecionados: df_ins_filtrado = df_ins_filtrado[df_ins_filtrado['tipo'].isin(tipos_selecionados)]
    else:
        df_ins_filtrado = pd.DataFrame()
    
    # Métricas de performance
    st.header("📈 Métricas de Performance")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        total_caixas = df_prod_filtrado['caixas'].sum() if not df_prod_filtrado.empty else 0
        st.metric("📦 Caixas 1ª Qualidade", f"{total_caixas:,.0f}")
    
    with col2:
        total_segunda = df_prod_filtrado['caixas_segunda'].sum() if not df_prod_filtrado.empty else 0
        pct_segunda = (total_segunda / (total_caixas + total_segunda) * 100) if (total_caixas + total_segunda) > 0 else 0
        st.metric("🔄 % 2ª Qualidade", f"{pct_segunda:.1f}%")
    
    with col3:
        custo_total = df_ins_filtrado['custo_total'].sum() if not df_ins_filtrado.empty else 0
        st.metric("💰 Custo Total", f"R$ {custo_total:,.2f}")
    
    with col4:
        receita_estimada = total_caixas * config.get('preco_medio_caixa', 30)
        lucro = receita_estimada - custo_total
        st.metric("💵 Lucro Estimado", f"R$ {lucro:,.2f}")
    
    # Análise de Produção
    if not df_prod_filtrado.empty:
        st.header("🌱 Análise de Produção")
        
        tab1, tab2, tab3, tab4 = st.tabs(["Visão Geral", "Por Cultura", "Por Área", "Tendências"])
        
        with tab1:
            col1, col2 = st.columns(2)
            
            with col1:
                prod_diaria = df_prod_filtrado.groupby('data')[['caixas', 'caixas_segunda']].sum().reset_index()
                fig = px.line(prod_diaria, x='data', y=['caixas', 'caixas_segunda'],
                             title='📅 Produção Diária', markers=True)
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                qualidade_data = pd.DataFrame({
                    'Categoria': ['1ª Qualidade', '2ª Qualidade'],
                    'Quantidade': [total_caixas, total_segunda]
                })
                fig = px.pie(qualidade_data, values='Quantidade', names='Categoria',
                            title='🎯 Distribuição por Qualidade')
                st.plotly_chart(fig, use_container_width=True)
        
        with tab2:
            prod_cultura = df_prod_filtrado.groupby('cultura')[['caixas', 'caixas_segunda']].sum().reset_index()
            prod_cultura['Total'] = prod_cultura['caixas'] + prod_cultura['caixas_segunda']
            prod_cultura['% 2ª'] = (prod_cultura['caixas_segunda'] / prod_cultura['Total'] * 100).round(1)
            
            col1, col2 = st.columns(2)
            
            with col1:
                fig = px.bar(prod_cultura, x='cultura', y=['caixas', 'caixas_segunda'],
                            title='🌿 Produção por Cultura', barmode='group')
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                fig = px.bar(prod_cultura, x='cultura', y='% 2ª',
                            title='📊 Percentual de 2ª por Cultura')
                st.plotly_chart(fig, use_container_width=True)
        
        with tab3:
            if 'area' in df_prod_filtrado.columns:
                prod_area = df_prod_filtrado.groupby('area')[['caixas', 'caixas_segunda']].sum().reset_index()
                prod_area['Produtividade'] = prod_area['caixas'] / len(df_prod_filtrado['data'].unique())
                
                col1, col2 = st.columns(2)
                
                with col1:
                    fig = px.bar(prod_area, x='area', y='caixas',
                                title='🏭 Produção Total por Área')
                    st.plotly_chart(fig, use_container_width=True)
                
                with col2:
                    fig = px.bar(prod_area, x='area', y='Produtividade',
                                title='⚡ Produtividade Média Diária por Área')
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("ℹ️ Dados de área não disponíveis para análise")
        
        with tab4:
            prod_mensal = df_prod_filtrado.copy()
            prod_mensal['mes'] = prod_mensal['data'].dt.to_period('M').astype(str)
            prod_mensal = prod_mensal.groupby('mes')[['caixas', 'caixas_segunda']].sum().reset_index()
            
            fig = px.line(prod_mensal, x='mes', y=['caixas', 'caixas_segunda'],
                         title='📈 Tendência Mensal de Produção', markers=True)
            st.plotly_chart(fig, use_container_width=True)
    
    # Análise de Custos
    if not df_ins_filtrado.empty:
        st.header("💰 Análise de Custos e Rentabilidade")
        
        tab1, tab2, tab3 = st.tabs(["Distribuição", "Evolução", "Rentabilidade"])
        
        with tab1:
            col1, col2 = st.columns(2)
            
            with col1:
                custos_tipo = df_ins_filtrado.groupby('tipo')['custo_total'].sum().reset_index()
                fig = px.pie(custos_tipo, values='custo_total', names='tipo',
                            title='📊 Distribuição de Custos por Tipo')
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                custos_cultura = df_ins_filtrado.groupby('cultura')['custo_total'].sum().reset_index()
                fig = px.bar(custos_cultura, x='cultura', y='custo_total',
                            title='🌱 Custos por Cultura')
                st.plotly_chart(fig, use_container_width=True)
        
        with tab2:
            custos_mensal = df_ins_filtrado.copy()
            custos_mensal['mes'] = custos_mensal['data'].dt.to_period('M').astype(str)

        # ... (continuação do código anterior)

        with tab2:
            custos_mensal = df_ins_filtrado.copy()
            custos_mensal['mes'] = custos_mensal['data'].dt.to_period('M').astype(str)
            custos_mensal = custos_mensal.groupby('mes')['custo_total'].sum().reset_index()
            
            fig = px.line(custos_mensal, x='mes', y='custo_total',
                         title='📈 Evolução Mensal de Custos', markers=True)
            st.plotly_chart(fig, use_container_width=True)
        
        with tab3:
            if not df_prod_filtrado.empty:
                rentabilidade_prod = df_prod_filtrado.groupby('cultura')[['caixas', 'caixas_segunda']].sum()
                custos_cultura_ins = df_ins_filtrado.groupby('cultura')['custo_total'].sum()
                
                culturas_comuns = list(set(rentabilidade_prod.index) & set(custos_cultura_ins.index))
                
                if culturas_comuns:
                    df_rentabilidade = pd.DataFrame({
                        'Cultura': culturas_comuns,
                        'Receita': [
                            (rentabilidade_prod.loc[cultura, 'caixas'] * config.get('preco_medio_caixa', 30)) + 
                            (rentabilidade_prod.loc[cultura, 'caixas_segunda'] * config.get('preco_medio_caixa', 30) * 0.5)
                            for cultura in culturas_comuns
                        ],
                        'Custo': [custos_cultura_ins.loc[cultura] for cultura in culturas_comuns]
                    })
                    
                    df_rentabilidade['Lucro'] = df_rentabilidade['Receita'] - df_rentabilidade['Custo']
                    df_rentabilidade['ROI'] = (df_rentabilidade['Lucro'] / df_rentabilidade['Custo'] * 100).round(1)
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        fig = px.bar(df_rentabilidade, x='Cultura', y='Lucro',
                                    title='💵 Lucro por Cultura')
                        st.plotly_chart(fig, use_container_width=True)
                    
                    with col2:
                        fig = px.bar(df_rentabilidade, x='Cultura', y='ROI',
                                    title='📈 ROI (%) por Cultura')
                        st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("ℹ️ Não há culturas com dados completos de produção e custos para análise de rentabilidade.")
    
    # Análise de Correlação e Insights
    st.header("🔍 Insights e Correlações")
    
    if not df_prod_filtrado.empty:
        col1, col2 = st.columns(2)
        
        with col1:
            correlacao_cols = ['caixas', 'temperatura', 'umidade', 'chuva']
            cols_disponiveis = [col for col in correlacao_cols if col in df_prod_filtrado.columns]
            
            if len(cols_disponiveis) > 1:
                correlacao = df_prod_filtrado[cols_disponiveis].corr()
                fig = px.imshow(correlacao, text_auto=True, aspect="auto",
                               title='📊 Correlação: Clima vs Produção')
                st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            if 'area' in df_prod_filtrado.columns:
                top_areas = df_prod_filtrado.groupby('area')['caixas'].sum().nlargest(5)
                if not top_areas.empty:
                    fig = px.bar(x=top_areas.index, y=top_areas.values,
                                title='🏆 Top 5 Áreas por Produção')
                    st.plotly_chart(fig, use_container_width=True)
    
    # Recomendações baseadas em dados
    st.header("🎯 Recomendações Estratégicas")
    
    insights = []
    
    if 'df_rentabilidade' in locals() and not df_rentabilidade.empty:
        cultura_lucrativa = df_rentabilidade.nlargest(1, 'ROI')['Cultura'].iloc[0]
        roi_max = df_rentabilidade.nlargest(1, 'ROI')['ROI'].iloc[0]
        insights.append(f"✅ **{cultura_lucrativa}** é a cultura mais rentável (ROI: {roi_max}%)")
    
    if 'pct_segunda' in locals() and pct_segunda > config.get('alerta_pct_segunda', 25):
        insights.append(f"⚠️ **Alerta**: Percentual de 2ª qualidade ({pct_segunda:.1f}%) acima do limite recomendado")
    
    if not df_prod_filtrado.empty and 'area' in df_prod_filtrado.columns:
        prod_area = df_prod_filtrado.groupby('area')['caixas'].mean()
        if not prod_area.empty:
            area_baixa = prod_area.idxmin()
            prod_baixa = prod_area.min()
            insights.append(f"🔍 **Oportunidade**: Área {area_baixa} tem a menor produtividade média ({prod_baixa:.1f} caixas/dia)")
    
    for insight in insights:
        st.info(insight)
    
    if not df_prod_filtrado.empty:
        st.download_button(
            "📊 Exportar Relatório de Análise",
            data=df_prod_filtrado.to_csv(index=False),
            file_name="relatorio_analise.csv",
            mime="text/csv"
        )

def pagina_configuracoes():
    """Página de configurações do sistema"""
    st.title("⚙️ Configurações do Sistema")
    
    tab1, tab2, tab3, tab4 = st.tabs(["Geral", "Fenologia", "Preços e Custos", "Fenologia por Espécie"])
    
    with tab1:
        st.subheader("Configurações Gerais")
        cidade_new = st.text_input("Cidade padrão para clima", value=config.get("cidade", CIDADE_PADRAO))
        
        pct_alert = st.number_input("Alerta % de segunda qualidade", 
                                   min_value=0.0, max_value=100.0, 
                                   value=float(config.get("alerta_pct_segunda", 25.0)))
        
        prod_alert = st.number_input("Alerta produção baixa (%)", 
                                    min_value=0.0, max_value=100.0,
                                    value=float(config.get("alerta_prod_baixo_pct", 30.0)))
        
        preco_caixa = st.number_input("Preço médio da caixa (R$)", min_value=0.0, 
                                     value=float(config.get("preco_medio_caixa", 30.0)))
    
    with tab2:
        st.subheader("Estágios Fenológicos Padrão")
        st.info("Configure os estágios de desenvolvimento padrão para culturas sem configuração específica")
        
        estagios = config.get("fenologia_padrao", {}).get("estagios", [])
        novos_estagios = []
        
        for i, estagio in enumerate(estagios):
            st.markdown(f"**Estágio {i+1}**")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                nome = st.text_input("Nome", value=estagio.get("nome", ""), key=f"nome_{i}")
            with col2:
                dias = st.text_input("Duração (dias)", value=estagio.get("dias", ""), key=f"dias_{i}")
            with col3:
                adubo = st.number_input("Adubo (kg/ha)", value=float(estagio.get("adubo", 0)), key=f"adubo_{i}")
            with col4:
                agua = st.number_input("Água (L/planta)", value=float(estagio.get("agua", 0)), key=f"agua_{i}")
            
            novos_estagios.append({"nome": nome, "dias": dias, "adubo": adubo, "agua": agua})
        
        if st.button("Adicionar estágio padrão"):
            novos_estagios.append({"nome": "Novo Estágio", "dias": "0-0", "adubo": 0.0, "agua": 0.0})
        
        # Substitua esta linha:
config.setdefault("fenologia_padrao", {})["estagios"] = novos_estagios

# Por esta verificação mais robusta:
if "fenologia_padrao" not in config:
    config["fenologia_padrao"] = {"estagios": []}
config["fenologia_padrao"]["estagios"] = novos_estagios
    
with tab3:
        st.subheader("Custos Médios de Insumos")
        st.info("Configure os preços de referência para cada tipo de insumo")
        
        custos_medios = config.get("custo_medio_insumos", {})
        novos_custos = {}
        
        for tipo in TIPOS_INSUMOS:
            valor_atual = custos_medios.get(tipo, 0.0)
            novo_valor = st.number_input(f"{tipo} (R$)", min_value=0.0, value=float(valor_atual), key=f"custo_{tipo}")
            novos_custos[tipo] = novo_valor
        
        config["custo_medio_insumos"] = novos_custos
    
with tab4:
        st.subheader("Fenologia por Espécie")
        st.info("Configure estágios fenológicos específicos para cada espécie")
        
        especies_existentes = list(fenologia_especies.keys())
        nova_especie = st.text_input("Nova espécie")
        
        if nova_especie and nova_especie not in especies_existentes:
            if st.button("Adicionar nova espécie"):
                fenologia_especies[nova_especie] = config["fenologia_padrao"]["estagios"].copy()
                salvar_fenologia_especie(nova_especie, fenologia_especies[nova_especie])
                st.success(f"Espécie {nova_especie} adicionada!")
                st.rerun()
        
        especie_selecionada = st.selectbox(
            "Selecionar espécie para editar",
            options=especies_existentes,
            index=0 if especies_existentes else None
        )
        
        if especie_selecionada:
            estagios_especie = fenologia_especies[especie_selecionada]
            st.markdown(f"### Estágios fenológicos para {especie_selecionada}")
            
            novos_estagios = []
            for i, estagio in enumerate(estagios_especie):
                st.markdown(f"**Estágio {i+1}**")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    nome = st.text_input("Nome", value=estagio.get("nome", ""), key=f"esp_nome_{especie_selecionada}_{i}")
                with col2:
                    dias = st.text_input("Duração (dias)", value=estagio.get("dias", ""), key=f"esp_dias_{especie_selecionada}_{i}")
                with col3:
                    adubo = st.number_input("Adubo (kg/ha)", value=float(estagio.get("adubo", 0)), key=f"esp_adubo_{especie_selecionada}_{i}")
                with col4:
                    agua = st.number_input("Água (L/planta)", value=float(estagio.get("agua", 0)), key=f"esp_agua_{especie_selecionada}_{i}")
                
                novos_estagios.append({"nome": nome, "dias": dias, "adubo": adubo, "agua": agua})
            
            if st.button(f"Adicionar estágio para {especie_selecionada}"):
                novos_estagios.append({"nome": "Novo Estágio", "dias": "0-0", "adubo": 0.0, "agua": 0.0})
            
            if st.button(f"Salvar estágios para {especie_selecionada}"):
                fenologia_especies[especie_selecionada] = novos_estagios
                salvar_fenologia_especie(especie_selecionada, novos_estagios)
                st.success(f"Estágios para {especie_selecionada} salvos com sucesso!")
    
    if st.button("Salvar Configurações Gerais"):
        config["cidade"] = cidade_new
        config["alerta_pct_segunda"] = float(pct_alert)
        config["alerta_prod_baixo_pct"] = float(prod_alert)
        config["preco_medio_caixa"] = float(preco_caixa)
        salvar_config(config)
        st.success("Configurações salvas com sucesso!")

# ===============================
# MENU PRINCIPAL
# ===============================
def main():
    """Função principal da aplicação"""
    # Inicialização
    criar_tabelas()
    global config, fenologia_especies
    config = carregar_config()
    fenologia_especies = carregar_fenologia_especies()
    
    # Sidebar
    st.sidebar.title("📌 Menu Navegação")
    pagina = st.sidebar.radio("Escolha a página:", 
                            ["Dashboard", "Cadastro Produção", "Cadastro Insumos", 
                             "Análise", "Recomendações Agronômicas", "Configurações"])
    
    # Navegação
    if pagina == "Dashboard":
        pagina_dashboard()
    elif pagina == "Cadastro Produção":
        pagina_cadastro_producao()
    elif pagina == "Cadastro Insumos":
        pagina_cadastro_insumos()
    elif pagina == "Análise":
        pagina_analise()
    elif pagina == "Recomendações Agronômicas":
        mostrar_modulo_agronomico()
    elif pagina == "Configurações":
        pagina_configuracoes()
    
    # Exportar dados
    st.sidebar.markdown("---")
    st.sidebar.subheader("📤 Exportar Dados")
    
    if st.sidebar.button("Exportar Produção Excel"):
        df_export = carregar_tabela("producao")
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_export.to_excel(writer, sheet_name='Produção', index=False)
            workbook = writer.book
            worksheet = writer.sheets['Produção']
            format_header = workbook.add_format({'bold': True, 'bg_color': '#2c3e50', 'font_color': 'white'})
            for col_num, value in enumerate(df_export.columns.values):
                worksheet.write(0, col_num, value, format_header)
        
        output.seek(0)
        st.sidebar.download_button(
            "📥 Baixar Produção", 
            data=output, 
            file_name="producao_exportada.xlsx", 
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    if st.sidebar.button("Exportar Insumos Excel"):
        df_export = carregar_tabela("insumos")
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_export.to_excel(writer, sheet_name='Insumos', index=False)
            workbook = writer.book
            worksheet = writer.sheets['Insumos']
            format_header = workbook.add_format({'bold': True, 'bg_color': '#2c3e50', 'font_color': 'white'})
            for col_num, value in enumerate(df_export.columns.values):
                worksheet.write(0, col_num, value, format_header)
        
        output.seek(0)
        st.sidebar.download_button(
            "📥 Baixar Insumos", 
            data=output, 
            file_name="insumos_exportados.xlsx", 
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    st.sidebar.markdown("---")
    st.sidebar.info("🌱 Desenvolvido para otimizar a gestão agrícola")

# ===============================
# EXECUÇÃO PRINCIPAL
# ===============================
if __name__ == "__main__":
    main()
