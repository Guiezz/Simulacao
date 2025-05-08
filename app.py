import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

def simular_reservatorio(volume_inicial, curva_av, afluencias, demandas, evaporacao_mm, restricoes=None):
    vol = curva_av['Volume (hm³)'].values
    area = curva_av['Área (km²)'].values
    coef_polinomio = np.polyfit(vol, area, deg=3)
    area_func = np.poly1d(coef_polinomio)

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
        a = area_func(v_ant) * 1e6
        a = max(a, 0)
        evap_m = evaporacao_mm[t] / 1000
        evap_volume = (a * evap_m) / 1e6

        demanda = demandas[t]
        retirada = min(demanda, max(0, v_ant + afluencias[t] - evap_volume))
        v_atual = v_ant + afluencias[t] - evap_volume - retirada
        v_atual = max(v_atual, 0)
        v_atual = min(v_atual, volume_max)

        if v_atual < volume_min_oper:
            alertas.append(f"Mês {t+1}: volume abaixo do mínimo operacional ({v_atual:.2f} hm³)")
        if v_atual < volume_morto:
            alertas.append(f"Mês {t+1}: volume abaixo do volume morto ({v_atual:.2f} hm³)")

        evap_hm3[t] = evap_volume
        volumes[t + 1] = v_atual
        retiradas[t] = retirada

    return {
        'volumes': volumes[1:],
        'retiradas': retiradas,
        'evaporacao': evap_hm3,
        'alertas': alertas
    }

def display_results(nome_reservatorio, resultados):
    meses = np.arange(1, len(resultados['volumes']) + 1)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=meses, y=resultados['volumes'], mode='lines+markers', name='Volume (hm³)'))
    fig.add_trace(go.Scatter(x=meses, y=resultados['retiradas'], mode='lines+markers', name='Retirada (hm³)', line=dict(dash='dash')))
    fig.add_trace(go.Scatter(x=meses, y=resultados['evaporacao'], mode='lines+markers', name='Evaporação (hm³)', line=dict(dash='dot')))

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
        label="📥 Baixar CSV",
        data=csv,
        file_name=f'simulacao_{nome_reservatorio}.csv',
        mime='text/csv'
    )

    if resultados['alertas']:
        st.warning("⚠️ Alertas durante a simulação:")
        for alerta in resultados['alertas']:
            st.text(alerta)

def main():
    st.title("💧 Simulador de Reservatórios com Restrições Operacionais")

    aba_upload, aba_resultados = st.tabs(["📂 Upload e Configuração", "📊 Resultados"])

    with aba_upload:
        arquivos = st.file_uploader("Enviar arquivos Excel (.xlsx)", type="xlsx", accept_multiple_files=True)
        dados_reservatorios = {}

        if arquivos:
            for arquivo in arquivos:
                nome_reservatorio = arquivo.name.replace(".xlsx", "")
                try:
                    curva_av = pd.read_excel(arquivo, sheet_name='CurvaAV')
                    afluencias_df = pd.read_excel(arquivo, sheet_name='Afluencias')
                    demandas_df = pd.read_excel(arquivo, sheet_name='Demandas')
                    evaporacao_df = pd.read_excel(arquivo, sheet_name='Evaporacao')

                    if not all(col in afluencias_df.columns for col in ['Afluência (hm³)']) or \
                       not all(col in demandas_df.columns for col in ['Demanda (hm³)']) or \
                       not all(col in evaporacao_df.columns for col in ['Evaporação (mm)']):
                        st.error(f"{nome_reservatorio}: Nomes de colunas incorretos.")
                        continue

                    if len(afluencias_df) != len(demandas_df) or len(demandas_df) != len(evaporacao_df):
                        st.error(f"{nome_reservatorio}: Séries com comprimentos diferentes.")
                        continue

                    if afluencias_df.isnull().values.any() or demandas_df.isnull().values.any() or evaporacao_df.isnull().values.any():
                        st.error(f"{nome_reservatorio}: Há valores nulos nas séries.")
                        continue

                    afluencias = afluencias_df['Afluência (hm³)'].astype(float).values
                    demandas = demandas_df['Demanda (hm³)'].astype(float).values
                    evaporacao_mm = evaporacao_df['Evaporação (mm)'].astype(float).values

                    restricoes = None
                    try:
                        restricoes_raw = pd.read_excel(arquivo, sheet_name='Restricoes')
                        st.markdown(f"**Editar restrições operacionais - {nome_reservatorio}**")
                        restricoes = st.data_editor(restricoes_raw, num_rows="dynamic", key=f"restricoes_{nome_reservatorio}")
                    except:
                        st.info(f"{nome_reservatorio}: Sem aba 'Restricoes'.")

                    volume_inicial = st.number_input(
                        f"Volume inicial - {nome_reservatorio} (hm³)",
                        min_value=0.0,
                        value=float(curva_av['Volume (hm³)'].min()),
                        key=f"volini_{nome_reservatorio}"
                    )

                    dados_reservatorios[nome_reservatorio] = {
                        "curva_av": curva_av,
                        "afluencias": afluencias,
                        "demandas": demandas,
                        "evaporacao_mm": evaporacao_mm,
                        "restricoes": restricoes,
                        "volume_inicial": volume_inicial
                    }

                except Exception as e:
                    st.error(f"Erro ao processar {nome_reservatorio}: {e}")

            if st.button("▶️ Executar simulações"):
                st.session_state.resultados = {}
                for nome, dados in dados_reservatorios.items():
                    resultado = simular_reservatorio(
                        dados["volume_inicial"],
                        dados["curva_av"],
                        dados["afluencias"],
                        dados["demandas"],
                        dados["evaporacao_mm"],
                        dados["restricoes"]
                    )
                    st.session_state.resultados[nome] = resultado
                st.success("Simulações concluídas! Vá para a aba '📊 Resultados'.")

    with aba_resultados:
        if "resultados" in st.session_state and st.session_state.resultados:
            tabs = st.tabs(list(st.session_state.resultados.keys()))
            for tab, nome_reservatorio in zip(tabs, st.session_state.resultados.keys()):
                with tab:
                    display_results(nome_reservatorio, st.session_state.resultados[nome_reservatorio])
        else:
            st.info("Nenhuma simulação foi executada ainda. Carregue os dados e clique em 'Executar simulações' na aba anterior.")

main()
