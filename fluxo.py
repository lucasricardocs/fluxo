import streamlit as st
import pandas as pd
import altair as alt

st.set_page_config(page_title="Detector de Fluxo - Times & Trades", layout="wide")
st.title("📊 Detector de Absorções, Reversões e Rompimentos")
st.markdown("Detecta **absorções**, **reversões** e **rompimentos** em dados de Times & Trades com visualização interativa.")

uploaded_file = st.file_uploader("📎 Faça o upload da planilha (.xlsx)", type="xlsx")

if uploaded_file:
    df = pd.read_excel(uploaded_file)

    # Renomear colunas conforme a planilha
    df = df.rename(columns={
        'Data': 'horario',
        'Valor': 'preco',
        'Quantidade': 'quantidade',
        'Agressor': 'agressor'
    })

    df['horario'] = pd.to_datetime(df['horario'].astype(str), format="%H:%M:%S")

    st.success("✅ Planilha carregada com sucesso!")

    st.sidebar.header("⚙️ Parâmetros de Análise")
    janela = st.sidebar.slider("Tamanho da janela", 5, 50, 10)
    limite_volume = st.sidebar.slider("Volume mínimo", 100, 5000, 1000, step=100)

    def detectar_eventos(df, janela, limite_volume):
        eventos = []
        max_previa = None
        min_previa = None

        for i in range(len(df) - janela):
            trecho = df.iloc[i:i+janela]
            compradores = trecho[trecho['agressor'].str.lower() == 'comprador']
            vendedores = trecho[trecho['agressor'].str.lower() == 'vendedor']

            preco_max = trecho['preco'].max()
            preco_min = trecho['preco'].min()
            preco_medio = trecho['preco'].mean()
            vol_total = trecho['quantidade'].sum()
            vol_compra = compradores['quantidade'].sum()
            vol_venda = vendedores['quantidade'].sum()

            tipo = None

            if vol_venda > limite_volume and preco_min == vendedores['preco'].mode().iloc[0]:
                tipo = 'Absorção Passiva de Compra'
            elif vol_compra > limite_volume and preco_max == compradores['preco'].mode().iloc[0]:
                tipo = 'Absorção Passiva de Venda'
            elif vol_compra > limite_volume and preco_max > trecho['preco'].min():
                tipo = 'Absorção Ativa de Compra'
            elif vol_venda > limite_volume and preco_min < trecho['preco'].max():
                tipo = 'Absorção Ativa de Venda'

            trecho_ant = df.iloc[i-janela:i] if i >= janela else None
            if trecho_ant is not None:
                vol_ant_compra = trecho_ant[trecho_ant['agressor'].str.lower() == 'comprador']['quantidade'].sum()
                vol_ant_venda = trecho_ant[trecho_ant['agressor'].str.lower() == 'vendedor']['quantidade'].sum()
                if vol_ant_venda > limite_volume and vol_compra > limite_volume:
                    tipo = 'Reversão: Venda → Compra'
                elif vol_ant_compra > limite_volume and vol_venda > limite_volume:
                    tipo = 'Reversão: Compra → Venda'

            if max_previa and preco_max > max_previa and vol_compra > limite_volume:
                tipo = 'Rompimento de Topo'
            if min_previa and preco_min < min_previa and vol_venda > limite_volume:
                tipo = 'Rompimento de Fundo'

            max_previa = max(max_previa or preco_max, preco_max)
            min_previa = min(min_previa or preco_min, preco_min)

            if tipo:
                eventos.append({
                    'inicio': trecho['horario'].iloc[0],
                    'fim': trecho['horario'].iloc[-1],
                    'tipo': tipo,
                    'preco_medio': preco_medio,
                    'volume_total': vol_total
                })

        return pd.DataFrame(eventos)

    eventos_df = detectar_eventos(df, janela, limite_volume)

    st.subheader("📋 Eventos Detectados")
    if eventos_df.empty:
        st.warning("Nenhum evento detectado com os parâmetros atuais.")
    else:
        st.dataframe(eventos_df)

        st.subheader("📈 Gráfico com Eventos (Altair)")

        base = alt.Chart(df).mark_line(color='gray').encode(
            x=alt.X('horario:T', title='Horário'),
            y=alt.Y('preco:Q', title='Preço'),
            tooltip=['horario', 'preco', 'quantidade', 'agressor']
        )

        cores = {
            'Absorção Passiva de Compra': 'blue',
            'Absorção Passiva de Venda': 'red',
            'Absorção Ativa de Compra': 'green',
            'Absorção Ativa de Venda': 'orange',
            'Reversão: Venda → Compra': 'purple',
            'Reversão: Compra → Venda': 'brown',
            'Rompimento de Topo': 'darkgreen',
            'Rompimento de Fundo': 'darkred'
        }

        eventos_chart = alt.Chart(eventos_df).mark_rule(size=2).encode(
            x='inicio:T',
            color=alt.Color('tipo:N', scale=alt.Scale(domain=list(cores.keys()), range=list(cores.values()))),
            tooltip=['tipo', 'inicio', 'fim', 'volume_total']
        )

        chart = (base + eventos_chart).properties(width=700, height=500)
        st.altair_chart(chart, use_container_width=True)
