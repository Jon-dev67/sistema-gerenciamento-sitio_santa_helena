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
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ===============================
# CONFIGURAÇÕES INICIAIS
# ===============================
st.set_page_config(page_title="🌱 Gerenciador Integrado de Produção", layout="wide")
plt.style.use("dark_background")
sns.set_theme(style="darkgrid")

DB_NAME = "dados_sitio.db"
CONFIG_FILE = "config.json"
API_KEY = "eef20bca4e6fb1ff14a81a3171de5cec"  # OpenWeather API Key
CIDADE_PADRAO = "Londrina"

# Tipos de insumos pré-definidos para padronização
TIPOS_INSUMOS = [
    "Adubo Orgânico", "Adubo Químico", "Defensivo Agrícola", 
    "Semente", "Muda", "Fertilizante Foliar", 
    "Corretivo de Solo", "Insumo para Irrigação", "Outros"
]

UNIDADES = ["kg", "g", "L", "mL", "unidade", "saco", "caixa", "pacote"]

# ===============================
# BANCO DE DADOS
# ===============================
def criar_tabelas():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Tabela de produção
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS producao (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data TEXT,
        estufa TEXT,
        cultura TEXT,
        caixas INTEGER,
        caixas_segunda INTEGER,
        temperatura REAL,
        umidade REAL,
        chuva REAL,
        observacao TEXT
    )
    """)
    
    # Tabela de insumos (ampliada)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS insumos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data TEXT,
        estufa TEXT,
        cultura TEXT,
        tipo TEXT,
        quantidade REAL,
        unidade TEXT,
        custo_unitario REAL,
        custo_total REAL,
        fornecedor TEXT,
        lote TEXT,
        observacoes TEXT
    )
    """)
    
    # Nova tabela para custos operacionais
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS custos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data TEXT,
        tipo TEXT,
        descricao TEXT,
        valor REAL,
        area TEXT,
        observacoes TEXT
    )
    """)
    
    conn.commit()
    conn.close()

def inserir_tabela(nome_tabela, df):
    conn = sqlite3.connect(DB_NAME)
    df.to_sql(nome_tabela, conn, if_exists="append", index=False)
    conn.close()

def carregar_tabela(nome_tabela):
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql(f"SELECT * FROM {nome_tabela}", conn)
    conn.close()
    return df

def excluir_linha(nome_tabela, row_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM {nome_tabela} WHERE id=?", (row_id,))
    conn.commit()
    conn.close()

criar_tabelas()

# ===============================
# CONFIGURAÇÕES
# ===============================
def carregar_config():
    if not os.path.exists(CONFIG_FILE):
        cfg = {
            "cidade": CIDADE_PADRAO,
            "fenologia": {
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
                "Adubo Orgânico": 2.5,
                "Adubo Químico": 4.0,
                "Defensivo Agrícola": 35.0,
                "Semente": 0.5,
                "Muda": 1.2,
                "Fertilizante Foliar": 15.0,
                "Corretivo de Solo": 1.8
            }
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
        return cfg
    
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def salvar_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)

config = carregar_config()

# ===============================
# FUNÇÕES UTILITÁRIAS
# ===============================
def buscar_clima(cidade):
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
                    "Data": item["dt_txt"],
                    "Temp Real (°C)": item["main"]["temp"],
                    "Temp Média (°C)": (item["main"]["temp_min"] + item["main"]["temp_max"]) / 2,
                    "Temp Min (°C)": item["main"]["temp_min"],
                    "Temp Max (°C)": item["main"]["temp_max"],
                    "Umidade (%)": item["main"]["humidity"]
                })
                
        return atual, pd.DataFrame(previsao)
    except:
        return None, None

def normalizar_colunas(df):
    df = df.copy()
    col_map = {
        "Estufa": "estufa", "Área": "estufa", "Produção": "caixas", 
        "Primeira": "caixas", "Segunda": "caixas_segunda", 
        "Qtd": "caixas", "Quantidade": "caixas", "Data": "data"
    }
    df.rename(columns={c: col_map.get(c, c) for c in df.columns}, inplace=True)
    
    if "data" in df.columns: 
        df["data"] = pd.to_datetime(df["data"], errors="coerce").dt.strftime('%Y-%m-%d')
    
    for col in ["caixas", "caixas_segunda", "temperatura", "umidade", "chuva"]:
        if col not in df.columns: 
            df[col] = 0
    
    if "estufa" not in df.columns: 
        df["estufa"] = ""
    
    if "cultura" not in df.columns: 
        df["cultura"] = ""
    
    return df

def plot_bar_sum(ax, df, x, y, titulo, ylabel, palette="tab20"):
    if df.empty:
        ax.set_axis_off()
        return
        
    g = df.groupby(x)[y].sum().reset_index()
    if g.empty: 
        ax.set_axis_off()
        return
        
    sns.barplot(data=g, x=x, y=y, ax=ax, palette=palette)
    ax.set_title(titulo, fontsize=14)
    ax.set_ylabel(ylabel)
    ax.set_xlabel("")
    ax.grid(axis="y", linestyle="--", alpha=0.5)
    
    for c in ax.containers: 
        ax.bar_label(c, fmt="%.0f")

def calcular_estagio_fenologico(data_plantio):
    """Calcula o estágio fenológico com base na data de plantio"""
    if not data_plantio:
        return "Não especificado"
        
    try:
        dias = (datetime.now() - datetime.strptime(data_plantio, "%Y-%m-%d")).days
        
        for estagio in config["fenologia"]["estagios"]:
            dias_range = estagio["dias"].split("-")
            if len(dias_range) == 2 and dias >= int(dias_range[0]) and dias <= int(dias_range[1]):
                return estagio["nome"]
                
        return "Colheita concluída"
    except:
        return "Data inválida"

def recomendar_adubacao(estagio):
    """Retorna recomendação de adubação baseada no estágio fenológico"""
    for e in config["fenologia"]["estagios"]:
        if e["nome"] == estagio:
            return f"Recomendado: {e['adubo']}kg/ha de adubo e {e['agua']}L/planta de água"
    
    return "Sem recomendação específica"

# ===============================
# MÓDULO DE RECOMENDAÇÕES AGRONÔMICAS
# ===============================

# Dados agronômicos por cultura (baseados em literatura técnica)
DADOS_AGRONOMICOS = {
    "Tomate": {
        "densidade_plantio": 15000,  # plantas por hectare
        "espacamento": "50x30 cm",
        "producao_esperada": 2.5,  # kg por planta por ciclo
        "ciclo_dias": 90,
        "temp_ideal": [18, 28],
        "umidade_ideal": [60, 80],
        "ph_ideal": [5.5, 6.8],
        "adubacao_base": {
            "N": 120,  # kg/ha de Nitrogênio
            "P": 80,   # kg/ha de Fósforo  
            "K": 150   # kg/ha de Potássio
        },
        "pragas_comuns": ["tuta-absoluta", "mosca-branca", "ácaros"],
        "doencas_comuns": ["requeima", "murcha-bacteriana", "oidio"]
    },
    "Pepino Japonês": {
        "densidade_plantio": 18000,
        "espacamento": "80x40 cm",
        "producao_esperada": 3.2,  # kg por planta
        "ciclo_dias": 65,
        "temp_ideal": [20, 30],
        "umidade_ideal": [65, 80],
        "ph_ideal": [5.5, 6.5],
        "adubacao_base": {
            "N": 110,
            "P": 60,
            "K": 140
        },
        "pragas_comuns": ["mosca-branca", "ácaros", "vaquinha"],
        "doencas_comuns": ["oidio", "antracnose", "viruses"]
    },
    "Pepino Caipira": {
        "densidade_plantio": 15000,
        "espacamento": "100x50 cm", 
        "producao_esperada": 2.8,  # kg por planta
        "ciclo_dias": 70,
        "temp_ideal": [18, 28],
        "umidade_ideal": [60, 75],
        "ph_ideal": [5.8, 6.8],
        "adubacao_base": {
            "N": 100,
            "P": 50,
            "K": 120
        },
        "pragas_comuns": ["vaquinha", "broca", "ácaros"],
        "doencas_comuns": ["oidio", "mancha-angular", "viruses"]
    },
    "Abóbora Itália": {
        "densidade_plantio": 8000,
        "espacamento": "200x100 cm",
        "producao_esperada": 4.5,  # kg por planta
        "ciclo_dias": 85,
        "temp_ideal": [20, 30],
        "umidade_ideal": [60, 75],
        "ph_ideal": [6.0, 7.0],
        "adubacao_base": {
            "N": 80,
            "P": 50,
            "K": 100
        },
        "pragas_comuns": ["vaquinha", "broca", "pulgão"],
        "doencas_comuns": ["oidio", "antracnose", "murcha"]
    },
    "Abóbora Menina": {
        "densidade_plantio": 6000,
        "espacamento": "250x120 cm",
        "producao_esperada": 6.0,  # kg por planta
        "ciclo_dias": 95,
        "temp_ideal": [22, 32],
        "umidade_ideal": [65, 80],
        "ph_ideal": [6.0, 7.2],
        "adubacao_base": {
            "N": 70,
            "P": 45,
            "K": 90
        },
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
        'producao_caixas': round(producao_kg / 20, 1),  # assumindo 20kg por caixa
        'ciclo_dias': dados['ciclo_dias']
    }

def gerar_recomendacoes_clima(cultura, dados_clima):
    """Gera recomendações baseadas nas condições climáticas"""
    if cultura not in DADOS_AGRONOMICOS:
        return []
    
    dados = DADOS_AGRONOMICOS[cultura]
    recomendacoes = []
    
    # Verificar temperatura
    temp = dados_clima.get('temperatura', 25)
    if temp < dados['temp_ideal'][0]:
        recomendacoes.append(f"🌡️ Temperatura baixa ({temp}°C) - considerar aquecimento ou cobertura")
    elif temp > dados['temp_ideal'][1]:
        recomendacoes.append(f"🌡️ Temperatura alta ({temp}°C) - aumentar ventilação/sombreamento")
    
    # Verificar umidade
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
    
    # Ajustar adubação base baseada no estágio fenológico
    fator_estagio = {
        "Germinação/Vegetativo": 0.6,
        "Floração": 1.0,
        "Frutificação": 0.8,
        "Maturação": 0.4
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
    
    # Alertas por umidade alta
    if dados_clima.get('umidade', 70) > 80:
        alertas.append(f"⚠️ Condições favoráveis para doenças fúngicas em {cultura}")
        alertas.append(f"   Doenças comuns: {', '.join(dados['doencas_comuns'][:2])}")
    
    # Alertas por temperatura alta + umidade
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
        'cultura': cultura,
        'area_estufa_m2': estufa_area,
        'plantas_recomendadas': int(plantas_possiveis),
        'producao_estimada_kg': round(plantas_possiveis * dados['producao_esperada'], 2),
        'espacamento_recomendado': dados['espacamento'],
        'rendimento_por_m2': round((plantas_possiveis * dados['producao_esperada']) / estufa_area, 3)
    }

# ===============================
# INTEGRAÇÃO COM O SISTEMA EXISTENTE
# ===============================

def adicionar_modulo_agronomico():
    """Adiciona o módulo agronômico à interface do sistema"""
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("🌿 Módulo Agronômico")
    
    # Adicionar ao menu
    if "pagina" not in st.session_state:
        st.session_state.pagina = "Dashboard"
    
    # Adicionar opção no menu
    opcoes_menu = ["Dashboard", "Cadastro Produção", "Cadastro Insumos", "Análise", "Recomendações Agronômicas", "Configurações"]
    pagina = st.sidebar.radio("Escolha a página:", opcoes_menu)
    
    if pagina == "Recomendações Agronômicas":
        mostrar_modulo_agronomico()

def mostrar_modulo_agronomico():
    """Interface do módulo agronômico"""
    
    st.title("🌿 Recomendações Agronômicas Inteligentes")
    
    tab1, tab2, tab3, tab4 = st.tabs(["Calculadora de Produção", "Recomendações de Manejo", "Alertas Sanitários", "Otimização de Espaço"])
    
    with tab1:
        st.header("📊 Calculadora de Produção Esperada")
        
        col1, col2 = st.columns(2)
        with col1:
            cultura = st.selectbox("Selecione a cultura:", list(DADOS_AGRONOMICOS.keys()))
            area_m2 = st.number_input("Área disponível (m²):", min_value=1.0, value=100.0)
        
        with col2:
            if cultura:
                dados_cultura = DADOS_AGRONOMICOS[cultura]
                st.info(f"""
                **Dados Técnicos da {cultura}:**
                - Densidade: {dados_cultura['densidade_plantio']} plantas/ha
                - Espaçamento: {dados_cultura['espacamento']}
                - Ciclo: {dados_cultura['ciclo_dias']} dias
                - Produção esperada: {dados_cultura['producao_esperada']} kg/planta
                """)
        
        if st.button("Calcular Produção Esperada"):
            resultado = calcular_producao_esperada(cultura, area_m2)
            if resultado:
                st.success(f"""
                **Resultado para {cultura} em {area_m2}m²:**
                - 👨‍🌾 Plantas estimadas: {resultado['plantas_estimadas']}
                - 📦 Produção estimada: {resultado['producao_kg']} kg ({resultado['producao_caixas']} caixas)
                - ⏰ Ciclo: {resultado['ciclo_dias']} dias
                """)
    
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
        
        dados_clima = {'temperatura': temperatura, 'umidade': umidade}
        
        if st.button("Gerar Recomendações"):
            # Recomendações climáticas
            rec_clima = gerar_recomendacoes_clima(cultura, dados_clima)
            if rec_clima:
                st.info("**Recomendações Climáticas:**")
                for rec in rec_clima:
                    st.write(f"- {rec}")
            
            # Recomendações de adubação
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
                st.success(f"""
                **Otimização para {cultura}:**
                - 🏭 Área disponível: {resultado['area_estufa_m2']} m²
                - 👨‍🌾 Plantas recomendadas: {resultado['plantas_recomendadas']}
                - 📦 Produção estimada: {resultado['producao_estimada_kg']} kg
                - 📏 Espaçamento: {resultado['espacamento_recomendado']}
                - 📊 Rendimento: {resultado['rendimento_por_m2']} kg/m²
                """)

# ===============================
# INTEGRAÇÃO NO DASHBOARD EXISTENTE
# ===============================
def adicionar_recomendacoes_dashboard():
    """Adiciona cards de recomendação ao dashboard principal"""
    df_prod = carregar_tabela("producao")
    
    if not df_prod.empty:
        st.subheader("🌿 Recomendações Agronômicas")
        
        # Último registro para análise
        ultimo_registro = df_prod.iloc[-1]
        cultura = ultimo_registro['cultura']
        
        # Verificação adicional para cultura não vazia
        if cultura and cultura.strip() and cultura in DADOS_AGRONOMICOS:
            temperatura = ultimo_registro['temperatura']
            umidade = ultimo_registro['umidade']
            
            # Gerar recomendações baseadas nos últimos dados
            dados_clima = {'temperatura': temperatura, 'umidade': umidade}
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
# SIDEBAR / MENU
# ===============================
st.sidebar.title("📌 Menu Navegação")
pagina = st.sidebar.radio("Escolha a página:", 
                         ["Dashboard", "Cadastro Produção", "Cadastro Insumos", "Análise", "Recomendações Agronômicas", "Configurações"])

# ===============================
# PÁGINA: DASHBOARD
# ===============================
if pagina == "Dashboard":
    st.title("🌱 Dashboard de Produção")
    
    # Carregar dados
    df_prod = carregar_tabela("producao")
    df_ins = carregar_tabela("insumos")
    
    # KPIs principais
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        total_caixas = df_prod["caixas"].sum() if not df_prod.empty else 0
        total_segunda = df_prod["caixas_segunda"].sum() if not df_prod.empty else 0
        st.metric("📦 Caixas 1ª Qualidade", f"{total_caixas:.0f}")
    
    with col2:
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
        # Alertas de produção
        df_prod["pct_segunda"] = np.where(
            (df_prod["caixas"] + df_prod["caixas_segunda"]) > 0,
            df_prod["caixas_segunda"] / (df_prod["caixas"] + df_prod["caixas_segunda"]) * 100,
            0
        )
        
        alta_segunda = df_prod[df_prod["pct_segunda"] > config.get("alerta_pct_segunda", 25)]
        if not alta_segunda.empty:
            st.warning(f"Alto percentual de 2ª qualidade ({alta_segunda['pct_segunda'].mean():.1f}%)")
        
        # Alertas de clima
        ultimo_clima = df_prod.iloc[-1] if not df_prod.empty else None
        if ultimo_clima is not None and ultimo_clima["umidade"] > 85:
            st.error("Alerta: Umidade muito alta, risco de doenças fúngicas!")
        
        if ultimo_clima is not None and ultimo_clima["temperatura"] < 10:
            st.error("Alerta: Temperatura muito baixa, risco de danos às plantas!")
    
    # Gráficos resumos
    st.subheader("📊 Visão Geral")
    
    if not df_prod.empty:
        col1, col2 = st.columns(2)
        
        with col1:
            # Produção por estufa
            prod_estufa = df_prod.groupby("estufa")[["caixas", "caixas_segunda"]].sum().reset_index()
            if not prod_estufa.empty:
                fig = px.bar(prod_estufa, x="estufa", y=["caixas", "caixas_segunda"], 
                            title="Produção por Estufa", barmode="group")
                st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # Evolução temporal
            df_prod["data"] = pd.to_datetime(df_prod["data"])
            prod_temporal = df_prod.groupby("data")[["caixas", "caixas_segunda"]].sum().reset_index()
            if not prod_temporal.empty:
                fig = px.line(prod_temporal, x="data", y=["caixas", "caixas_segunda"], 
                             title="Evolução da Produção", markers=True)
                st.plotly_chart(fig, use_container_width=True)
    
    if not df_ins.empty:
        col1, col2 = st.columns(2)
        
        with col1:
            # Custos por tipo de insumo
            custos_tipo = df_ins.groupby("tipo")["custo_total"].sum().reset_index()
            if not custos_tipo.empty:
                fig = px.pie(custos_tipo, values="custo_total", names="tipo", 
                            title="Distribuição de Custos por Tipo")
                st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # Custos por cultura
            custos_cultura = df_ins.groupby("cultura")["custo_total"].sum().reset_index()
            if not custos_cultura.empty:
                fig = px.bar(custos_cultura, x="cultura", y="custo_total", 
                            title="Custos por Cultura")
                st.plotly_chart(fig, use_container_width=True)


          

# ===============================
# PÁGINA: CADASTRO PRODUÇÃO
# ===============================
elif pagina == "Cadastro Produção":
    st.title("📝 Cadastro de Produção")
    df = carregar_tabela("producao")
    cidade = st.sidebar.text_input("🌍 Cidade para clima", value=config.get("cidade", CIDADE_PADRAO))

    with st.form("form_cadastro_producao", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1: 
            data_val = st.date_input("Data", value=date.today())
            estufa = st.text_input("Estufa/Área")
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
                "data": str(data_val),
                "estufa": estufa.strip(),
                "cultura": cultura.strip(),
                "caixas": int(caixas),
                "caixas_segunda": int(caixas2),
                "temperatura": float(temperatura),
                "umidade": float(umidade),
                "chuva": float(chuva),
                "observacao": observacao
            }])
            inserir_tabela("producao", novo)
            st.success("Registro salvo com sucesso!")

    if not df.empty:
        st.markdown("### 📋 Registros recentes")
        df_display = df.sort_values("data", ascending=False).head(15)
        st.dataframe(df_display, use_container_width=True)
        
        # Excluir linha
        ids = st.multiselect("Selecione ID(s) para excluir", df["id"].tolist())
        if st.button("Excluir selecionados"):
            for i in ids: 
                excluir_linha("producao", i)
            st.success("✅ Linhas excluídas!")
            st.experimental_rerun()

    # Import Excel
    st.subheader("📂 Importar Excel")
    uploaded_file = st.file_uploader("Envie planilha Excel (Produção)", type=["xlsx"])
    if uploaded_file:
        df_excel = pd.read_excel(uploaded_file)
        df_excel = normalizar_colunas(df_excel)
        inserir_tabela("producao", df_excel)
        st.success("✅ Dados importados do Excel!")
        st.rerun()  # ← PARA ISSO

# ===============================
# PÁGINA: CADASTRO INSUMOS
# ===============================
elif pagina == "Cadastro Insumos":
    st.title("📦 Cadastro de Insumos")
    df_ins = carregar_tabela("insumos")
    
    with st.form("form_insumos", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            data_i = st.date_input("Data", value=date.today())
            estufa_i = st.text_input("Estufa/Área")
            cultura_i = st.text_input("Cultura (opcional)")
            tipo_i = st.selectbox("Tipo de Insumo", TIPOS_INSUMOS)
            fornecedor_i = st.text_input("Fornecedor (opcional)")
            
        with col2:
            qtd_i = st.number_input("Quantidade", min_value=0.0, step=0.1)
            un_i = st.selectbox("Unidade", UNIDADES)
            custo_unit_i = st.number_input("Custo Unitário (R$)", min_value=0.0, step=0.01)
            custo_total_i = st.number_input("Custo Total (R$)", min_value=0.0, step=0.01, 
                                          value=0.0, 
                                          help="Se não preenchido, será calculado automaticamente")
            lote_i = st.text_input("Nº Lote (opcional)")
            
        observacoes_i = st.text_area("Observações")
        
        # Calcular custo total automaticamente se necessário
        if custo_unit_i > 0 and qtd_i > 0 and custo_total_i == 0:
            custo_total_i = custo_unit_i * qtd_i
            st.info(f"Custo total calculado: R$ {custo_total_i:.2f}")
            
        enviado_i = st.form_submit_button("Salvar Insumo ✅")
        if enviado_i:
            novo = pd.DataFrame([{
                "data": str(data_i),
                "estufa": estufa_i,
                "cultura": cultura_i,
                "tipo": tipo_i,
                "quantidade": qtd_i,
                "unidade": un_i,
                "custo_unitario": custo_unit_i,
                "custo_total": custo_total_i if custo_total_i > 0 else custo_unit_i * qtd_i,
                "fornecedor": fornecedor_i,
                "lote": lote_i,
                "observacoes": observacoes_i
            }])
            inserir_tabela("insumos", novo)
            st.success("Insumo salvo com sucesso!")

    if not df_ins.empty:
        st.subheader("📋 Histórico de Insumos")
        
        # Filtros
        col1, col2, col3 = st.columns(3)
        with col1:
            filtro_tipo = st.multiselect("Filtrar por tipo", options=df_ins["tipo"].unique())
        with col2:
            filtro_estufa = st.multiselect("Filtrar por estufa", options=df_ins["estufa"].unique())
        with col3:
            filtro_cultura = st.multiselect("Filtrar por cultura", options=df_ins["cultura"].unique())
        
        # Aplicar filtros
        df_filtrado = df_ins.copy()
        if filtro_tipo:
            df_filtrado = df_filtrado[df_filtrado["tipo"].isin(filtro_tipo)]
        if filtro_estufa:
            df_filtrado = df_filtrado[df_filtrado["estufa"].isin(filtro_estufa)]
        if filtro_cultura:
            df_filtrado = df_filtrado[df_filtrado["cultura"].isin(filtro_cultura)]
            
        st.dataframe(df_filtrado.sort_values("data", ascending=False).head(20), use_container_width=True)
        
        # Estatísticas de custos
        st.subheader("📊 Estatísticas de Custos")
        if not df_filtrado.empty:
            total_custo = df_filtrado["custo_total"].sum()
            media_custo = df_filtrado["custo_total"].mean()
            st.write(f"**Total gasto:** R$ {total_custo:,.2f} | **Média por registro:** R$ {media_custo:,.2f}")
            
            # Gráfico de evolução de custos
            df_filtrado["data"] = pd.to_datetime(df_filtrado["data"])
            custos_mensais = df_filtrado.groupby(df_filtrado["data"].dt.to_period("M"))["custo_total"].sum().reset_index()
            custos_mensais["data"] = custos_mensais["data"].astype(str)
            
            fig = px.bar(custos_mensais, x="data", y="custo_total", 
                        title="Evolução Mensal de Custos com Insumos")
            st.plotly_chart(fig, use_container_width=True)
        
        # Excluir registros
        ids_insumos = st.multiselect("Selecione ID(s) de insumos para excluir", df_ins["id"].tolist())
        if st.button("Excluir insumos selecionados"):
            for i in ids_insumos: 
                excluir_linha("insumos", i)
            st.success("✅ Insumos excluídos!")
            st.experimental_rerun()

    # Import Excel para insumos
    st.subheader("📂 Importar Excel (Insumos)")
    uploaded_file = st.file_uploader("Envie planilha Excel (Insumos)", type=["xlsx"], key="insumos_upload")
    if uploaded_file:
        df_excel = pd.read_excel(uploaded_file)
        df_excel.rename(columns=lambda x: x.lower(), inplace=True)
        inserir_tabela("insumos", df_excel)
        st.success("✅ Dados de insumos importados do Excel!")
        st.rerun()

# ===============================
# PÁGINA: ANÁLISE
# ===============================
# ===============================
# PÁGINA: ANÁLISE
# ===============================
elif pagina == "Análise":
    st.title("📊 Análise Avançada de Produção e Custos")
    
    # Carregar dados
    df_prod = carregar_tabela("producao")
    df_ins = carregar_tabela("insumos")
    
    if df_prod.empty and df_ins.empty:
        st.warning("📭 Nenhum dado disponível para análise. Cadastre dados de produção e insumos primeiro.")
        st.stop()
    
    # Filtros avançados na sidebar
    st.sidebar.subheader("🔍 Filtros de Análise")
    
    # Período temporal
    if not df_prod.empty:
        datas_disponiveis = pd.to_datetime(df_prod['data']).sort_values()
        min_date = datas_disponiveis.min()
        max_date = datas_disponiveis.max()
    else:
        min_date = date.today() - timedelta(days=365)
        max_date = date.today()
    
    date_range = st.sidebar.date_input(
        "📅 Período de análise",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date
    )
    
    if len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date, end_date = min_date, max_date
    
    # Filtros adicionais
    col1, col2 = st.sidebar.columns(2)
    
    with col1:
        if not df_prod.empty:
            estufas_disponiveis = df_prod['estufa'].unique()
            estufas_selecionadas = st.multiselect(
                "🏭 Estufas", 
                options=estufas_disponiveis,
                default=estufas_disponiveis
            )
        else:
            estufas_selecionadas = []
        
        if not df_ins.empty:
            tipos_insumos_disponiveis = df_ins['tipo'].unique()
            tipos_selecionados = st.multiselect(
                "📦 Tipos de Insumos", 
                options=tipos_insumos_disponiveis,
                default=tipos_insumos_disponiveis
            )
        else:
            tipos_selecionados = []
    
    with col2:
        if not df_prod.empty:
            culturas_disponiveis = df_prod['cultura'].unique()
            culturas_selecionadas = st.multiselect(
                "🌱 Culturas", 
                options=culturas_disponiveis,
                default=culturas_disponiveis
            )
        else:
            culturas_selecionadas = []
    
    # Aplicar filtros
    if not df_prod.empty:
        df_prod['data'] = pd.to_datetime(df_prod['data'])
        df_prod_filtrado = df_prod[
            (df_prod['data'] >= pd.to_datetime(start_date)) & 
            (df_prod['data'] <= pd.to_datetime(end_date))
        ]
        if estufas_selecionadas:
            df_prod_filtrado = df_prod_filtrado[df_prod_filtrado['estufa'].isin(estufas_selecionadas)]
        if culturas_selecionadas:
            df_prod_filtrado = df_prod_filtrado[df_prod_filtrado['cultura'].isin(culturas_selecionadas)]
    else:
        df_prod_filtrado = pd.DataFrame()
    
    if not df_ins.empty:
        df_ins['data'] = pd.to_datetime(df_ins['data'])
        df_ins_filtrado = df_ins[
            (df_ins['data'] >= pd.to_datetime(start_date)) & 
            (df_ins['data'] <= pd.to_datetime(end_date))
        ]
        if tipos_selecionados:
            df_ins_filtrado = df_ins_filtrado[df_ins_filtrado['tipo'].isin(tipos_selecionados)]
    else:
        df_ins_filtrado = pd.DataFrame()
    
    # Métricas de performance
    st.header("📈 Métricas de Performance")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if not df_prod_filtrado.empty:
            total_caixas = df_prod_filtrado['caixas'].sum()
            st.metric("📦 Caixas 1ª Qualidade", f"{total_caixas:,.0f}")
        else:
            st.metric("📦 Caixas 1ª Qualidade", "0")
    
    with col2:
        if not df_prod_filtrado.empty:
            total_segunda = df_prod_filtrado['caixas_segunda'].sum()
            pct_segunda = (total_segunda / (total_caixas + total_segunda) * 100) if (total_caixas + total_segunda) > 0 else 0
            st.metric("🔄 % 2ª Qualidade", f"{pct_segunda:.1f}%")
        else:
            st.metric("🔄 % 2ª Qualidade", "0%")
    
    with col3:
        if not df_ins_filtrado.empty:
            custo_total = df_ins_filtrado['custo_total'].sum()
            st.metric("💰 Custo Total", f"R$ {custo_total:,.2f}")
        else:
            st.metric("💰 Custo Total", "R$ 0,00")
    
    with col4:
        if not df_prod_filtrado.empty and not df_ins_filtrado.empty:
            receita_estimada = total_caixas * config.get('preco_medio_caixa', 30)
            lucro = receita_estimada - custo_total
            st.metric("💵 Lucro Estimado", f"R$ {lucro:,.2f}")
        else:
            st.metric("💵 Lucro Estimado", "R$ 0,00")
    
    # Análise de Produção
    if not df_prod_filtrado.empty:
        st.header("🌱 Análise de Produção")
        
        tab1, tab2, tab3, tab4 = st.tabs(["Visão Geral", "Por Cultura", "Por Estufa", "Tendências"])
        
        with tab1:
            col1, col2 = st.columns(2)
            
            with col1:
                # Produção diária
                prod_diaria = df_prod_filtrado.groupby('data')[['caixas', 'caixas_segunda']].sum().reset_index()
                fig = px.line(prod_diaria, x='data', y=['caixas', 'caixas_segunda'],
                             title='📅 Produção Diária', markers=True)
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                # Qualidade da produção
                qualidade_data = pd.DataFrame({
                    'Categoria': ['1ª Qualidade', '2ª Qualidade'],
                    'Quantidade': [total_caixas, total_segunda]
                })
                fig = px.pie(qualidade_data, values='Quantidade', names='Categoria',
                            title='🎯 Distribuição por Qualidade')
                st.plotly_chart(fig, use_container_width=True)
        
        with tab2:
            # Análise por cultura
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
            # Análise por estufa
            prod_estufa = df_prod_filtrado.groupby('estufa')[['caixas', 'caixas_segunda']].sum().reset_index()
            prod_estufa['Produtividade'] = prod_estufa['caixas'] / len(df_prod_filtrado['data'].unique())
            
            col1, col2 = st.columns(2)
            
            with col1:
                fig = px.bar(prod_estufa, x='estufa', y='caixas',
                            title='🏭 Produção Total por Estufa')
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                fig = px.bar(prod_estufa, x='estufa', y='Produtividade',
                            title='⚡ Produtividade Média Diária por Estufa')
                st.plotly_chart(fig, use_container_width=True)
        
        with tab4:
            # Análise de tendências
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
                # Custos por tipo
                custos_tipo = df_ins_filtrado.groupby('tipo')['custo_total'].sum().reset_index()
                fig = px.pie(custos_tipo, values='custo_total', names='tipo',
                            title='📊 Distribuição de Custos por Tipo')
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                # Custos por cultura
                custos_cultura = df_ins_filtrado.groupby('cultura')['custo_total'].sum().reset_index()
                fig = px.bar(custos_cultura, x='cultura', y='custo_total',
                            title='🌱 Custos por Cultura')
                st.plotly_chart(fig, use_container_width=True)
        
        with tab2:
            # Evolução temporal de custos
            custos_mensal = df_ins_filtrado.copy()
            custos_mensal['mes'] = custos_mensal['data'].dt.to_period('M').astype(str)
            custos_mensal = custos_mensal.groupby('mes')['custo_total'].sum().reset_index()
            
            fig = px.line(custos_mensal, x='mes', y='custo_total',
                         title='📈 Evolução Mensal de Custos', markers=True)
            st.plotly_chart(fig, use_container_width=True)
        
        with tab3:
            if not df_prod_filtrado.empty:
                # CORREÇÃO: Análise de rentabilidade com tratamento para dados inconsistentes
                rentabilidade_prod = df_prod_filtrado.groupby('cultura')[['caixas', 'caixas_segunda']].sum()
                custos_cultura_ins = df_ins_filtrado.groupby('cultura')['custo_total'].sum()
                
                # Encontrar culturas comuns entre produção e custos
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
            # Correlação entre clima e produção
            correlacao_cols = ['caixas', 'temperatura', 'umidade', 'chuva']
            cols_disponiveis = [col for col in correlacao_cols if col in df_prod_filtrado.columns]
            
            if len(cols_disponiveis) > 1:
                correlacao = df_prod_filtrado[cols_disponiveis].corr()
                fig = px.imshow(correlacao, text_auto=True, aspect="auto",
                               title='📊 Correlação: Clima vs Produção')
                st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # Top performers
            top_estufas = df_prod_filtrado.groupby('estufa')['caixas'].sum().nlargest(5)
            if not top_estufas.empty:
                fig = px.bar(x=top_estufas.index, y=top_estufas.values,
                            title='🏆 Top 5 Estufas por Produção')
                st.plotly_chart(fig, use_container_width=True)
    
    # Recomendações baseadas em dados
    st.header("🎯 Recomendações Estratégicas")
    
    insights = []
    
    # Insight 1: Culturas mais rentáveis
    if 'df_rentabilidade' in locals() and not df_rentabilidade.empty:
        cultura_lucrativa = df_rentabilidade.nlargest(1, 'ROI')['Cultura'].iloc[0]
        roi_max = df_rentabilidade.nlargest(1, 'ROI')['ROI'].iloc[0]
        insights.append(f"✅ **{cultura_lucrativa}** é a cultura mais rentável (ROI: {roi_max}%)")
    
    # Insight 2: Alta porcentagem de 2ª qualidade
    if 'pct_segunda' in locals() and pct_segunda > config.get('alerta_pct_segunda', 25):
        insights.append(f"⚠️ **Alerta**: Percentual de 2ª qualidade ({pct_segunda:.1f}%) acima do limite recomendado")
    
    # Insight 3: Estufas com baixa produtividade
    if not df_prod_filtrado.empty:
        prod_estufa = df_prod_filtrado.groupby('estufa')['caixas'].mean()
        if not prod_estufa.empty:
            estufa_baixa = prod_estufa.idxmin()
            prod_baixa = prod_estufa.min()
            insights.append(f"🔍 **Oportunidade**: Estufa {estufa_baixa} tem a menor produtividade média ({prod_baixa:.1f} caixas/dia)")
    
    # Exibir insights
    for insight in insights:
        st.info(insight)
    
    # Exportar relatório
    if not df_prod_filtrado.empty:
        st.download_button(
            "📊 Exportar Relatório de Análise",
            data=df_prod_filtrado.to_csv(index=False),
            file_name="relatorio_analise.csv",
            mime="text/csv"
        )
# ===============================
# PÁGINA: CONFIGURAÇÕES
# ===============================
elif pagina == "Configurações":
    st.title("⚙️ Configurações do Sistema")
    
    tab1, tab2, tab3 = st.tabs(["Geral", "Fenologia", "Preços e Custos"])
    
    with tab1:
        st.subheader("Configurações Gerais")
        cidade_new = st.text_input("Cidade padrão para clima", value=config.get("cidade", CIDADE_PADRAO))
        
        # CORREÇÃO: Converter valores para float para manter consistência
        pct_alert = st.number_input("Alerta % de segunda qualidade", 
                                   min_value=0.0, max_value=100.0, 
                                   value=float(config.get("alerta_pct_segunda", 25.0)))
        
        prod_alert = st.number_input("Alerta produção baixa (%)", 
                                    min_value=0.0, max_value=100.0,
                                    value=float(config.get("alerta_prod_baixo_pct", 30.0)))
        
        preco_caixa = st.number_input("Preço médio da caixa (R$)", min_value=0.0, 
                                     value=float(config.get("preco_medio_caixa", 30.0)))
    
    with tab2:
        st.subheader("Estágios Fenológicos")
        st.info("Configure os estágios de desenvolvimento das culturas e suas necessidades")
        
        # Editor de estágios fenológicos
        estagios = config.get("fenologia", {}).get("estagios", [])
        
        novos_estagios = []
        for i, estagio in enumerate(estagios):
            st.markdown(f"**Estágio {i+1}**")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                nome = st.text_input("Nome", value=estagio.get("nome", ""), key=f"nome_{i}")
            with col2:
                dias = st.text_input("Duração (dias)", value=estagio.get("dias", ""), key=f"dias_{i}")
            with col3:
                # CORREÇÃO: Usar float para consistência
                adubo = st.number_input("Adubo (kg/ha)", value=float(estagio.get("adubo", 0)), key=f"adubo_{i}")
            with col4:
                # CORREÇÃO: Usar float para consistência
                agua = st.number_input("Água (L/planta)", value=float(estagio.get("agua", 0)), key=f"agua_{i}")
            
            novos_estagios.append({
                "nome": nome,
                "dias": dias,
                "adubo": adubo,
                "agua": agua
            })
        
        # Adicionar novo estágio
        if st.button("Adicionar estágio"):
            novos_estagios.append({"nome": "Novo Estágio", "dias": "0-0", "adubo": 0.0, "agua": 0.0})
        
        config["fenologia"]["estagios"] = novos_estagios
    
    with tab3:
        st.subheader("Custos Médios de Insumos")
        st.info("Configure os preços de referência para cada tipo de insumo")
        
        custos_medios = config.get("custo_medio_insumos", {})
        novos_custos = {}
        
        for tipo in TIPOS_INSUMOS:
            valor_atual = custos_medios.get(tipo, 0.0)
            # CORREÇÃO: Usar float para consistência
            novo_valor = st.number_input(f"{tipo} (R$)", min_value=0.0, value=float(valor_atual), key=f"custo_{tipo}")
            novos_custos[tipo] = novo_valor
        
        config["custo_medio_insumos"] = novos_custos
    
    if st.button("Salvar Configurações"):
        config["cidade"] = cidade_new
        config["alerta_pct_segunda"] = float(pct_alert)  # CORREÇÃO: Converter para float
        config["alerta_prod_baixo_pct"] = float(prod_alert)  # CORREÇÃO: Converter para float
        config["preco_medio_caixa"] = float(preco_caixa)  # CORREÇÃO: Converter para float
        salvar_config(config)
        st.success("Configurações salvas com sucesso!")

   # ===============================
    # INTEGRAR MÓDULO AGRONÔMICO AO DASHBOARD
    # ===============================
if pagina == "Dashboard":
    adicionar_recomendacoes_dashboard()
elif pagina == "Recomendações Agronômicas":
    mostrar_modulo_agronomico()

# ===============================
# EXPORTAR DADOS
# ===============================
st.sidebar.markdown("---")
st.sidebar.subheader("📤 Exportar Dados")

if st.sidebar.button("Exportar Produção Excel"):
    df_export = carregar_tabela("producao")
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_export.to_excel(writer, sheet_name='Produção', index=False)
        
        # Adicionar formatação
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

# ===============================
# RODAPÉ
# ===============================
st.sidebar.markdown("---")
st.sidebar.info("🌱 Desenvolvido para otimizar a gestão agrícola")