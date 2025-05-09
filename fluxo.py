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
    limite_volume_inicial = st.sidebar.slider("Volume mínimo inicial para evento", 100, 10000, 1000, step=100, help="Volume mínimo base para considerar um evento significativo.")
    fator_desvio_volume = st.sidebar.slider("Fator de desvio padrão do volume", 1.0, 5.0, 2.0, step=0.1, help="Multiplicador do desvio padrão para definir os limites de volume para ajuste da janela.")
    janela_inicial = st.sidebar.slider("Tamanho da janela inicial (trades)", 5, 100, 20, help="Número inicial de trades para compor uma janela de análise.")
    lookback_period_stats = st.sidebar.slider("Período para cálculo de stats de volume (trades)", 50, 500, 100, step=10, help="Número de trades anteriores para calcular a média e desvio padrão do volume.")


    def detectar_eventos_adaptativo(df_original, limite_vol_inicial, fator_dev_vol, jan_inicial, lookback_stats):
        eventos = []
        # Inicializa max_previa e min_previa para o histórico de preços máximos e mínimos
        # Eles serão atualizados com os valores da *janela anterior* para avaliar rompimentos
        max_previa_historica = None
        min_previa_historica = None
        limite_volume = limite_vol_inicial
        janela = jan_inicial
        evento_anterior = None # Variável para lembrar o tipo de evento anterior

        # O loop principal itera sobre o DataFrame, fatiando-o em 'trechos' (janelas)
        # O range vai até len(df_original) - janela para garantir que haja dados suficientes para a última janela
        for i in range(len(df_original) - janela + 1):
            if i + janela > len(df_original): # Se a janela adaptativa cresceu e ultrapassaria o fim
                break

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

            tipo_evento = None # Evento detectado para a janela atual

            # --- Lógica de Detecção de Eventos ---
            # A ordem dessas verificações if/elif implica uma prioridade.
            # O primeiro tipo de evento que tiver suas condições satisfeitas será o registrado para esta janela.

            # 1. Absorções Passivas
            modo_preco_vendedores = vendedores['preco'].mode()
            if not modo_preco_vendedores.empty and vol_venda_trecho > limite_volume and preco_min_trecho == modo_preco_vendedores.iloc[0]:
                tipo_evento = 'Absorção Passiva de Compra'

            modo_preco_compradores = compradores['preco'].mode()
            if not tipo_evento and not modo_preco_compradores.empty and vol_compra_trecho > limite_volume and preco_max_trecho == modo_preco_compradores.iloc[0]:
                tipo_evento = 'Absorção Passiva de Venda'

            # 2. Absorções Ativas
            if not tipo_evento and vol_compra_trecho > limite_volume and preco_max_trecho > trecho['preco'].iloc[0] and preco_max_trecho >= preco_max_trecho: # Compradores ativos elevando o preço dentro da janela
                tipo_evento = 'Absorção Ativa de Compra'

            if not tipo_evento and vol_venda_trecho > limite_volume and preco_min_trecho < trecho['preco'].iloc[0] and preco_min_trecho <= preco_min_trecho: # Vendedores ativos baixando o preço dentro da janela
                tipo_evento = 'Absorção Ativa de Venda'

            # 3. Reversões (modificado para considerar o evento anterior)
            if i >= janela:
                trecho_anterior = df_original.iloc[i-janela:i]
                if not trecho_anterior.empty:
                    vol_ant_compra = trecho_anterior[trecho_anterior['agressor'] == 'comprador']['quantidade'].sum()
                    vol_ant_venda = trecho_anterior[trecho_anterior['agressor'] == 'vendedor']['quantidade'].sum()

                    if not tipo_evento and evento_anterior == 'Absorção Passiva de Venda' and vol_compra_trecho > limite_volume * 0.8 and vol_compra_trecho > vol_ant_venda * 1.2: # Ajuste os multiplicadores conforme necessário
                        tipo_evento = 'Reversão: Venda → Compra (Pós Absorção)'
                    elif not tipo_evento and evento_anterior == 'Absorção Passiva de Compra' and vol_venda_trecho > limite_volume * 0.8 and vol_venda_trecho > vol_ant_compra * 1.2:
                        tipo_evento = 'Reversão: Compra → Venda (Pós Absorção)'
                    elif not tipo_evento and vol_ant_venda > limite_volume and vol_compra_trecho > limite_volume and vol_compra_trecho > vol_ant_venda:
                        tipo_evento = 'Reversão: Venda → Compra'
                    elif not tipo_evento and vol_ant_compra > limite_volume and vol_venda_trecho > limite_volume and vol_venda_trecho > vol_ant_compra:
                        tipo_evento = 'Reversão: Compra → Venda'

            # 4. Rompimentos (baseados no histórico de máximas/mínimas)
            if not tipo_evento and max_previa_historica is not None and preco_max_trecho > max_previa_historica and vol_compra_trecho > limite_volume:
                tipo_evento = 'Rompimento de Topo'

            if not tipo_evento and min_previa_historica is not None and preco_min_trecho < min_previa_historica and vol_venda_trecho > limite_volume:
                tipo_evento = 'Rompimento de Fundo'

            # Atualiza o histórico de máximas e mínimas para a PRÓXIMA iteração
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
                    'preco_medio': round(preco_medio_trecho, 2), # Arredondar para melhor visualização
                    'volume_total': vol_total_trecho,
                    'janela_usada': janela,
                    'limite_vol_usado': round(limite_volume,0)
                })
                evento_anterior = tipo_evento # Atualiza o tipo de evento anterior
            else:
                evento_anterior = None # Se nenhum evento for detectado, reseta

            # --- Ajuste Dinâmico da Janela e Limite de Volume ---
            # O ajuste é feito ao final da iteração, para valer para a próxima janela.
            nova_janela = janela
            novo_limite_volume = limite_volume

            # Calcula a média e desvio padrão dos volumes de 'lookback_stats' trades ANTERIORES ao início da janela ATUAL.
            if i > lookback_stats : # Garante que temos dados suficientes para as estatísticas
                # Série de volumes para calcular estatísticas (olhando para trás, excluindo a janela atual)
                start_index_stats = max(0, i - lookback_stats) # Início do período de lookback
                recent_volume_series = df_original['quantidade'].iloc[start_index_stats:i]

                if not recent_volume_series.empty:
                    vol_medio_recente = recent_volume_series.mean()
                    desvio_padrao_volume_recente = recent_volume_series.std()

                    if pd.notna(vol_medio_recente) and pd.notna(desvio_padrao_volume_recente) and desvio_padrao_volume_recente > 1e-6: # Evita divisão por zero ou std muito pequeno
                        vol_upper_band = vol_medio_recente + fator_dev_vol * desvio_padrao_volume_recente
                        vol_lower_band = vol_medio_recente - fator_dev_vol * desvio_padrao_volume_recente

                        # 'vol_total_trecho' é o volume da janela que acabamos de analisar
                        if vol_total_trecho > vol_upper_band: # Surto de alto volume
                            nova_janela = max(5, int(janela * 0.75)) # Reduz a janela para maior sensibilidade
                            novo_limite_volume = max(limite_vol_inicial, vol_upper_band * 0.7) # Ajusta o limite para cima, mas não abaixo do inicial
                        elif vol_total_trecho < vol_lower_band and vol_lower_band > 0: # Surto de baixo volume (significativamente abaixo da média)
                            # A lógica original também reduzia a janela. Mantendo essa premissa:
                            # Isso pode ser útil se a intenção é aumentar a sensibilidade em qualquer desvio da norma.
                            nova_janela = max(5, int(janela * 0.85)) # Reduz um pouco menos drasticamente
                            novo_limite_volume = max(limite_vol_inicial * 0.5, vol_lower_band * 1.1) # Ajusta limite para baixo, mas com um piso
                        else: # Volume dentro da normalidade
                            # Aumenta gradualmente a janela, permitindo que ela seja um pouco maior que a inicial
                            nova_janela = min(jan_inicial + int(jan_inicial * 0.25), janela + 1)
                            novo_limite_volume = limite_vol_inicial # Retorna ao limite de volume inicial
                    else: # Estatísticas não confiáveis (e.g., std zero)
                        nova_janela = jan_inicial
                        novo_limite_volume = limite_vol_inicial
                else: # Séria de volume recente vazia (improvável se i > lookback_stats)
                    nova_janela = jan_inicial
                    novo_limite_volume = limite_vol_inicial
            else: # Ainda não há dados suficientes para o lookback completo
                nova_janela = jan_inicial
                novo_limite_volume = limite_vol_inicial

            janela = nova_janela
            limite_volume = novo_limite_volume

        return pd.DataFrame(eventos)

    eventos_df = detectar_eventos_adaptativo(df, limite_volume_inicial, fator_desvio_volume, janela_inicial, lookback_period_stats)

    st.subheader("📋 Eventos Detectados")
    if eventos_df.empty:
        st.warning("Nenhum evento detectado com os parâmetros atuais.")
    else:
        st.dataframe(eventos_df)

        st.subheader("📈 Gráfico com Eventos (Altair)")

        # Gráfico de linha base para os preços
        base = alt.Chart(df).mark_line(color='lightblue').encode(
            x=alt.X('horario:T', title='Horário'),
            y=alt.Y('preco:Q', title='Preço', scale=alt.Scale(zero=False)),
            tooltip=['horario', 'preco', 'quantidade', 'agressor']
        ).interactive() # Adiciona interatividade (zoom, pan)

        # Cores para cada tipo de evento
        cores_eventos = {
            'Absorção Passiva de Compra': 'darkblue',
            'Absorção Passiva de Venda': 'darkred',
            'Absorção Ativa de Compra': 'green',
            'Absorção Ativa de Venda': 'orange',
            'Reversão: Venda → Compra': 'purple',
            'Reversão: Compra → Venda': 'brown',
            'Rompimento de Topo': 'lime',
            'Rompimento de Fundo': 'maroon',
            'Reversão: Venda → Compra (Pós Absorção)': 'mediumpurple',
            'Reversão: Compra → Venda (Pós Absorção)': 'sienna'
        }

        # Criando marcações (regras verticais) para os eventos
        event_marks = alt.Chart(eventos_df).mark_rule(size=2, opacity=0.7).encode(
            x='inicio:T',
            color=alt.Color('tipo:N',
                            scale=alt.Scale(domain=list(cores_eventos.keys()),
                                            range=list(cores_eventos.values())),
                            legend=alt.Legend(title="Tipos de Evento")),
            tooltip=['tipo', 'inicio', 'fim', 'preco_medio', 'volume_total', 'janela_usada', 'limite_vol_usado']
        )

        # Adicionando texto para os eventos (opcional, pode poluir o gráfico)
        # Se não quiser os textos, comente o bloco 'event_text' abaixo
        # e use a linha comentada na atribuição de 'chart'.
        event_text = event_marks.mark_text(
            align='left',
            baseline='middle',
            dx=7,      # Pequeno deslocamento em X para não sobrepor a linha
            dy=-7,      # Pequeno deslocamento em Y para posicionar acima/diagonal à linha
            angle=0      # Ângulo do texto (0 para horizontal)
        ).encode(
            text='tipo:N' # Mostra o tipo do evento como texto
        )

        # Combinando o gráfico base com as marcações de eventos e os textos
        # Se não quiser os textos, comente a linha abaixo:
        chart = (base + event_marks + event_text).properties(
        # E descomente esta linha:
        # chart = (base + event_marks).properties(
            width=700,
            height=500,
            title="Preços ao Longo do Tempo com Eventos Detectados"
        )
        st.altair_chart(chart, use_container_width=True)

else:
    st.info("ℹ️ Por favor, faça o upload de uma planilha Excel (.xlsx) para
