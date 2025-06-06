import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from io import BytesIO

# Carrega dados do Excel fixo
@st.cache_data

def carregar_dados():
    caminho = "testeAcudes.xlsx"
    cav = pd.read_excel(caminho, sheet_name="cav")
    evaporacao = pd.read_excel(caminho, sheet_name="evaporacao")
    acudes = pd.read_excel(caminho, sheet_name="acudes")
    return cav, evaporacao, acudes

def simular_reservatorio(volume_inicial, curva_av, afluencias, demandas, evaporacao_mm, restricoes=None):
    curva_av['volume'] = pd.to_numeric(curva_av['volume'], errors='coerce')
    curva_av['area'] = pd.to_numeric(curva_av['area'], errors='coerce')
    curva_av = curva_av.dropna(subset=['volume', 'area'])

    vol = curva_av['volume'].values
    area = curva_av['area'].values

    coef_polinomio = np.polyfit(vol, area, deg=3)
    polinomio_area = np.poly1d(coef_polinomio)

    volume_max = np.inf
    volume_min_oper = 0
    volume_morto = 0

    if restricoes is not None:
        try:
            restricoes_dict = restricoes.set_index('Parâmetro')['Valor (hm³)'].to_dict()
            volume_max = restricoes_dict.get('Volume Máximo', volume_max)
            volume_min_oper = restricoes_dict.get('Volume Mínimo Operacional', volume_min_oper)
            volume_morto = restricoes_dict.get('Volume Morto', volume_morto)
        except Exception as e:
            st.warning(f"Erro ao ler restrições operacionais: {e}")

    n_meses = len(afluencias)
    volumes = np.zeros(n_meses + 1)
    evap_hm3 = np.zeros(n_meses)
    retiradas = np.zeros(n_meses)
    alertas = []

    volumes[0] = volume_inicial

    for t in range(n_meses):
        v_ant = volumes[t]
        a = polinomio_area(v_ant) * 1e6  # Usa o polinômio calculado        a = max(a, 0)
        evap_m = evaporacao_mm[t] / 1000  # mm -> m
        evap_volume = (a * evap_m) / 1e6  # m³ -> hm³

        demanda = demandas[t]
        retirada = min(demanda, max(0, v_ant + afluencias[t] - evap_volume))
        v_atual = v_ant + afluencias[t] - evap_volume - retirada
        v_atual = max(v_atual, 0)
        v_atual = min(v_atual, volume_max)

        if v_atual < volume_min_oper:
            alertas.append(f"Mês {t + 1}: volume abaixo do mínimo operacional ({v_atual:.2f} hm³)")
        if v_atual < volume_morto:
            alertas.append(f"Mês {t + 1}: volume abaixo do volume morto ({v_atual:.2f} hm³)")

        evap_hm3[t] = evap_volume
        volumes[t + 1] = v_atual
        retiradas[t] = retirada

    return {
        'volumes': volumes[1:],
        'retiradas': retiradas,
        'evaporacao': evap_hm3,
        'alertas': alertas
    }


def gerar_relatorio_pdf(nome_reservatorio, resultados):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, f"Relatório de Simulação - {nome_reservatorio}")

    c.setFont("Helvetica", 12)
    y = height - 100

    def linha(texto, espaco=20):
        nonlocal y
        c.drawString(50, y, texto)
        y -= espaco

    linha("Resumo dos Resultados:")
    linha(f"Meses simulados: {len(resultados['volumes'])}")
    linha(f"Volume final: {resultados['volumes'][-1]:.2f} hm³")
    linha("")

    linha("Volumes (hm³):")
    for i, vol in enumerate(resultados["volumes"]):
        linha(f"Mês {i + 1}: {vol:.2f}", espaco=15)
        if y < 100:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica", 12)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

def display_results(nome_reservatorio, resultados):
    st.subheader(f"Resultados - {nome_reservatorio}")
    meses = np.arange(1, len(resultados['volumes']) + 1)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=meses, y=resultados['volumes'], mode='lines+markers', name='Volume (hm³)'))
    fig.add_trace(go.Scatter(x=meses, y=resultados['retiradas'], mode='lines+markers', name='Retirada (hm³)',
                             line=dict(dash='dash')))
    fig.add_trace(go.Scatter(x=meses, y=resultados['evaporacao'], mode='lines+markers', name='Evaporação (hm³)',
                             line=dict(dash='dot')))

    fig.update_layout(
        title=f'Simulação do Reservatório - {nome_reservatorio}',
        xaxis_title='Mês',
        yaxis_title='Volume (hm³)',
        legend_title='Variáveis',
        hovermode='x unified',
        template='plotly_white'
    )

    st.plotly_chart(fig, use_container_width=True)

    df_resultados = pd.DataFrame({
        'Mês': meses,
        'Volume (hm³)': resultados['volumes'],
        'Retirada (hm³)': resultados['retiradas'],
        'Evaporação (hm³)': resultados['evaporacao']
    })
    st.dataframe(df_resultados)

    csv = df_resultados.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📀 Baixar CSV",
        data=csv,
        file_name=f'simulacao_{nome_reservatorio}.csv',
        mime='text/csv'
    )

    pdf_file = gerar_relatorio_pdf(nome_reservatorio, resultados)
    st.download_button(
        label="📄 Baixar Relatório em PDF",
        data=pdf_file,
        file_name=f'relatorio_{nome_reservatorio}.pdf',
        mime='application/pdf'
    )

def main():
    st.title("💧 Simulador de Reservatórios - Dados Fixos")
    cav, evaporacao, acudes = carregar_dados()

    nomes_acudes = acudes['CORPO'].tolist()
    nome_escolhido = st.selectbox("Selecione um açude para simular:", nomes_acudes)

    dados_acude = acudes[acudes['CORPO'] == nome_escolhido].iloc[0]
    cod_acude = dados_acude['COD']
    est_evap = dados_acude['Est. Evap.']
    volume_inicial = dados_acude['CAPAC (m³)'] / 1e6  # m3 para hm3

    curva_av = cav[cav['COD'] == cod_acude][['COTA', 'area', 'volume']]
    curva_av = curva_av.rename(columns={'area': 'area', 'volume': 'volume'})

    evaporacao_est = evaporacao[evaporacao['COD'] == est_evap]
    evaporacao_mm = evaporacao_est.iloc[0][['JAN','FEV','MAR','ABR','MAI','JUN','JUL','AGO','SET','OUT','NOV','DEZ']].values.astype(float)

    meses = len(evaporacao_mm)
    afluencias = st.number_input("Afluência mensal (hm³)", value=1.0, step=0.1) * np.ones(meses)
    demandas = st.number_input("Demanda mensal (hm³)", value=1.0, step=0.1) * np.ones(meses)

    if st.button("▶️ Executar simulação"):
        resultados = simular_reservatorio(volume_inicial, curva_av, afluencias, demandas, evaporacao_mm)
        display_results(nome_escolhido, resultados)

main()
