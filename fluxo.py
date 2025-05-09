import streamlit as st
import pandas as pd
import altair as alt
import numpy as np

st.set_page_config(page_title="Detector de Fluxo Adaptativo", layout="wide")
st.title("📊 Detector de Absorções, Reversões e Rompimentos Adaptativo")
st.markdown("Detecta **absorções**, **reversões** e **rompimentos** em dados de Times & Trades com ajuste dinâmico de janela e limite de volume.")

uploaded_file = st.file_uploader("📎 Faça o upload da planilha (.xlsx)", type="xlsx")

if uploaded_file:
    df = pd.read_excel(uploaded_file)
    df = df.rename(columns={
        'Data': 'horario',
        'Valor': 'preco',
        'Quantidade': 'quantidade',
        'Agressor': 'agressor'
    })

    # Robustez na conversão de horário e tratamento da coluna agressor
    try:
        # Tenta converter diretamente
        df['horario'] = pd.to_datetime(df['horario'])
    except (ValueError, TypeError):
        # Fallback para formato específico se a conversão direta falhar
        df['horario'] = pd.to_datetime(df['horario'].astype(str), format="%H:%M:%S", errors='coerce')

    df = df.dropna(subset=['horario']) # Remove linhas onde a conversão de horário falhou
    if 'agressor' in df.columns:
        df['agressor'] = df['agressor'].astype(str).str.lower() # Padroniza agressor para minúsculas
    else:
        st.error("Coluna 'Agressor' não encontrada na planilha. Verifique os nomes das colunas.")
        st.stop()

    st.success("✅ Planilha carregada com sucesso!")

    st.sidebar.header("⚙️ Parâmetros de Análise")
    limite_volume_inicial = st.sidebar.slider(
        "Volume mínimo inicial para evento",
        100, 10000, 1000, step=100,
        help="Volume mínimo base para considerar um evento significativo."
    )
    fator_desvio_volume = st.sidebar.slider(
        "Fator de desvio padrão do volume",
        1.0, 5.0, 2.0, step=0.1,
        help="Multiplicador do desvio padrão para definir os limites de volume para ajuste da janela."
    )
    janela_inicial = st.sidebar.slider(
        "Tamanho da janela inicial (trades)",
        5, 100, 20,
        help="Número inicial de trades para compor uma janela de análise."
    )
    lookback_period_stats = st.sidebar.slider(
        "Período para cálculo de stats de volume (trades)",
        50, 500, 100, step=10,
        help="Número de trades anteriores para calcular a média e desvio padrão do volume."
    )

    st.sidebar.subheader("⚙️ Parâmetros de Inversão por Absorção")
    lookback_preco_extremos = st.sidebar.slider(
        "Janelas para extremos de preço",
        20, 200, 50, step=10,
        help="Número de janelas recentes para calcular máximas e mínimas locais."
    )
    pct_proximidade = st.sidebar.slider(
        "Percentual de proximidade do extremo",
        0.01, 0.10, 0.02, step=0.01,
        help="Percentual da variação recente para considerar o preço 'próximo' de um topo ou fundo."
    )


    def detectar_eventos_adaptativo(df_original, limite_vol_inicial, fator_dev_vol, jan_inicial, lookback_stats, lookback_preco_extremos=50, pct_proximidade=0.02):
        eventos = []
        max_previa_historica = None
        min_previa_historica = None
        limite_volume = limite_vol_inicial
        janela = jan_inicial
        evento_anterior = None
        absorcoes_recentes = [] # Lista para rastrear absorções recentes (tipo e preço)
        precos_recentes = df_original['preco'].rolling(window=lookback_preco_extremos, min_periods=1).agg(['max', 'min'])

        for i in range(len(df_original) - janela + 1):
            trecho = df_original.iloc[i:i+janela]
            if trecho.empty:
                continue

            compradores = trecho[trecho['agressor'] == 'comprador']
            vendedores = trecho[trecho['agressor'] == 'vendedor']

            preco_max_trecho = trecho['preco'].max()
            preco_min_trecho = trecho['preco'].min()
            preco_medio_trecho = trecho['preco'].mean()
            vol_total_trecho = trecho['quantidade'].sum()
            vol_compra_trecho = compradores['quantidade'].sum()
            vol_venda_trecho = vendedores['quantidade'].sum()

            tipo_evento = None

            # 1. Absorções Passivas
            modo_preco_vendedores = vendedores['preco'].mode()
            if not modo_preco_vendedores.empty and vol_venda_trecho > limite_volume and preco_min_trecho == modo_preco_vendedores.iloc[0]:
                tipo_evento = 'Absorção Passiva de Compra'

            modo_preco_compradores = compradores['preco'].mode()
            if not tipo_evento and not modo_preco_compradores.empty and vol_compra_trecho > limite_volume and preco_max_trecho == modo_preco_compradores.iloc[0]:
                tipo_evento = 'Absorção Passiva de Venda'

            # 2. Absorções Ativas
            if not tipo_evento and vol_compra_trecho > limite_volume and preco_max_trecho > trecho['preco'].iloc[0] and preco_max_trecho >= preco_max_trecho:
                tipo_evento = 'Absorção Ativa de Compra'

            if not tipo_evento and vol_venda_trecho > limite_volume and preco_min_trecho < trecho['preco'].iloc[0] and preco_min_trecho <= preco_min_trecho:
                tipo_evento = 'Absorção Ativa de Venda'

            # Atualizar lista de absorções recentes
            if tipo_evento and 'Absorção' in tipo_evento:
                absorcoes_recentes.append({'tipo': tipo_evento, 'preco': preco_medio_trecho, 'indice': i})
                if len(absorcoes_recentes) > 3: # Manter apenas as 3 mais recentes
                    absorcoes_recentes.pop(0)

            # Verificar potencial inversão por clímax de absorção
            if precos_recentes is not None and i >= lookback_preco_extremos:
                max_recente = precos_recentes['max'].iloc[i]
                min_recente = precos_recentes['min'].iloc[i]
                preco_atual = preco_medio_trecho

                range_preco = max_recente - min_recente
                if range_preco > 1e-9: # Evitar divisão por zero
                    acima_pct = (max_recente - preco_atual) / range_preco
                    abaixo_pct = (preco_atual - min_recente) / range_preco

                    proximo_topo = acima_pct <= pct_proximidade
                    proximo_fundo = abaixo_pct <= pct_proximidade

                    if proximo_fundo and len(absorcoes_recentes) >= 2:
                        tipos_absorcao = [a['tipo'] for a in absorcoes_recentes[-2:]]
                        if all('Venda' in tipo for tipo in tipos_absorcao) and 'Compra' in tipo_evento and vol_compra_trecho > limite_volume * 0.8 and len(absorcoes_recentes) > 0 and isinstance(absorcoes_recentes[-1].get('indice'), (int, float)) and abs(absorcoes_recentes[-1]['indice'] - i) < 2 * janela:
                            tipo_evento = 'Potencial Inversão por Clímax de Absorção (Fundo)'
                    elif proximo_topo and len(absorcoes_recentes) >= 2:
                        tipos_absorcao = [a['tipo'] for a in absorcoes_recentes[-2:]]
                        if all('Compra' in tipo for tipo in tipos_absorcao) and 'Venda' in tipo_evento and vol_venda_trecho > limite_volume * 0.8 and len(absorcoes_recentes) > 0 and isinstance(absorcoes_recentes[-1].get('indice'), (int, float)) and abs(absorcoes_recentes[-1]['indice'] - i) < 2 * janela:
                            tipo_evento = 'Potencial Inversão por Clímax de Absorção (Topo)'

            # 3. Reversões (com prioridade menor que clímax de absorção)
            if not tipo_evento:
                if i >= janela:
                    trecho_anterior = df_original.iloc[i-janela:i]
                    if not trecho_anterior.empty:
                        vol_ant_compra = trecho_anterior[trecho_anterior['agressor'] == 'comprador']['quantidade'].sum()
                        vol_ant_venda = trecho_anterior[trecho_anterior['agressor'] == 'vendedor']['quantidade'].sum()
                        if vol_ant_venda > limite_volume and vol_compra_trecho > limite_volume and vol_compra_trecho > vol_ant_venda:
                            tipo_evento = 'Reversão: Venda → Compra'
                        elif vol_ant_compra > limite_volume and vol_venda_trecho > limite_volume and vol_venda_trecho > vol_ant_compra:
                            tipo_evento = 'Reversão: Compra → Venda'

            # 4. Rompimentos (com prioridade ainda menor)
            if not tipo_evento and max_previa_historica is not None and preco_max_trecho > max_previa_historica and vol_compra_trecho > limite_volume:
                tipo_evento = 'Rompimento de Topo'

            if not tipo_evento and min_previa_historica is not None and preco_min_trecho < min_previa_historica and vol_venda_trecho > limite_volume:
                tipo_evento = 'Rompimento de Fundo'

            # Atualiza o histórico de máximas e mínimas
            if max_previa_historica is None:
                max_previa_historica = preco_max_trecho
            else:
                max_previa_historica = max(max_previa_historica, preco_max_trecho)

            if min_previa_historica is None:
                min_previa_historica = preco_min_trecho
            else:
                min_previa_historica = min(min_previa_historica, preco_min_trecho)

            if tipo_evento:
                eventos.append({
                    'inicio': trecho['horario'].iloc[0],
                    'fim': trecho['horario'].iloc[-1],
                    'tipo': tipo_evento,
                    'preco_medio': round(preco_medio_trecho, 2),
                    'volume_total': vol_total_trecho,
                    'janela_usada': janela,
                    'limite_vol_usado': round(limite_volume,0)
                })
                evento_anterior = tipo_evento
            else:
                evento_anterior = None

            # Ajuste Dinâmico da Janela e Limite de Volume
            nova_janela = janela
            novo_limite_volume = limite_volume

            if i > lookback_stats :
                start_index_stats = max(0, i - lookback_stats)
                recent_volume_series = df_original['quantidade'].iloc[start_index_stats:i]

                if not recent_volume_series.empty:
                    vol_medio_recente = recent_volume_series.mean()
                    desvio_padrao_volume_recente = recent_volume_series.std()

                    if pd.notna(vol_medio_recente) and pd.notna(desvio_padrao_volume_recente) and desvio_padrao_volume_recente > 1e-6:
                        vol_upper_band = vol_medio_recente + fator_dev_vol * desvio_padrao_volume_recente
                        vol_lower_band = vol_medio_recente - fator_dev_vol * desvio_padrao_volume_recente

                        if vol_total_trecho > vol_upper_band:
                            nova_janela = max(5, int(janela * 0.75))
                            novo_limite_volume = max(limite_vol_inicial, vol_upper_band * 0.7)
                        elif vol_total_trecho < vol_lower_band and vol_lower_band > 0:
                            nova_janela = max(5, int(janela * 0.85))
                            novo_limite_volume = max(limite_vol_inicial * 0.5, vol_lower_band * 1.1)
                        else:
                            nova_janela = min(janela_inicial + int(janela_inicial * 0.25), janela + 1)
                            novo_limite_volume = limite_vol_inicial
                    else:
                        nova_janela = janela_inicial
                        novo_limite_volume = limite_vol_inicial
                else:
                    nova_janela = janela_inicial
                    novo_limite_volume = limite_vol_inicial
            else:
                nova_janela = janela_inicial
                novo_limite_volume = limite_vol_inicial

            janela = nova_janela
            limite_volume = novo_limite_volume

        return pd.DataFrame(eventos)

    if uploaded_file:
        eventos_df = detectar_eventos_adaptativo(df, limite_volume_inicial, fator_desvio_volume, janela_inicial, lookback_period_stats, lookback_preco_extremos, pct_proximidade)

        st.subheader("📋 Eventos Detectados")
        if eventos_df.empty:
            st.warning("Nenhum evento detectado com os parâmetros atuais.")
        else:
            st.dataframe(eventos_df)

            st.subheader("📈 Gráfico com Eventos (Altair)")

            base = alt.Chart(df).mark_line(color='lightblue').encode(
                x=alt.X('horario:T', title='Horário'),
                y=alt.Y('preco:Q', title='Preço', scale=alt.Scale(zero=False)),
                tooltip=['horario', 'preco', 'quantidade', 'agressor']
            ).interactive()

            cores_eventos = {
                'Absorção Passiva de Compra': 'darkblue',
                'Absorção Passiva de Venda': 'darkred',
                'Absorção Ativa de Compra': 'green',
                'Absorção Ativa de Venda': 'orange',
                'Reversão: Venda → Compra': 'purple',
                'Reversão: Compra → Venda': 'brown',
                'Rompimento de Topo': 'lime',
                'Rompimento de Fundo': 'maroon',
                'Potencial Inversão por Clímax de Absorção (Fundo)': 'mediumpurple',
                'Potencial Inversão por Clímax de Absorção (Topo)': 'sienna'
            }

            event_marks = alt.Chart(eventos_df).mark_rule(size=2, opacity=0.7).encode(
                x='inicio:T',
                color=alt.Color('tipo:N',
                                scale=alt.Scale(domain=list(cores_eventos.keys()),
                                                range=list(cores_eventos.values())),
                legend=alt.Legend(title="Tipos de Evento")),
                tooltip=['tipo', 'inicio', 'fim', 'preco_medio', 'volume_total', 'janela_usada', 'limite_vol_usado']
            )

            event_text = event_marks.mark_text(
                align='left',
                baseline='middle',
                dx=7,
                dy=-7,
                angle=0
            ).encode(
                text='tipo:N'
            )

            chart = (base + event_marks + event_text).properties(
                width=700,
                height=500,
                title="Preços ao Longo do Tempo com Eventos Detectados"
            )
            st.altair_chart(chart, use_container_width=True)

else:
    st.info("ℹ️ Por favor, faça o upload de uma planilha Excel (.xlsx) para iniciar a análise.")
