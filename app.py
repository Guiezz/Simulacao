import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from io import BytesIO

@st.cache_data
def carregar_dados():
    caminho = "testeAcudes.xlsx"
    cav = pd.read_excel(caminho, sheet_name="cav")
    evaporacao = pd.read_excel(caminho, sheet_name="evaporacao")
    acudes = pd.read_excel(caminho, sheet_name="acudes")
    vazoes = pd.read_excel(caminho, sheet_name="vazoes")
    return cav, evaporacao, acudes, vazoes

# Esta função realiza a simulação mensal do balanço hídrico do reservatório, considerando:
# - Volume inicial
# - Curva cota-área-volume (curva_av)
# - Séries de afluência, demanda e evaporação
# - Restrições operacionais: volume máximo, mínimo operacional e volume morto (se fornecidas)
def simular_reservatorio(volume_inicial, curva_av, afluencias, demandas, evaporacao_mm, restricoes=None):
    # Tratamento da curva para garantir que volume e área são numéricos e não nulos
    curva_av['volume'] = pd.to_numeric(curva_av['volume'], errors='coerce')
    curva_av['area'] = pd.to_numeric(curva_av['area'], errors='coerce')
    curva_av = curva_av.dropna(subset=['volume', 'area'])

    vol = curva_av['volume'].values
    area = curva_av['area'].values

    # Ajusta um polinômio para estimar área em função do volume
    coef_polinomio = np.polyfit(vol, area, deg=3)
    polinomio_area = np.poly1d(coef_polinomio)

    # Valores padrão de restrições
    volume_max = np.inf
    volume_min_oper = 0
    volume_morto = 0

    # Se houver DataFrame de restrições, atualiza os valores com base nele
    if restricoes is not None:
        try:
            restricoes_dict = restricoes.set_index('Parâmetro')['Valor (hm³)'].to_dict()
            volume_max = restricoes_dict.get('Volume Máximo', volume_max)
            volume_min_oper = restricoes_dict.get('Volume Mínimo Operacional', volume_min_oper)
            volume_morto = restricoes_dict.get('Volume Morto', volume_morto)
        except Exception as e:
            st.warning(f"Erro ao ler restrições operacionais: {e}")

    n_meses = len(afluencias)
    volumes = np.zeros(n_meses + 1)       # Armazena volume no início de cada mês
    evap_hm3 = np.zeros(n_meses)          # Armazena perdas por evaporação
    retiradas = np.zeros(n_meses)         # Armazena retiradas reais
    vertimentos = np.zeros(n_meses)       # Armazena volumes vertidos (excedentes)
    alertas = []                          # Lista de mensagens de alerta

    volumes[0] = volume_inicial

    for t in range(n_meses):
        v_ant = volumes[t]
        a = polinomio_area(v_ant) * 1e6  # Convertendo km² para m²
        a = max(a, 0)
        evap_m = evaporacao_mm[t] / 1000  # mm para m
        evap_volume = (a * evap_m) / 1e6   # m³ para hm³

        # Conversão de m³/s para hm³/mês
        demanda_hm3 = (demandas[t] * 30 * 24 * 60 * 60) / 1e6
        afluencia_hm3 = (afluencias[t] * 30 * 24 * 60 * 60) / 1e6

        # Define quanto pode ser retirado com base no saldo hídrico e volume morto
        retirada = min(demanda_hm3, max(0, v_ant + afluencia_hm3 - evap_volume - volume_morto))

        # Volume potencial antes de considerar vertimento
        v_potencial = v_ant + afluencia_hm3 - evap_volume - retirada
        v_potencial = max(v_potencial, 0)

        # Cálculo do vertimento (excesso de água acima do volume máximo permitido)
        vertimento_t = max(0, v_potencial - volume_max)
        vertimentos[t] = vertimento_t

        # Volume final após possível vertimento
        v_atual = v_potencial - vertimento_t

        # Alertas para volumes abaixo de limites operacionais
        if v_atual < volume_min_oper:
            alertas.append(f"Mês {t + 1}: volume ({v_atual:.2f} hm³) abaixo do mínimo operacional.")
        if v_atual < volume_morto:
            alertas.append(f"Mês {t + 1}: volume ({v_atual:.2f} hm³) abaixo do volume morto.")

        # Armazena os resultados do mês
        evap_hm3[t] = evap_volume
        volumes[t + 1] = v_atual
        retiradas[t] = retirada

    return {
        'volumes': volumes[1:],
        'retiradas': retiradas,
        'evaporacao': evap_hm3,
        'vertimento': vertimentos,
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
    fig.add_trace(go.Scatter(x=meses, y=resultados['retiradas'], mode='lines+markers', name='Retirada (hm³)', line=dict(dash='dash')))
    fig.add_trace(go.Scatter(x=meses, y=resultados['evaporacao'], mode='lines+markers', name='Evaporação (hm³)', line=dict(dash='dot')))
    fig.add_trace(go.Scatter(x=meses, y=resultados['vertimento'], mode='lines+markers', name='Vertimento (hm³)', line=dict(dash='dashdot')))  # NOVO

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
        'Evaporação (hm³)': resultados['evaporacao'],
        'Vertimento (hm³)': resultados['vertimento']  # NOVO
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

    dados_vazao = vazoes[vazoes['COD'] == cod_acude]
    if dados_vazao.empty:
        st.warning(f"Não foram encontrados dados de vazão para o açude {nome_acude}")
        return

    meses_ordem = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']
    datas_expandidas = []

    for _, row in dados_vazao.iterrows():
        ano = int(row['ANO'])
        for idx, mes_nome in enumerate(meses_ordem, start=1):
            try:
                valor = float(row[mes_nome])
                data = pd.Timestamp(year=ano, month=idx, day=1)
                datas_expandidas.append({'DATA': data, 'VAZAO': valor})
            except:
                continue

    df_vazao_mes = pd.DataFrame(datas_expandidas).sort_values('DATA')

    # Lista de anos válidos
    anos_validos = sorted([ano for ano in df_vazao_mes['DATA'].dt.year.unique() if ano != 1910])
    col_meses = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']
    meses_dict = {nome: idx for idx, nome in enumerate(col_meses)}  # para montar datas

    col1, col2 = st.columns(2)

    with col1:
        ano_inicio = st.selectbox("Ano inicial:", anos_validos, index=0, key="ano_inicio_hist")
        mes_inicio = st.selectbox("Mês inicial:", col_meses, index=0, key="mes_inicio_hist")
    with col2:
        ano_fim = st.selectbox("Ano final:", anos_validos, index=len(anos_validos) - 1, key="ano_fim_hist")
        mes_fim = st.selectbox("Mês final:", col_meses, index=11, key="mes_fim_hist")

    # Constrói intervalo de datas com base nas seleções
    data_inicio = pd.Timestamp(year=ano_inicio, month=meses_dict[mes_inicio] + 1, day=1)
    data_fim = pd.Timestamp(year=ano_fim, month=meses_dict[mes_fim] + 1, day=1)

    if data_inicio > data_fim:
        st.warning("A data de início deve ser anterior à data de fim.")
        return

    df_filtrado = df_vazao_mes[(df_vazao_mes['DATA'] >= data_inicio) &
                               (df_vazao_mes['DATA'] <= data_fim)]

    if df_filtrado.empty:
        st.warning("Não há dados para o intervalo selecionado.")
        return

    # Gráfico
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_filtrado['DATA'], y=df_filtrado['VAZAO'], mode='lines+markers', name='Vazão (m³/s)'))

    fig.update_layout(
        title=f'Vazão de {nome_acude} de {data_inicio.strftime("%b/%Y")} a {data_fim.strftime("%b/%Y")}',
        xaxis_title='Data',
        yaxis_title='Vazão (m³/s)',
        template='plotly_white'
    )

    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(df_filtrado.rename(columns={'DATA': 'Data', 'VAZAO': 'Vazão (m³/s)'}))

    csv = df_filtrado.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Baixar dados de vazão",
        data=csv,
        file_name=f'vazao_{nome_acude}_{data_inicio.strftime("%Y%m")}_{data_fim.strftime("%Y%m")}.csv',
        mime='text/csv'
    )


