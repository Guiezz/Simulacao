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
    vazoes = pd.read_excel(caminho, sheet_name="vazoes")  # Nova aba de vazões
    return cav, evaporacao, acudes, vazoes


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
        a = polinomio_area(v_ant) * 1e6  # converte km² para m²
        a = max(a, 0)
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


def mostrar_dados_vazao(vazoes, cod_acude, nome_acude):
    st.subheader(f"📊 Dados Históricos de Vazão - {nome_acude}")

    # Filtrar dados para o açude específico
    dados_vazao = vazoes[vazoes['COD'] == cod_acude]

    if dados_vazao.empty:
        st.warning(f"Não foram encontrados dados de vazão para o açude {nome_acude}")
        return

    # Selecionar ano para visualização
    anos_disponiveis = dados_vazao['ANO'].unique()
    ano_selecionado = st.selectbox("Selecione o ano para visualizar:", anos_disponiveis)

    # Filtrar dados para o ano selecionado
    dados_ano = dados_vazao[dados_vazao['ANO'] == ano_selecionado]

    if dados_ano.empty:
        st.warning(f"Não há dados para o ano {ano_selecionado}")
        return

    # Preparar dados para visualização
    meses = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']
    valores = dados_ano[meses].values[0]

    # Criar gráfico
    fig = go.Figure()
    fig.add_trace(go.Bar(x=meses, y=valores, name='Vazão (hm³)'))

    fig.update_layout(
        title=f'Vazão Mensal - {nome_acude} ({ano_selecionado})',
        xaxis_title='Mês',
        yaxis_title='Vazão (hm³)',
        template='plotly_white'
    )

    st.plotly_chart(fig, use_container_width=True)

    # Mostrar tabela de dados
    st.write(f"Valores detalhados para {ano_selecionado}:")
    dados_tabela = pd.DataFrame({
        'Mês': meses,
        'Vazão (hm³)': valores
    })
    st.dataframe(dados_tabela)

    # Opção para download
    csv = dados_tabela.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Baixar dados de vazão",
        data=csv,
        file_name=f'vazao_{nome_acude}_{ano_selecionado}.csv',
        mime='text/csv'
    )


def main():
    st.title("💧 Simulador de Reservatórios - Dados Fixos")
    cav, evaporacao, acudes, vazoes = carregar_dados()

    nomes_acudes = acudes['CORPO'].tolist()
    nome_escolhido = st.selectbox("Selecione um açude para simular:", nomes_acudes)

    # Criando abas para separação de funcionalidades
    tab1, tab2 = st.tabs(["📊 Simulação", "📚 Dados Históricos"])

    with tab1:
        st.header("Simulação de Reservatório")
        dados_acude = acudes[acudes['CORPO'] == nome_escolhido].iloc[0]
        cod_acude = dados_acude['COD']
        est_evap = dados_acude['Est. Evap.']
        volume_inicial = dados_acude['CAPAC (m³)'] / 1e6  # m3 para hm3

        curva_av = cav[cav['COD'] == cod_acude][['COTA', 'area', 'volume']]
        curva_av = curva_av.rename(columns={'area': 'area', 'volume': 'volume'})

        evaporacao_est = evaporacao[evaporacao['COD'] == est_evap]
        evaporacao_mm = evaporacao_est.iloc[0][
            ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']].values.astype(float)

        meses = len(evaporacao_mm)

        st.subheader("⚙️ Parâmetros de Simulação")
        opcao_vazao = st.radio("Tipo de entrada de vazão:",
                               ["Valor Constante", "Dados Históricos"])

        if opcao_vazao == "Valor Constante":
            afluencias = st.number_input("Afluência mensal (hm³)", value=1.0, step=0.1) * np.ones(meses)
            demandas = st.number_input("Demanda mensal (hm³)", value=1.0, step=0.1) * np.ones(meses)
        else:
            dados_vazao_acude = vazoes[vazoes['COD'] == cod_acude]
            if dados_vazao_acude.empty:
                st.warning("Não há dados históricos de vazão para este açude. Usando valor constante.")
                afluencias = st.number_input("Afluência mensal (hm³)", value=1.0, step=0.1) * np.ones(meses)
                demandas = st.number_input("Demanda mensal (hm³)", value=1.0, step=0.1) * np.ones(meses)
            else:
                anos_disponiveis = dados_vazao_acude['ANO'].unique()
                ano_selecionado = st.selectbox("Selecione o ano para usar dados de vazão:", anos_disponiveis)
                dados_ano = dados_vazao_acude[dados_vazao_acude['ANO'] == ano_selecionado]
                afluencias = \
                dados_ano[['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']].values[
                    0]
                st.info(f"Usando dados de vazão de {ano_selecionado}")
                demanda_constante = st.number_input("Demanda mensal constante (hm³)", value=1.0, step=0.1)
                demandas = demanda_constante * np.ones(meses)

        if st.button("▶️ Executar simulação", key="simulate_button"):
            resultados = simular_reservatorio(volume_inicial, curva_av, afluencias, demandas, evaporacao_mm)
            display_results(nome_escolhido, resultados)

    with tab2:
        st.header("Dados Históricos de Vazão")
        if 'dados_acude' in locals():
            mostrar_dados_vazao(vazoes, cod_acude, nome_escolhido)
        else:
            st.info("Selecione um açude na aba de Simulação primeiro")


main()