def main():
    st.title("💧 Simulador de Reservatórios")
    cav, evaporacao, acudes, vazoes = carregar_dados()

    nomes_acudes = acudes['CORPO'].tolist()
    nome_escolhido = st.selectbox("Selecione um açude para simular:", nomes_acudes)

    tab1, tab2 = st.tabs(["📊 Simulação", "📚 Dados Históricos"])

    def converter_m3s_para_hm3mes(valor_m3s):
        segundos_por_mes = 30.44 * 24 * 60 * 60
        return (valor_m3s * segundos_por_mes) / 1e6

    with tab1:
        st.header("Simulação de Reservatório")
        dados_acude = acudes[acudes['CORPO'] == nome_escolhido].iloc[0]
        cod_acude = dados_acude['COD']
        est_evap = dados_acude['Est. Evap.']
        volume_inicial = dados_acude['CAPAC (m³)'] / 1e6


        curva_av = cav[cav['COD'] == cod_acude][['COTA', 'area', 'volume']]
        curva_av = curva_av.rename(columns={'area': 'area', 'volume': 'volume'})

        evaporacao_est = evaporacao[evaporacao['COD'] == est_evap]
        evaporacao_mm = evaporacao_est.iloc[0][
            ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']
        ].values.astype(float)

        st.subheader("⚙️ Parâmetros de Simulação")
        opcao_vazao = st.radio("Tipo de entrada de vazão:", ["Valor Constante", "Dados Históricos"])

        meses = 12  # padrão, caso valor constante

        if opcao_vazao == "Valor Constante":
            meses = st.number_input("Número de meses a simular", min_value=1, max_value=120, value=12, step=1)
            afluencia_m3s = st.number_input("Afluência constante (m³/s)", value=1.0, step=0.1)
            demanda_m3s = st.number_input("Retirada mensal constante (m³/s)", value=1.0, step=0.1)
            fator_conv = 2.628e-6  # m³/s para hm³/mês
            afluencias = afluencia_m3s * fator_conv * np.ones(meses)
            demandas = demanda_m3s * fator_conv * np.ones(meses)
            evaporacao_mm = np.resize(evaporacao_mm, meses)
        else:
            dados_vazao_acude = vazoes[vazoes['COD'] == cod_acude]
            if dados_vazao_acude.empty:
                st.warning("Não há dados históricos de vazão para este açude. Usando valor constante.")
                meses = 12
                afluencia_m3s = st.number_input("Afluência constante (m³/s)", value=1.0, step=0.1)
                demanda_m3s = st.number_input("Demanda constante (m³/s)", value=1.0, step=0.1)
                fator_conv = 2.628e-6
                afluencias = afluencia_m3s * fator_conv * np.ones(meses)
                demandas = demanda_m3s * fator_conv * np.ones(meses)
                evaporacao_mm = np.resize(evaporacao_mm, meses)
            else:
                anos_disponiveis = sorted([ano for ano in dados_vazao_acude['ANO'].unique() if ano != 1910])  # O ano de 1910 estava dando problema, optei por remover pois so tinha dados de 3 meses.
                col_meses = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']
                meses_dict = {nome: idx for idx, nome in enumerate(col_meses)}

                col1, col2 = st.columns(2)
                with col1:
                    ano_inicio = st.selectbox("Ano inicial:", anos_disponiveis, index=0)
                    mes_inicio = st.selectbox("Mês inicial:", col_meses, index=0)
                with col2:
                    ano_fim = st.selectbox("Ano final:", anos_disponiveis, index=len(anos_disponiveis) - 1)
                    mes_fim = st.selectbox("Mês final:", col_meses, index=11)

                # Construir vetor de afluência
                data_inicio = pd.Timestamp(year=ano_inicio, month=meses_dict[mes_inicio]+1, day=1)
                data_fim = pd.Timestamp(year=ano_fim, month=meses_dict[mes_fim]+1, day=1)
                datas_simulacao = pd.date_range(start=data_inicio, end=data_fim, freq='MS')

                afluencias = []
                for data in datas_simulacao:
                    linha = dados_vazao_acude[dados_vazao_acude['ANO'] == data.year]
                    if not linha.empty:
                        val = linha.iloc[0][col_meses[data.month - 1]]
                        afluencias.append(val)
                    else:
                        afluencias.append(0.0)  # ou usar np.nan e depois interpolar

                meses = len(afluencias)
                demanda_m3s = st.number_input("Retirada mensal constante (m³/s)", value=1.0, step=0.1)
                fator_conv = 2.628e-6
                demandas = demanda_m3s * fator_conv * np.ones(meses)

                evaporacao_mm = np.resize(evaporacao_mm, meses)

                st.info(f"Simulando de {mes_inicio}/{ano_inicio} até {mes_fim}/{ano_fim} ({meses} meses).")

        if st.button("▶️ Executar simulação", key="simulate_button"):
            # Extrai volume máximo diretamente da capacidade do açude em m³ e converte para hm³
            volume_maximo_hm3 = dados_acude['CAPAC (m³)'] / 1e6

            # Cria DataFrame de restrições contendo o volume máximo
            restricoes_df = pd.DataFrame({
                'Parâmetro': ['Volume Máximo'],
                'Valor (hm³)': [volume_maximo_hm3]
            })

            # Executa simulação com restrições
            resultados = simular_reservatorio(
                volume_inicial, curva_av, afluencias, demandas, evaporacao_mm,
                restricoes=restricoes_df
            )
            display_results(nome_escolhido, resultados)

    with tab2:
        st.header("Dados Históricos de Vazão")
        if 'dados_acude' in locals():
            mostrar_dados_vazao(vazoes, cod_acude, nome_escolhido)
        else:
            st.info("Selecione um açude na aba de Simulação primeiro")

main()
